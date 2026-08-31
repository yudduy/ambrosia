from __future__ import annotations

from pathlib import Path

from ambrosia.deploy import SERVICE_LABEL, launch_agent_payload


def test_launch_agent_is_loopback_only_and_keeps_secrets_out_of_arguments(app_settings, tmp_path: Path):
    project = tmp_path / "project"
    credentials = tmp_path / "credentials.json"
    token = tmp_path / "token.json"
    payload = launch_agent_payload(app_settings, project, Path("/opt/homebrew/bin/uv"), credentials, token)
    arguments = payload["ProgramArguments"]
    assert arguments[-4:] == ["--host", "127.0.0.1", "--port", "8787"]
    assert payload["Label"] == SERVICE_LABEL
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert str(credentials) not in arguments
    assert str(token) not in arguments
    assert payload["EnvironmentVariables"]["AMBROSIA_GOOGLE_TOKEN"] == str(token)
    assert str(Path.home() / ".local" / "bin") in payload["EnvironmentVariables"]["PATH"].split(":")
