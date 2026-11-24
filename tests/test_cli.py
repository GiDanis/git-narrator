"""Comprehensive tests for git-narrator CLI entrypoint, E2E pipeline, CI gate, and hooks."""

import json
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from git_narrator import __version__
from git_narrator.cli import cli
from git_narrator.providers.base import BaseLLMProvider


class _FakeProvider(BaseLLMProvider):
    """Deterministic fake async streaming LLM provider for CLI E2E testing."""

    def __init__(self, payload: dict[str, Any]):
        super().__init__(model="fake-model")
        self.payload = payload
        self.captured_user_prompts: list[str] = []

    async def stream_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: Any = None,
    ) -> AsyncIterator[str]:
        self.captured_user_prompts.append(user_prompt)
        text = json.dumps(self.payload)
        half = len(text) // 2
        yield text[:half]
        yield text[half:]


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "demo_repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    (repo / "app.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    return repo


def _sample_llm_payload(severity: str = "MEDIUM") -> dict[str, Any]:
    return {
        "executive_summary": {
            "headline": "Add authentication middleware and token verifier",
            "intent": "Enforce stateless auth across API handlers.",
            "overall_impact": "High impact on auth security.",
            "blast_radius": "HIGH",
            "tags": ["auth", "security"],
        },
        "architecture_narrative": {
            "before_state": "Unauthenticated route handlers.",
            "after_state": "Middleware checks JWT bearer headers before routing.",
            "tech_debt": "Key rotation endpoint remains stubbed.",
            "components_affected": [
                {
                    "component_name": "AuthMiddleware",
                    "mutation_type": "ADDED",
                    "summary": "Added bearer validation middleware.",
                }
            ],
        },
        "risk_radar": [
            {
                "category": "TEST_GAP",
                "severity": severity,
                "title": "Expired token path untested",
                "file_path": "app.py",
                "line_hint": "L12",
                "explanation": "No test validates HTTP 401 when JWT expires.",
                "remediation": "Add unit test with expired JWT fixture.",
            }
        ],
        "visual_flow": {
            "diagram_type": "flowchart",
            "mermaid_code": 'graph LR\nA["Client"] --> B["Middleware"]\nB --> C["Handler"]',
            "ascii_diagram": "[Client] -> [Middleware] -> [Handler]",
        },
        "review_checklist": {
            "manual_checks": ["Verify public key env var"],
            "breaking_changes": ["Anonymous requests rejected with 401"],
        },
        "conventional_commit": "feat(auth): enforce JWT middleware verification",
    }


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "git-narrator" in result.output
    assert __version__ in result.output


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Understand any git diff in 5 seconds." in result.output
    assert "commit" in result.output
    assert "pr" in result.output
    assert "diff" in result.output
    assert "config" in result.output
    assert "install-hook" in result.output


def test_cli_config_and_set_command(tmp_path: Path, monkeypatch):
    import git_narrator.config as cfg_mod

    global_cfg = tmp_path / "global_cfg" / "config.json"
    local_dir = tmp_path / "proj"
    local_dir.mkdir()
    (local_dir / ".gitnarrator.json").write_text(json.dumps({"model": "local-only-model"}), encoding="utf-8")

    monkeypatch.setattr(cfg_mod, "GLOBAL_CONFIG_PATH", global_cfg)
    monkeypatch.chdir(local_dir)

    runner = CliRunner()
    res_set = runner.invoke(cli, ["config", "set", "provider", "gemini"])
    assert res_set.exit_code == 0
    saved = json.loads(global_cfg.read_text(encoding="utf-8"))
    assert saved["provider"] == "gemini"
    # Verify local project config never leaks into global config
    assert "model" not in saved

    res_show = runner.invoke(cli, ["config"])
    assert res_show.exit_code == 0
    assert "git-narrator Configuration" in res_show.output
    assert "Active Provider" in res_show.output
    assert "GEMINI" in res_show.output


def test_cli_e2e_redacts_secrets_and_includes_untracked(tmp_path: Path, monkeypatch):
    repo = _init_repo(tmp_path)
    (repo / ".narratorignore").write_text("ignored_secret.txt\n", encoding="utf-8")
    (repo / "ignored_secret.txt").write_text("should be ignored\n", encoding="utf-8")
    # Modify tracked file (unstaged) with an AWS access key that MUST be redacted before reaching LLM
    (repo / "app.py").write_text(
        'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\ndef greet():\n    return "hello"\n',
        encoding="utf-8",
    )
    # Create brand-new untracked file
    (repo / "new_module.py").write_text("def compute(x):\n    return x * 2\n", encoding="utf-8")

    fake_provider = _FakeProvider(_sample_llm_payload(severity="LOW"))
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("git_narrator.providers.create_provider", lambda **_kw: fake_provider)

    runner = CliRunner()
    res = runner.invoke(cli, ["--provider", "gemini", "--format", "json"])
    assert res.exit_code == 0, res.output

    # Verify secret was scrubbed from prompt sent to LLM and ignored file stayed pruned
    assert len(fake_provider.captured_user_prompts) == 1
    sent_prompt = fake_provider.captured_user_prompts[0]
    assert "AKIAIOSFODNN7EXAMPLE" not in sent_prompt
    assert "[REDACTED:AWS_ACCESS_KEY]" in sent_prompt
    assert "new_module.py" in sent_prompt
    assert "should be ignored" not in sent_prompt

    # Verify deterministic CRITICAL SECURITY_LEAK risk is merged into final JSON output
    parsed = json.loads(res.output)
    assert any(
        item["category"] == "SECURITY_LEAK" and item["severity"] == "CRITICAL"
        for item in parsed["risk_radar"]
    )


def test_cli_fail_on_risk_gate(tmp_path: Path, monkeypatch):
    repo = _init_repo(tmp_path)
    fake_provider = _FakeProvider(_sample_llm_payload(severity="HIGH"))
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("git_narrator.providers.create_provider", lambda **_kw: fake_provider)

    runner = CliRunner()
    res_fail = runner.invoke(cli, ["--provider", "gemini", "--format", "markdown", "--fail-on-risk", "HIGH"])
    assert res_fail.exit_code == 1
    assert "CI Gate Failed" in res_fail.output
    assert "Expired token path untested" in res_fail.output

    res_pass = runner.invoke(cli, ["--provider", "gemini", "--format", "markdown", "--fail-on-risk", "CRITICAL"])
    assert res_pass.exit_code == 0


def test_cli_ci_mode_writes_summary_and_annotations(tmp_path: Path, monkeypatch):
    repo = _init_repo(tmp_path)
    summary_file = tmp_path / "step_summary.md"
    fake_provider = _FakeProvider(_sample_llm_payload(severity="HIGH"))

    monkeypatch.chdir(repo)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    monkeypatch.setattr("git_narrator.providers.create_provider", lambda **_kw: fake_provider)

    runner = CliRunner()
    res = runner.invoke(cli, ["--provider", "gemini", "--ci"])
    assert res.exit_code == 0
    assert "::error file=app.py" in res.output
    assert summary_file.is_file()
    summary_text = summary_file.read_text(encoding="utf-8")
    assert "Add authentication middleware and token verifier" in summary_text
    assert "https://github.com/GiDanis/git-narrator" in summary_text


def test_cli_commit_and_install_hook(tmp_path: Path, monkeypatch):
    repo = _init_repo(tmp_path)
    fake_provider = _FakeProvider(_sample_llm_payload(severity="LOW"))

    monkeypatch.chdir(repo)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("git_narrator.providers.create_provider", lambda **_kw: fake_provider)

    runner = CliRunner()

    # Install hook
    res_hook = runner.invoke(cli, ["install-hook"])
    assert res_hook.exit_code == 0
    hook_path = repo / ".git" / "hooks" / "prepare-commit-msg"
    assert hook_path.is_file()
    assert "git-narrator-managed-hook" in hook_path.read_text(encoding="utf-8")

    # Commit refuses when nothing is staged
    (repo / "app.py").write_text("def greet():\n    return 'unstaged'\n", encoding="utf-8")
    res_unstaged = runner.invoke(cli, ["commit", "--yes"])
    assert "No staged changes" in res_unstaged.output

    # Stage & auto-commit
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    res_commit = runner.invoke(cli, ["commit", "--provider", "gemini", "--yes"])
    assert res_commit.exit_code == 0
    assert "Successfully committed" in res_commit.output
    log_out = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo, capture_output=True, text=True, check=True)
    assert log_out.stdout.strip() == "feat(auth): enforce JWT middleware verification"
