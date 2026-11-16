"""CLI regression tests for the explicit application-submission opt-in."""

from typer.testing import CliRunner

from applypilot.cli import app


def test_apply_command_exposes_explicit_submit_flag():
    result = CliRunner().invoke(app, ["apply", "--help"])

    assert result.exit_code == 0
    assert "--submit" in result.stdout
    assert "Explicitly authorize submission" in result.stdout
