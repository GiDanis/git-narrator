"""Unit tests for git_narrator Rich TUI rendering and GitHub Actions helpers."""

import io
import json
from pathlib import Path

from rich.console import Console

from git_narrator.parser import parse_and_validate_report
from git_narrator.ui import (
    REPO_URL,
    emit_github_annotations,
    generate_pr_markdown,
    get_impact_badge,
    get_severity_badge,
    render_commit_tab,
    render_diagram_tab,
    render_footer,
    render_header,
    render_risk_tab,
    render_story_tab,
    write_github_step_summary,
)


def _render_to_str(renderable) -> str:
    buf = io.StringIO()
    c = Console(file=buf, width=120, force_terminal=False, no_color=True)
    c.print(renderable)
    return buf.getvalue()


def _make_report(with_flow: bool = True, with_risks: bool = True):
    data = {
        "executive_summary": {
            "headline": "Switch session auth to RS256 JWT",
            "intent": "Eliminate Redis session contention.",
            "overall_impact": "Reduces API tail latency by 12ms.",
            "blast_radius": "HIGH",
            "tags": ["auth", "jwt"],
        },
        "architecture_narrative": {
            "before_state": "Redis cookie store",
            "after_state": "Stateless RS256 verification",
            "tech_debt": "Key rotation interval currently hardcoded.",
            "components_affected": [
                {"component_name": "AuthMiddleware", "mutation_type": "MODIFIED", "summary": "Verify bearer JWT"}
            ],
        },
        "risk_radar": (
            [
                {
                    "category": "SECURITY_LEAK",
                    "severity": "CRITICAL",
                    "title": "Fallback accepts unsigned token",
                    "file_path": None,
                    "line_hint": None,
                    "explanation": "alg=none not rejected explicitly.",
                    "remediation": "Restrict algorithms=['RS256'].",
                },
                {
                    "category": "TEST_GAP",
                    "severity": "MEDIUM",
                    "title": "Missing clock skew test",
                    "file_path": "auth.py",
                    "line_hint": "L42",
                    "explanation": "Leeway edge case untested.",
                    "remediation": "Add skew test.",
                },
            ]
            if with_risks
            else []
        ),
        "visual_flow": (
            {
                "diagram_type": "flowchart",
                "mermaid_code": 'flowchart LR\nA["Client"] --> B["API"]',
                "ascii_diagram": "[Client] --> [API]",
            }
            if with_flow
            else None
        ),
        "review_checklist": {
            "manual_checks": ["Check JWKS cache TTL in staging"],
            "breaking_changes": ["Cookie auth disabled"],
        },
        "conventional_commit": "feat(auth): replace Redis sessions with RS256 JWT",
    }
    return parse_and_validate_report(json.dumps(data))


def test_severity_and_impact_badges():
    report = _make_report()
    assert "HIGH" in get_impact_badge(report.executive_summary).plain
    assert "CRITICAL" in get_severity_badge(report.risk_radar[0].severity).plain
    assert "MEDIUM" in get_severity_badge(report.risk_radar[1].severity).plain


def test_render_all_tabs_with_flow_and_risks():
    report = _make_report(with_flow=True, with_risks=True)

    header = _render_to_str(render_header("main", "2 files changed", "gemini/gemini-2.5-flash"))
    assert "GIT NARRATOR" in header
    assert "main" in header

    story = _render_to_str(render_story_tab(report))
    assert "Switch session auth to RS256 JWT" in story
    assert "Key rotation interval currently hardcoded." in story
    assert "HIGH" in story

    risks = _render_to_str(render_risk_tab(report))
    assert "CRITICAL" in risks
    assert "SECURITY_LEAK" in risks
    assert "repository-wide" in risks
    assert "None" not in risks

    diagram = _render_to_str(render_diagram_tab(report))
    assert "[Client] --> [API]" in diagram
    assert "Cookie auth disabled" in diagram

    commit_tab = _render_to_str(render_commit_tab(report))
    assert "feat(auth): replace Redis sessions with RS256 JWT" in commit_tab

    footer = _render_to_str(render_footer(1, 2, toast="✓ Copied!"))
    assert "Copied!" in footer


def test_render_tabs_and_markdown_when_visual_flow_is_none():
    report = _make_report(with_flow=False, with_risks=False)

    story = _render_to_str(render_story_tab(report))
    assert "Switch session auth to RS256 JWT" in story

    risks = _render_to_str(render_risk_tab(report))
    assert "All Clear" in risks

    diagram = _render_to_str(render_diagram_tab(report))
    assert "No visual flow diagram generated" in diagram

    commit_tab = _render_to_str(render_commit_tab(report))
    assert "feat(auth): replace Redis sessions with RS256 JWT" in commit_tab

    md = generate_pr_markdown(report)
    assert REPO_URL in md
    assert "Cookie auth disabled" in md
    assert "```mermaid" not in md


def test_github_annotations_and_summary(tmp_path: Path, monkeypatch):
    report = _make_report(with_flow=True, with_risks=True)
    buf = io.StringIO()
    printer = Console(file=buf, width=200, no_color=True)
    emit_github_annotations(report, out_console=printer)
    ann = buf.getvalue()
    assert "::error " in ann
    assert "::warning file=auth.py" in ann

    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    assert write_github_step_summary(report) is True
    assert "```mermaid" in summary_path.read_text(encoding="utf-8")
