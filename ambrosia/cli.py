from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import webbrowser
from pathlib import Path

import uvicorn

from .assistant import CodexAppServerProvider, OmpSidecarProvider, analyze_meal
from .config import Settings
from .db import Database
from .deploy import install_macos
from .google_health import GoogleHealthSync, begin_authorization, complete_authorization
from .importer import ExportImporter, validate_manifest


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Ambrosia private personal-health dashboard")
    root.add_argument("--home", type=Path, help="Override AMBROSIA_HOME for this command")
    commands = root.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Run the API and compiled dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    import_command = commands.add_parser("import", help="Import an existing Google Health export")
    import_command.add_argument("export_dir", type=Path)
    validate = commands.add_parser("validate-export", help="Count and validate an export without importing")
    validate.add_argument("export_dir", type=Path)
    sync = commands.add_parser("sync", help="Run one incremental Google Health sync")
    sync.add_argument("--type", action="append", dest="types")
    authorize = commands.add_parser("google-auth", help="Authorize all read-only Google Health scopes")
    authorize.add_argument("--credentials", type=Path, required=True)
    authorize.add_argument("--token", type=Path, required=True)
    install = commands.add_parser("install-macos", help="Install launchd and private Tailscale Serve")
    install.add_argument("--credentials", type=Path, required=True)
    install.add_argument("--token", type=Path, required=True)
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--allow-non-mini", action="store_true", help=argparse.SUPPRESS)
    gate = commands.add_parser("assistant-gate", help="Run the complete assistant compatibility checks")
    gate.add_argument("--provider", choices=("codex-app-server", "omp"))
    gate.add_argument("--activate-fallback", action="store_true")
    return root


async def _wait_for_turn(provider, thread_id: str, turn_id: str) -> tuple[str, bool, str]:
    mcp_called = False
    text = ""
    async for event in provider.events(thread_id):
        method = event.get("method")
        params = event.get("params") or {}
        event_turn_id = params.get("turnId") or (params.get("turn") or {}).get("id")
        if event_turn_id != turn_id:
            continue
        if method == "item/completed":
            item = params.get("item") or {}
            if item.get("type") == "mcpToolCall":
                mcp_called = True
            elif item.get("type") == "agentMessage":
                text = str(item.get("text") or "")
        if method == "turn/completed":
            return str((params.get("turn") or {}).get("status")), mcp_called, text


def _event_turn_id(event: dict) -> str | None:
    params = event.get("params") or {}
    return params.get("turnId") or (params.get("turn") or {}).get("id")


async def _wait_for_turn_activity(provider, thread_id: str, turn_id: str, timeout: float = 30) -> bool:
    stream = provider.events(thread_id)
    while True:
        event = await asyncio.wait_for(anext(stream), timeout=timeout)
        if _event_turn_id(event) != turn_id:
            continue
        method = event.get("method")
        if method == "turn/completed":
            return False
        if method in {"turn/started", "turn/updated", "item/started", "item/completed"}:
            return True


def _provider(name: str, app_settings: Settings):
    return OmpSidecarProvider(app_settings) if name == "omp" else CodexAppServerProvider(app_settings)


async def assistant_gate(app_settings: Settings, provider_name: str) -> dict:
    from PIL import Image, ImageDraw

    provider = _provider(provider_name, app_settings)
    status = await provider.status()
    checks = {
        "authenticated": status.authenticated,
        "image_capable_model": status.image_capable_model,
        "restricted_text_stream": False,
        "meal_schema": False,
        "mcp_available": False,
        "filesystem_boundary": provider_name == "omp",
        "token_refresh": False,
        "interruption": False,
        "resume": False,
    }
    if not status.authenticated or not status.image_capable_model:
        await provider.close()
        return {"passed": False, "checks": checks, "status": status.model_dump(mode="json")}
    test_image = app_settings.upload_dir / "assistant-gate-meal.webp"
    gate_error: str | None = None
    try:
        checks["token_refresh"] = await provider.refresh_auth()
        thread_id = await provider.create_thread()
        turn_id = await provider.start_turn(
            thread_id,
            "Call get_profile_and_data_quality, then answer with exactly: Ambrosia connection verified.",
        )
        turn_status, mcp_called, text = await _wait_for_turn(provider, thread_id, turn_id)
        checks["mcp_available"] = mcp_called
        checks["restricted_text_stream"] = turn_status == "completed" and bool(text)

        image = Image.new("RGB", (480, 320), "#d9b382")
        drawing = ImageDraw.Draw(image)
        drawing.ellipse((80, 110, 400, 300), fill="#315c49")
        drawing.ellipse((110, 125, 370, 270), fill="#f4eee3")
        drawing.rectangle((145, 155, 230, 225), fill="#bc6c43")
        drawing.ellipse((240, 145, 340, 235), fill="#78a55a")
        image.save(test_image, format="WEBP", quality=85)
        meal = await analyze_meal(provider, test_image, "synthetic chicken and greens bowl")
        checks["meal_schema"] = meal.calories.high >= meal.calories.low and 0 <= meal.confidence <= 1

        interrupt_verified = False
        interrupt_prompt = (
            "Do not call tools. Keep writing 'still streaming <n>' on separate lines, starting at 1, "
            "until you are interrupted. Do not summarize or stop early."
        )
        for _ in range(2):
            interrupt_thread = await provider.create_thread()
            interrupt_id = await provider.start_turn(interrupt_thread, interrupt_prompt)
            active = await _wait_for_turn_activity(provider, interrupt_thread, interrupt_id)
            if not active:
                continue
            try:
                await provider.interrupt_turn(interrupt_thread, interrupt_id)
            except Exception as error:
                if "no active turn to interrupt" not in str(error):
                    raise
            interrupted_status, _, _ = await _wait_for_turn(provider, interrupt_thread, interrupt_id)
            checks["interruption"] = interrupted_status in {"interrupted", "completed"}
            interrupt_verified = True
            break
        if not interrupt_verified:
            gate_error = "Unable to observe an active turn before interruption."

        await provider.close()
        provider = _provider(provider_name, app_settings)
        restarted = await provider.status()
        await provider.resume_thread(thread_id)
        resumed_turn = await provider.start_turn(thread_id, "Reply with exactly: resume verified.")
        resumed_status, _, resumed_text = await _wait_for_turn(provider, thread_id, resumed_turn)
        checks["resume"] = restarted.authenticated and resumed_status == "completed" and (
            resumed_text.strip().lower() == "resume verified."
        )
    except Exception as error:
        gate_error = str(error)
    finally:
        await provider.close()
        test_image.unlink(missing_ok=True)
    passed = all(checks.values())
    return {
        "passed": passed, "checks": checks, "status": status.model_dump(mode="json"),
        "error": gate_error,
        "reason": None if passed else (
            "Codex app-server cannot prove an upload-only filesystem boundary; activate the OMP fallback."
            if provider_name == "codex-app-server" and not checks["filesystem_boundary"] else
            "One or more mandatory provider checks failed."
        ),
    }


def main() -> int:
    args = parser().parse_args()
    overrides = {"home": args.home} if args.home else {}
    app_settings = Settings(**overrides)
    try:
        if args.command == "serve":
            os.environ["AMBROSIA_HOME"] = str(app_settings.home)
            uvicorn.run("ambrosia.api:create_app", factory=True, host=args.host, port=args.port)
        elif args.command == "validate-export":
            print(json.dumps(validate_manifest(args.export_dir), indent=2))
        elif args.command == "import":
            result = ExportImporter(Database(app_settings), app_settings).import_directory(args.export_dir)
            print(json.dumps(result, indent=2, default=str))
        elif args.command == "sync":
            result = GoogleHealthSync(Database(app_settings), app_settings).run("manual", args.types)
            print(json.dumps(result, indent=2, default=str))
        elif args.command == "google-auth":
            authorization = begin_authorization(args.credentials)
            print("Opening Google authorization. Approve the read-only scopes, including nutrition.")
            print("After Google redirects, copy the complete browser URL and paste it here.")
            if not webbrowser.open(authorization["url"]):
                print(f"Open this URL manually:\n{authorization['url']}")
            redirected_url = input("Redirected URL: ").strip()
            result = complete_authorization(
                args.credentials.resolve(), args.token.resolve(), redirected_url, authorization
            )
            print(json.dumps(result, indent=2))
        elif args.command == "install-macos":
            result = install_macos(
                app_settings,
                args.credentials,
                args.token,
                dry_run=args.dry_run,
                allow_non_mini=args.allow_non_mini,
            )
            print(json.dumps(result, indent=2))
        elif args.command == "assistant-gate":
            provider_name = args.provider or app_settings.assistant_provider
            result = asyncio.run(assistant_gate(app_settings, provider_name))
            if args.activate_fallback and provider_name == "codex-app-server" and not result["passed"]:
                app_settings.ensure_directories()
                temporary = app_settings.assistant_provider_path.with_suffix(".json.part")
                temporary.write_text(json.dumps({"provider": "omp", "reason": result["reason"]}, indent=2) + "\n")
                temporary.chmod(0o600)
                temporary.replace(app_settings.assistant_provider_path)
                result["fallback_activated"] = True
            print(json.dumps(result, indent=2))
            return 0 if result["passed"] else 2
        return 0
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
