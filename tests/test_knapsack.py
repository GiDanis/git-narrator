"""Tests for knapsack module: semantic priority scoring and token budget allocation."""

import math
import pytest

from git_narrator.knapsack import (
    DiffFile,
    DiffHunk,
    KnapsackBudgetOptimizer,
    classify_file_weight,
    compress_hunk_context,
    estimate_tokens,
    has_interface_signature,
    optimize_diff_tokens,
    parse_diff_files,
    score_hunk,
)


def test_classify_file_weight():
    # Core logic / domain / auth / db / api
    assert classify_file_weight("src/auth/service.py") == 1.0
    assert classify_file_weight("app/models/user.py") == 1.0
    assert classify_file_weight("lib/database/connection.rs") == 1.0
    assert classify_file_weight("core/engine.go") == 1.0

    # Infra / config
    assert classify_file_weight("Dockerfile") == 0.85
    assert classify_file_weight("docker-compose.yml") == 0.85
    assert classify_file_weight("pyproject.toml") == 0.85
    assert classify_file_weight("k8s/deployment.yaml") == 0.85
    assert classify_file_weight(".github/workflows/ci.yml") == 0.85
    assert classify_file_weight("src/config.py") == 0.85

    # Tests
    assert classify_file_weight("tests/test_engine.py") == 0.50
    assert classify_file_weight("test/unit_test.py") == 0.50
    assert classify_file_weight("src/__tests__/app.test.tsx") == 0.50
    assert classify_file_weight("pkg/auth_test.go") == 0.50

    # Styling
    assert classify_file_weight("styles/globals.css") == 0.25
    assert classify_file_weight("src/theme.scss") == 0.25

    # Docs
    assert classify_file_weight("README.md") == 0.20
    assert classify_file_weight("docs/architecture.rst") == 0.20
    assert classify_file_weight("LICENSE") == 0.20


def test_has_interface_signature():
    assert has_interface_signature("@@ -10,6 +10,12 @@ def calculate_total(a, b):") is True
    assert has_interface_signature("@@ -50,4 +50,8 @@ async def fetch_user():") is True
    assert has_interface_signature("@@ -100,5 +100,10 @@ class AuthenticationManager:") is True
    assert has_interface_signature("@@ -5,3 +5,6 @@ export function useAuth() {") is True
    assert has_interface_signature("@@ -20,2 +20,4 @@ @router.post('/login')") is True
    assert has_interface_signature("@@ -30,4 +30,8 @@ pub fn process_event() {") is True

    # No signature (just plain loop or variable or empty context)
    assert has_interface_signature("@@ -10,5 +10,6 @@ for item in items:") is False
    assert has_interface_signature("@@ -1,5 +1,5 @@") is False


def test_score_hunk_formula():
    # S = W_type * (1 + ln(1 + additions + deletions)) * C_interface
    w_type = 1.0
    additions = 10
    deletions = 5
    delta = additions + deletions  # 15

    # Without interface signature: C_interface = 1.0
    expected_score = 1.0 * (1.0 + math.log1p(15)) * 1.0
    calculated = score_hunk(additions, deletions, w_type, has_signature=False)
    assert math.isclose(calculated, expected_score, rel_tol=1e-5)

    # With interface signature: C_interface = 1.5
    expected_signature_score = 1.0 * (1.0 + math.log1p(15)) * 1.5
    calc_sig = score_hunk(additions, deletions, w_type, has_signature=True)
    assert math.isclose(calc_sig, expected_signature_score, rel_tol=1e-5)

    # Weight scaling: Infra w_type = 0.85
    expected_infra = 0.85 * (1.0 + math.log1p(15)) * 1.0
    calc_infra = score_hunk(additions, deletions, 0.85, has_signature=False)
    assert math.isclose(calc_infra, expected_infra, rel_tol=1e-5)


def test_token_estimator():
    sample_text = "def hello():\n    return 'world'\n"
    tokens = estimate_tokens(sample_text)
    assert tokens > 0
    assert tokens == math.ceil(len(sample_text) / 3.7)


def test_compress_hunk_context():
    # Hunk with 3 lines of context before and 3 lines after
    lines = [
        " ctx1",
        " ctx2",
        " ctx3",
        "-old_line",
        "+new_line",
        " ctx4",
        " ctx5",
        " ctx6",
    ]
    hunk = DiffHunk(
        file_path="app.py",
        header="@@ -10,7 +10,7 @@ def foo():",
        lines=lines,
        additions=1,
        deletions=1,
        w_type=1.0,
        has_interface=True,
        score=2.5,
    )

    compressed = compress_hunk_context(hunk)
    assert compressed.is_compressed is True
    # Should only keep 1 context line before (' ctx3') and 1 context line after (' ctx4')
    assert compressed.lines == [
        " ctx3",
        "-old_line",
        "+new_line",
        " ctx4",
    ]
    assert compressed.token_count < hunk.token_count


def test_knapsack_budget_allocation_under_budget():
    diff_text = """diff --git a/src/core.py b/src/core.py
--- a/src/core.py
+++ b/src/core.py
@@ -1,3 +1,4 @@ def run():
 ctx
-old
+new
+extra
"""
    result = optimize_diff_tokens(diff_text, token_budget=10000)
    assert result.included_hunks == 1
    assert result.omitted_hunks == 0
    assert result.optimized_diff == diff_text


def test_knapsack_budget_priority_and_truncation():
    # Create diff with high-priority core logic and low-priority styling
    # Set tight budget so knapsack has to omit low-priority hunk
    diff_core = """diff --git a/src/auth.py b/src/auth.py
--- a/src/auth.py
+++ b/src/auth.py
@@ -10,5 +10,15 @@ def authenticate_user():
""" + "\n".join([f"+auth_logic_{i} = True" for i in range(25)]) + "\n"

    diff_style = """diff --git a/styles/theme.css b/styles/theme.css
--- a/styles/theme.css
+++ b/styles/theme.css
@@ -1,5 +1,50 @@
""" + "\n".join([f"+.button_{i} {{ color: red; }}" for i in range(50)]) + "\n"

    full_diff = diff_core + diff_style

    # Token budget only enough for auth.py
    tokens_auth = estimate_tokens(diff_core)
    budget = tokens_auth + 40

    result = optimize_diff_tokens(full_diff, token_budget=budget)

    # Core auth should be included
    assert "src/auth.py" in result.optimized_diff
    assert "def authenticate_user():" in result.optimized_diff

    # Styling file should be truncated with clean omission marker
    assert "styles/theme.css" in result.optimized_diff
    assert "omitted in styles/theme.css - minor changes" in result.optimized_diff
    assert result.omitted_hunks >= 1
