"""Tests for git-narrator CLI entrypoint and commands."""

from click.testing import CliRunner

from git_narrator.cli import cli


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "git-narrator" in result.output
    assert "0.1.0" in result.output


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Understand any git diff in 5 seconds." in result.output
    assert "commit" in result.output
    assert "pr" in result.output
    assert "diff" in result.output
    assert "config" in result.output


def test_cli_config_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["config"])
    assert result.exit_code == 0
    assert "git-narrator Configuration" in result.output
    assert "Active Provider" in result.output
