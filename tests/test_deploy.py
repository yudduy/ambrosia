from __future__ import annotations

from pathlib import Path

from ambrosia.deploy import SERVICE_LABEL, _copy_runtime_sources, launch_agent_payload


def test_launch_agent_is_loopback_only_and_keeps_secrets_out_of_arguments(app_settings, tmp_path: Path):
    project = tmp_path / "project"
    credentials = tmp_path / "credentials.json"
    token = tmp_path / "token.json"
    payload = launch_agent_payload(app_settings, project, Path("/opt/homebrew/bin/uv"), credentials, token)
    arguments = payload["ProgramArguments"]
    assert arguments[0] == str(project / ".venv" / "bin" / "ambrosia")
    assert arguments[-4:] == ["--host", "127.0.0.1", "--port", "8787"]
    assert payload["Label"] == SERVICE_LABEL
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert str(credentials) not in arguments
    assert str(token) not in arguments
    assert payload["EnvironmentVariables"]["AMBROSIA_GOOGLE_TOKEN"] == str(token)
    assert payload["EnvironmentVariables"]["HOME"] == str(Path.home())
    assert str(Path.home() / ".local" / "bin") in payload["EnvironmentVariables"]["PATH"].split(":")


def test_runtime_copy_excludes_build_caches(tmp_path: Path):
    source = tmp_path / "source"
    for filename in ("pyproject.toml", "uv.lock", "README.md"):
        (source / filename).parent.mkdir(parents=True, exist_ok=True)
        (source / filename).write_text(filename)
    (source / "ambrosia" / "__pycache__").mkdir(parents=True)
    (source / "ambrosia" / "api.py").write_text("app = True")
    (source / "ambrosia" / "__pycache__" / "api.pyc").write_bytes(b"cache")
    (source / "web" / "dist").mkdir(parents=True)
    (source / "web" / "dist" / "index.html").write_text("Ambrosia")
    (source / "sidecar" / "src").mkdir(parents=True)
    (source / "sidecar" / "src" / "main.ts").write_text("export {}")
    (source / "sidecar" / "node_modules").mkdir()
    (source / "sidecar" / "node_modules" / "ignored.js").write_text("ignored")

    destination = tmp_path / "destination"
    _copy_runtime_sources(source, destination)

    assert (destination / "ambrosia" / "api.py").is_file()
    assert (destination / "web" / "dist" / "index.html").is_file()
    assert (destination / "sidecar" / "src" / "main.ts").is_file()
    assert not (destination / "ambrosia" / "__pycache__").exists()
    assert not (destination / "sidecar" / "node_modules").exists()
