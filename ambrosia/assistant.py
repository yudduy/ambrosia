from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import Any

from .config import Settings, settings
from .models import AssistantStatus, DailyInsightDraft, MealAnalysis


SAFETY_CONTEXT = """You are Ambrosia, a private personal health coach. Use only the bounded
Ambrosia MCP tools and the user-provided text or meal image. Describe patterns and uncertainty;
do not diagnose, prescribe treatment, recommend medication changes, or claim that association is
causation. Ask no more than three short intake questions when essential context is missing. Never
write health data or profile changes. If a profile fact should be saved, explicitly propose it as a
'Remember this' confirmation. Do not use shell, filesystem browsing, or network tools."""


class AssistantError(RuntimeError):
    pass


class AssistantProvider(ABC):
    @abstractmethod
    async def status(self) -> AssistantStatus: ...

    @abstractmethod
    async def start_login(self) -> dict[str, Any]: ...

    @abstractmethod
    async def create_thread(self) -> str: ...

    @abstractmethod
    async def resume_thread(self, provider_thread_id: str) -> None: ...

    @abstractmethod
    async def start_turn(
        self, provider_thread_id: str, text: str, image_path: Path | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> str: ...

    @abstractmethod
    async def events(self, provider_thread_id: str) -> AsyncIterator[dict[str, Any]]: ...


class CodexAppServerProvider(AssistantProvider):
    def __init__(self, app_settings: Settings = settings):
        self.settings = app_settings
        self.process: asyncio.subprocess.Process | None = None
        self.reader_task: asyncio.Task | None = None
        self.stderr_task: asyncio.Task | None = None
        self.request_id = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.queues: defaultdict[str, list[asyncio.Queue]] = defaultdict(list)
        self.history: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        self.model: str | None = None
        self.effort: str = "medium"
        self._write_lock = asyncio.Lock()
        self._event_sequence = 0

    async def close(self) -> None:
        if not self.process or self.process.returncode is not None:
            return
        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=5)
        except TimeoutError:
            self.process.kill()
            await self.process.wait()
        for task in (self.reader_task, self.stderr_task):
            if task and not task.done():
                task.cancel()

    def _write_config(self) -> None:
        self.settings.ensure_directories()
        executable = str(Path(sys.executable)).replace("\\", "\\\\").replace('"', '\\"')
        home = str(self.settings.home).replace("\\", "\\\\").replace('"', '\\"')
        api_url = f"http://127.0.0.1:{self.settings.port}/api"
        content = (
            '[mcp_servers.ambrosia]\n'
            f'command = "{executable}"\n'
            'args = ["-m", "ambrosia.mcp_server"]\n'
            'required = true\n'
            f'env = {{ AMBROSIA_HOME = "{home}", AMBROSIA_API_URL = "{api_url}" }}\n'
        )
        target = self.settings.codex_home / "config.toml"
        temporary = target.with_suffix(".toml.part")
        temporary.write_text(content)
        temporary.chmod(0o600)
        temporary.replace(target)

    async def ensure_started(self) -> None:
        if self.process and self.process.returncode is None:
            return
        self._write_config()
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
            "CODEX_HOME": str(self.settings.codex_home),
            "AMBROSIA_HOME": str(self.settings.home),
            "HOME": os.environ.get("HOME", str(Path.home())),
        }
        self.process = await asyncio.create_subprocess_exec(
            "codex", "app-server", "--stdio",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=environment,
        )
        self.reader_task = asyncio.create_task(self._read_messages())
        self.stderr_task = asyncio.create_task(self._drain_stderr())
        await self._request(
            "initialize",
            {
                "clientInfo": {"name": "ambrosia", "title": "Ambrosia", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        await self._notify("initialized", {})

    async def _read_messages(self) -> None:
        assert self.process and self.process.stdout
        while line := await self.process.stdout.readline():
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            message_id = message.get("id")
            if message_id is not None and ("result" in message or "error" in message):
                future = self.pending.pop(message_id, None)
                if future and not future.done():
                    if "error" in message:
                        future.set_exception(AssistantError(str(message["error"])))
                    else:
                        future.set_result(message.get("result"))
                continue
            if message_id is not None and message.get("method"):
                await self._respond_error(message_id, "Ambrosia does not permit interactive approvals or writes.")
                continue
            params = message.get("params") or {}
            provider_thread_id = params.get("threadId") or (params.get("thread") or {}).get("id")
            if provider_thread_id:
                self._event_sequence += 1
                message["_ambrosia_sequence"] = self._event_sequence
                self.history[provider_thread_id].append(message)
                if len(self.history[provider_thread_id]) > 500:
                    self.history[provider_thread_id] = self.history[provider_thread_id][-500:]
                for queue in list(self.queues[provider_thread_id]):
                    await queue.put(message)

        failure = AssistantError("Codex app-server stopped unexpectedly.")
        for future in self.pending.values():
            if not future.done():
                future.set_exception(failure)
        self.pending.clear()

    async def _drain_stderr(self) -> None:
        assert self.process and self.process.stderr
        while await self.process.stderr.readline():
            pass

    async def _send(self, payload: dict[str, Any]) -> None:
        await self.ensure_process_pipe()
        encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        async with self._write_lock:
            assert self.process and self.process.stdin
            self.process.stdin.write(encoded)
            await self.process.stdin.drain()

    async def ensure_process_pipe(self) -> None:
        if not self.process or self.process.returncode is not None or not self.process.stdin:
            raise AssistantError("Codex app-server is not running.")

    async def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.request_id += 1
        request_id = self.request_id
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        await self._send({"method": method, "id": request_id, "params": params or {}})
        try:
            return await asyncio.wait_for(future, timeout=120)
        except TimeoutError as error:
            self.pending.pop(request_id, None)
            raise AssistantError(f"Codex app-server timed out during {method}.") from error

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"method": method, "params": params})

    async def _respond_error(self, request_id: int, message: str) -> None:
        await self._send({"id": request_id, "error": {"code": -32001, "message": message}})

    async def status(self) -> AssistantStatus:
        try:
            await self.ensure_started()
            account = await self._request("account/read", {"refreshToken": False})
            models = await self._request("model/list", {"limit": 100, "includeHidden": False})
            choices = [
                item for item in models.get("data", [])
                if "image" in item.get("inputModalities", ["text", "image"])
            ]
            selected = next((item for item in choices if item.get("isDefault")), choices[0] if choices else None)
            self.model = (selected or {}).get("model") or (selected or {}).get("id")
            self.effort = (selected or {}).get("defaultReasoningEffort") or "medium"
            authenticated = bool(account.get("account"))
            return AssistantStatus(
                provider="codex-app-server", running=True, authenticated=authenticated,
                image_capable_model=bool(self.model), model=self.model,
                reason=None if authenticated else "Sign in with ChatGPT to use Ask Ambrosia.",
            )
        except Exception as error:
            return AssistantStatus(
                provider="codex-app-server", running=False, authenticated=False,
                image_capable_model=False, model=None, reason=str(error),
            )

    async def start_login(self) -> dict[str, Any]:
        await self.ensure_started()
        return await self._request(
            "account/login/start",
            {"type": "chatgpt", "useHostedLoginSuccessPage": True, "appBrand": "chatgpt"},
        )

    async def refresh_auth(self) -> bool:
        await self.ensure_started()
        result = await self._request("account/read", {"refreshToken": True})
        return bool(result.get("account"))

    async def interrupt_turn(self, provider_thread_id: str, turn_id: str) -> None:
        await self.ensure_started()
        await self._request("turn/interrupt", {"threadId": provider_thread_id, "turnId": turn_id})

    async def create_thread(self) -> str:
        await self.ensure_started()
        if not self.model:
            status = await self.status()
            if not status.model:
                raise AssistantError("No image-capable Codex model is available.")
        result = await self._request(
            "thread/start",
            {
                "model": self.model,
                "cwd": str(self.settings.upload_dir),
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "serviceName": "ambrosia",
                "developerInstructions": SAFETY_CONTEXT,
                "runtimeWorkspaceRoots": [str(self.settings.upload_dir)],
                "config": {"web_search": "disabled"},
            },
        )
        return str(result["thread"]["id"])

    async def resume_thread(self, provider_thread_id: str) -> None:
        await self.ensure_started()
        await self._request(
            "thread/resume",
            {
                "threadId": provider_thread_id, "cwd": str(self.settings.upload_dir),
                "approvalPolicy": "never", "sandbox": "read-only",
            },
        )

    async def start_turn(
        self, provider_thread_id: str, text: str, image_path: Path | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> str:
        await self.ensure_started()
        inputs: list[dict[str, Any]] = [
            {"type": "text", "text": f"{SAFETY_CONTEXT}\n\nUser request:\n{text}"}
        ]
        if image_path:
            resolved = image_path.resolve()
            if self.settings.upload_dir.resolve() not in resolved.parents:
                raise AssistantError("Meal images must be inside Ambrosia's sanitized upload directory.")
            inputs.append({"type": "localImage", "path": str(resolved)})
        params: dict[str, Any] = {
            "threadId": provider_thread_id,
            "input": inputs,
            "cwd": str(self.settings.upload_dir),
            "approvalPolicy": "never",
            "sandboxPolicy": {
                "type": "readOnly", "networkAccess": False,
            },
            "model": self.model,
            "effort": self.effort,
            "summary": "concise",
        }
        if output_schema:
            params["outputSchema"] = output_schema
        result = await self._request("turn/start", params)
        return str(result["turn"]["id"])

    async def events(
        self, provider_thread_id: str, after_sequence: int = 0
    ) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.queues[provider_thread_id].append(queue)
        try:
            for event in self.history[provider_thread_id]:
                if int(event.get("_ambrosia_sequence", 0)) > after_sequence:
                    yield event
            while True:
                event = await queue.get()
                if int(event.get("_ambrosia_sequence", 0)) > after_sequence:
                    yield event
        finally:
            self.queues[provider_thread_id].remove(queue)

    async def run_structured(
        self, prompt: str, schema: dict[str, Any], image_path: Path | None = None,
        timeout: float = 180,
    ) -> dict[str, Any]:
        thread_id = await self.create_thread()
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.queues[thread_id].append(queue)
        try:
            turn_id = await self.start_turn(thread_id, prompt, image_path, schema)
            final_text: str | None = None
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=timeout)
                method = event.get("method")
                params = event.get("params") or {}
                if method == "item/completed":
                    item = params.get("item") or {}
                    if item.get("type") == "agentMessage":
                        final_text = item.get("text")
                if method == "turn/completed" and (params.get("turn") or {}).get("id") == turn_id:
                    turn = params.get("turn") or {}
                    if turn.get("status") != "completed":
                        raise AssistantError(str(turn.get("error") or "Structured turn failed."))
                    if not final_text:
                        raise AssistantError("Structured turn completed without an agent message.")
                    candidate = final_text.strip()
                    if candidate.startswith("```"):
                        candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                    return json.loads(candidate)
        finally:
            self.queues[thread_id].remove(queue)


class OmpSidecarProvider(CodexAppServerProvider):
    async def ensure_started(self) -> None:
        if self.process and self.process.returncode is None:
            return
        self.settings.ensure_directories()
        project_root = Path(__file__).resolve().parents[1]
        sidecar = project_root / "sidecar" / "src" / "main.ts"
        bun = os.environ.get("AMBROSIA_BUN", "bun")
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
            "HOME": os.environ.get("HOME", str(Path.home())),
            "AMBROSIA_HOME": str(self.settings.home),
            "AMBROSIA_API_URL": f"http://127.0.0.1:{self.settings.port}/api",
        }
        self.process = await asyncio.create_subprocess_exec(
            bun, "run", str(sidecar), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=project_root / "sidecar", env=environment,
        )
        self.reader_task = asyncio.create_task(self._read_messages())
        self.stderr_task = asyncio.create_task(self._drain_stderr())

    async def status(self) -> AssistantStatus:
        try:
            await self.ensure_started()
            return AssistantStatus.model_validate(await self._request("status"))
        except Exception as error:
            return AssistantStatus(
                provider="omp", running=False, authenticated=False,
                image_capable_model=False, model=None, reason=str(error),
            )

    async def start_login(self) -> dict[str, Any]:
        await self.ensure_started()
        return await self._request("login/start")

    async def refresh_auth(self) -> bool:
        await self.ensure_started()
        result = await self._request("auth/refresh")
        return bool(result.get("refreshed"))

    async def create_thread(self) -> str:
        await self.ensure_started()
        result = await self._request("thread/create")
        return str(result["threadId"])

    async def resume_thread(self, provider_thread_id: str) -> None:
        await self.ensure_started()
        await self._request("thread/resume", {"threadId": provider_thread_id})

    async def start_turn(
        self, provider_thread_id: str, text: str, image_path: Path | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> str:
        if image_path:
            resolved = image_path.resolve()
            if self.settings.upload_dir.resolve() not in resolved.parents:
                raise AssistantError("Meal images must be inside Ambrosia's sanitized upload directory.")
        await self.ensure_started()
        result = await self._request(
            "turn/start",
            {
                "threadId": provider_thread_id, "text": text,
                "imagePath": str(image_path.resolve()) if image_path else None,
                "outputSchema": output_schema,
            },
        )
        return str(result["turnId"])

    async def interrupt_turn(self, provider_thread_id: str, turn_id: str) -> None:
        await self._request("turn/interrupt", {"threadId": provider_thread_id, "turnId": turn_id})


def assistant_provider(app_settings: Settings = settings) -> CodexAppServerProvider:
    selected = app_settings.assistant_provider
    try:
        configured = json.loads(app_settings.assistant_provider_path.read_text())
        selected = str(configured.get("provider", selected))
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError):
        selected = app_settings.assistant_provider
    if selected == "omp":
        return OmpSidecarProvider(app_settings)
    return CodexAppServerProvider(app_settings)


MEAL_PROMPT = """Analyze this meal photo and optional note. Return conservative editable ranges,
not exact values. Include visible ingredients, meal type, confidence from 0 to 1, and a short note
about what the image cannot establish. Do not infer medical conditions. Optional note: {note}"""

DAILY_INSIGHT_PROMPT = """Call get_health_overview for {as_of}. Write one plain-English sentence
of at most 24 words that helps the user understand that day at a glance. Use only the returned
evidence. Mention at most two useful facts. Prefer available activity when recovery data is missing.
Do not recalculate or invent a score, grade the day, give advice, or make a medical claim. If there
is no meaningful measured data, return exactly: Not enough data yet."""


def strict_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    output = copy.deepcopy(schema)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list((node.get("properties") or {}).keys())
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(output)
    return output


async def analyze_meal(provider: CodexAppServerProvider, image_path: Path, note: str | None) -> MealAnalysis:
    result = await provider.run_structured(
        MEAL_PROMPT.format(note=note or "none"), strict_output_schema(MealAnalysis.model_json_schema()),
        image_path=image_path,
    )
    return MealAnalysis.model_validate(result)


async def generate_daily_insight(provider: CodexAppServerProvider, as_of: date) -> DailyInsightDraft:
    result = await provider.run_structured(
        DAILY_INSIGHT_PROMPT.format(as_of=as_of.isoformat()),
        strict_output_schema(DailyInsightDraft.model_json_schema()),
    )
    return DailyInsightDraft.model_validate(result)
