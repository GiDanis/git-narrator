"""Unit tests for git_narrator 5-tier fallback parser and auto-repair engine."""

import json

from git_narrator.parser import (
    extract_balanced_braces,
    extract_code_fences,
    extract_conventional_commit,
    parse_and_validate_report,
    parse_narrator_json,
    repair_truncated_json,
)
from git_narrator.schemas import (
    GitNarratorReport,
    RiskCategory,
    RiskSeverity,
)

SAMPLE_VALID_REPORT = {
    "executive_summary": {
        "headline": "Introduce JWT-based auth layer",
        "intent": "Replace insecure session cookies with stateless JWT bearer tokens.",
        "overall_impact": "High positive impact on API horizontal scalability; minor auth latency reduction.",
        "tags": ["security", "auth", "jwt"],
    },
    "architecture_narrative": {
        "before_state": "Monolithic session table in Postgres checked on every request.",
        "after_state": "Decentralized JWT verification using RS256 public keys cached in memory.",
        "tech_debt": "Key rotation endpoint is mocked and needs KMS integration in next sprint.",
        "components_affected": [
            {
                "component_name": "AuthMiddleware",
                "mutation_type": "MODIFIED",
                "summary": "Switched bearer token extractor to verify RS256 signature.",
            }
        ],
    },
    "risk_radar": [
        {
            "category": "CONTRACT_BREAK",
            "severity": "HIGH",
            "title": "Old session cookie no longer accepted",
            "file_path": "src/auth/middleware.py",
            "line_hint": "L45-L60",
            "explanation": "Clients sending 'Set-Cookie: session_id' will receive 401 Unauthorized.",
            "remediation": "Add backwards-compatibility fallback during 30-day grace period.",
        },
        {
            "category": "TEST_GAP",
            "severity": "CRITICAL",
            "title": "Expired token branch missing automated assertion",
            "file_path": "tests/test_auth.py",
            "line_hint": "L110",
            "explanation": "No test currently asserts behavior when jwt.ExpiredSignatureError is raised.",
            "remediation": "Add test_expired_jwt_returns_401_with_token_expired_code.",
        },
    ],
    "visual_flow": {
        "diagram_type": "flowchart",
        "mermaid_code": 'graph TD\nA["Client Request"] --> B["AuthMiddleware"]\nB --> C["Verify RS256"]\nC --> D["Route Handler"]',
        "ascii_diagram": "[Client] --> [AuthMiddleware] --> [Verify RS256] --> [Handler]",
    },
    "review_checklist": {
        "manual_checks": [
            "Verify RS256 public key environment variable is populated in staging.",
        ],
        "breaking_changes": [
            "HTTP 401 response body schema updated to { error: string, code: string }.",
        ],
    },
    "conventional_commit": "feat(auth): implement stateless RS256 JWT validation",
}


def test_tier_1_direct_json():
    """Test Tier 1: Direct JSON parsing."""
    raw = json.dumps(SAMPLE_VALID_REPORT)
    data, tier = parse_narrator_json(raw)
    assert tier == 1
    assert data["executive_summary"]["headline"] == "Introduce JWT-based auth layer"

    report = parse_and_validate_report(raw)
    assert isinstance(report, GitNarratorReport)
    assert report.conventional_commit == "feat(auth): implement stateless RS256 JWT validation"
    assert len(report.risk_radar) == 2
    assert report.risk_radar[0].category == RiskCategory.CONTRACT_BREAK
    assert report.risk_radar[0].severity == RiskSeverity.HIGH


def test_tier_2_code_fences():
    """Test Tier 2: Stripping markdown code fences (```json ... ```)."""
    raw_json = json.dumps(SAMPLE_VALID_REPORT)
    markdown_wrapped = f"""
Here is the architectural review you requested:

```json
{raw_json}
```

Let me know if you need more details!
"""
    fences = extract_code_fences(markdown_wrapped)
    assert len(fences) == 1

    data, tier = parse_narrator_json(markdown_wrapped)
    assert tier == 2
    assert data["executive_summary"]["headline"] == "Introduce JWT-based auth layer"

    report = parse_and_validate_report(markdown_wrapped)
    assert isinstance(report, GitNarratorReport)
    assert report.executive_summary.headline == "Introduce JWT-based auth layer"


def test_tier_3_balanced_braces():
    """Test Tier 3: Balanced brace extraction without code fences."""
    raw_json = json.dumps(SAMPLE_VALID_REPORT)
    surrounded = f"Architectural Report Summary:\n{raw_json}\nEnd of analysis."

    candidate = extract_balanced_braces(surrounded)
    assert candidate is not None
    assert candidate.startswith("{")
    assert candidate.endswith("}")

    data, tier = parse_narrator_json(surrounded)
    assert tier == 3
    assert data["conventional_commit"] == "feat(auth): implement stateless RS256 JWT validation"

    report = parse_and_validate_report(surrounded)
    assert report.executive_summary.intent.startswith("Replace insecure")


def test_tier_4_truncated_json_string_repair():
    """Test Tier 4: Repairing JSON truncated mid-string."""
    truncated = '{"executive_summary": {"headline": "Add new authentication gateway'
    repaired = repair_truncated_json(truncated)
    parsed = json.loads(repaired)
    assert parsed["executive_summary"]["headline"] == "Add new authentication gateway"

    data, tier = parse_narrator_json(truncated)
    assert tier == 4

    report = parse_and_validate_report(truncated)
    assert isinstance(report, GitNarratorReport)
    assert report.executive_summary.headline == "Add new authentication gateway"


def test_tier_4_truncated_array_with_dangling_comma():
    """Test Tier 4: Repairing JSON truncated inside array with trailing comma."""
    truncated = '{"executive_summary": {"headline": "Auth", "intent": "Secure", "tags": ["auth", "security", '
    repaired = repair_truncated_json(truncated)
    parsed = json.loads(repaired)
    assert parsed["executive_summary"]["tags"] == ["auth", "security"]

    report = parse_and_validate_report(truncated)
    assert isinstance(report, GitNarratorReport)
    assert report.executive_summary.tags == ["auth", "security"]


def test_tier_4_truncated_dangling_key_and_colon():
    """Test Tier 4: Repairing JSON ending with dangling key or colon."""
    truncated_key = '{"executive_summary": {"headline": "Auth", "intent"'
    repaired_key = repair_truncated_json(truncated_key)
    parsed_key = json.loads(repaired_key)
    assert "intent" in parsed_key["executive_summary"]

    truncated_colon = '{"executive_summary": {"headline": "Auth", "intent": '
    repaired_colon = repair_truncated_json(truncated_colon)
    parsed_colon = json.loads(repaired_colon)
    assert parsed_colon["executive_summary"]["intent"] is None or parsed_colon["executive_summary"]["intent"] == ""


def test_tier_5_unstructured_fallback():
    """Test Tier 5: Fallback gracefully to structured report from completely unstructured text."""
    raw_text = """
feat(database): migrate connection pool to asyncpg

We changed the database driver from psycopg2 to asyncpg.
This improves throughput by 40% under concurrent loads.
Ensure pg_stat_activity is monitored post deploy.
"""
    data, tier = parse_narrator_json(raw_text)
    assert tier == 5

    report = parse_and_validate_report(raw_text)
    assert isinstance(report, GitNarratorReport)
    assert report.conventional_commit == "feat(database): migrate connection pool to asyncpg"
    assert "feat(database)" in report.executive_summary.headline
    assert len(report.review_checklist.manual_checks) > 0


def test_tier_5_empty_input():
    """Test Tier 5: Handling empty text without crashing."""
    report = parse_and_validate_report("")
    assert isinstance(report, GitNarratorReport)
    assert report.conventional_commit.startswith("chore:")


def test_extract_conventional_commit_variants():
    """Test regex extraction of conventional commit patterns."""
    assert extract_conventional_commit("fix(ui): resolve button alignment") == "fix(ui): resolve button alignment"
    assert extract_conventional_commit("Some text\nrefactor: streamline handler pipeline\nother text") == "refactor: streamline handler pipeline"
    assert extract_conventional_commit("No commit here") == "chore: update repository changes"


def test_coercion_on_partial_dict():
    """Test that a partial dictionary missing fields is coerced and validates."""
    partial = {
        "executive_summary": {
            "headline": "Partial diff summary",
        }
    }
    raw = json.dumps(partial)
    report = parse_and_validate_report(raw)
    assert isinstance(report, GitNarratorReport)
    assert report.executive_summary.headline == "Partial diff summary"
    assert report.architecture_narrative.before_state != ""
