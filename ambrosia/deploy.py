from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import Settings


SERVICE_LABEL = "com.ambrosia.health"


class DeploymentError(RuntimeError):
    pass


def _machine_name() -> str:
    result = subprocess.run(
        ["system_profiler", "SPHardwareDataType"], capture_output=True, check=True, text=True
    )
    for line in result.stdout.splitlines():
        if "Model Name:" in line:
            return line.split(":", 1)[1].strip()
    return "unknown Mac"


def launch_agent_payload(
    app_settings: Settings,
    project_root: Path,
    uv_path: Path,
    credentials: Path,
    token: Path,
) -> dict[str, Any]:
    logs = app_settings.home / "logs"
    return {
        "Label": SERVICE_LABEL,
        "ProgramArguments": [
            str(project_root / ".venv" / "bin" / "ambrosia"),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(app_settings.port),
        ],
        "WorkingDirectory": str(project_root),
        "EnvironmentVariables": {
            "HOME": str(Path.home()),
            "AMBROSIA_HOME": str(app_settings.home),
            "AMBROSIA_GOOGLE_CREDENTIALS": str(credentials),
            "AMBROSIA_GOOGLE_TOKEN": str(token),
            "PATH": (
                f"{uv_path.parent}:{Path.home() / '.local' / 'bin'}:"
                "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            ),
        },
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 5,
        "ProcessType": "Background",
        "StandardOutPath": str(logs / "ambrosia.log"),
        "StandardErrorPath": str(logs / "ambrosia.error.log"),
    }


def install_macos(
    app_settings: Settings,
    credentials: Path,
    token: Path,
    *,
    dry_run: bool = False,
    allow_non_mini: bool = False,
) -> dict[str, Any]:
    machine = _machine_name()
    if "Mac mini" not in machine and not allow_non_mini:
        raise DeploymentError(
            f"Refusing to install the production service on {machine}; run this command on the Mac mini."
        )
    credentials = credentials.expanduser().resolve()
    token = token.expanduser().resolve()
    for path, label in ((credentials, "Google credentials"), (token, "Google token")):
        if not path.is_file():
            raise DeploymentError(f"{label} file does not exist: {path}")
    uv = shutil.which("uv")
    tailscale = shutil.which("tailscale")
    if not uv:
        raise DeploymentError("uv is not installed or is not on PATH.")
    if not tailscale:
        raise DeploymentError("Tailscale is not installed or is not on PATH.")
    project_root = Path(__file__).resolve().parents[1]
    runtime = project_root / ".venv" / "bin" / "ambrosia"
    if not runtime.is_file():
        raise DeploymentError("Run `uv sync --frozen` before installing the service.")
    frontend = project_root / "web" / "dist" / "index.html"
    if not frontend.is_file():
        raise DeploymentError("Build the frontend before installing the service.")
    payload = launch_agent_payload(app_settings, project_root, Path(uv), credentials, token)
    agent_path = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
    serve_command = [tailscale, "serve", "--bg", "--yes", f"http://127.0.0.1:{app_settings.port}"]
    result = {
        "machine": machine,
        "launch_agent": str(agent_path),
        "service_label": SERVICE_LABEL,
        "serve_command": serve_command,
        "dry_run": dry_run,
    }
    if dry_run:
        result["plist"] = payload
        return result

    app_settings.ensure_directories()
    (app_settings.home / "logs").mkdir(parents=True, exist_ok=True, mode=0o700)
    agent_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = agent_path.with_suffix(".plist.part")
    temporary.write_bytes(plistlib.dumps(payload, sort_keys=True))
    temporary.chmod(0o600)
    temporary.replace(agent_path)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(agent_path)], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(agent_path)], check=True)
    subprocess.run(["launchctl", "enable", f"{domain}/{SERVICE_LABEL}"], check=True)
    subprocess.run(serve_command, check=True)
    result["service_status"] = "started"
    return result
