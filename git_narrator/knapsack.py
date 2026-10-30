"""Knapsack token optimizer: semantic priority scoring and greedy knapsack budgeting for diffs."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import re
from typing import Optional, Sequence

from git_narrator.sanitizer import split_diff_into_file_chunks

# Regex matching hunk headers: @@ -10,5 +10,8 @@ optional context signature
HUNK_HEADER_REGEX = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:\s*(.*))?$"
)

# Signature markers inside hunk headers that indicate code interfaces
INTERFACE_SIGNATURE_MARKERS = [
    r"\bdef\s+",
    r"\basync\s+def\s+",
    r"\bclass\s+",
    r"\bfunction\b",
    r"\bexport\s+",
    r"\binterface\s+",
    r"\btype\s+",
    r"\bpub\s+fn\s+",
    r"\bstruct\s+",
    r"\benum\s+",
    r"\bimpl\b",
    r"\btrait\b",
    r"\bfunc\s+",
    r"@(?:app|router|bp|blueprint)\.",
    r"\brouter\.",
    r"\bpublic\s+",
    r"\bprivate\s+",
    r"\bprotected\s+",
]
INTERFACE_SIGNATURE_COMPILED = re.compile(
    "|".join(INTERFACE_SIGNATURE_MARKERS), re.IGNORECASE
)


def estimate_tokens(text: str) -> int:
    """Estimate token count for LLMs (gemini/gpt/claude average ~3.7 chars/token).

    Args:
        text: String content.

    Returns:
        Estimated token integer.
    """
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 3.7))


def classify_file_weight(path: str | Path) -> float:
    """Classify the semantic importance weight $W_{type}$ of a file path.

    Weights:
    - Core logic / domain / auth / db: 1.00
    - Infra / config / build specs: 0.85
    - Tests: 0.50
    - Styling: 0.25
    - Docs & non-code text: 0.20

    Args:
        path: Path or filename.

    Returns:
        Weight float between 0.15 and 1.0.
    """
    norm = str(path).replace("\\", "/").lower()
    filename = Path(norm).name

    # 1. Docs (0.20)
    doc_extensions = {".md", ".rst", ".txt", ".adoc"}
    if Path(norm).suffix in doc_extensions or "docs/" in norm or filename in ("license", "changelog", "authors"):
        return 0.20

    # 2. Styling (0.25)
    style_extensions = {".css", ".scss", ".sass", ".less", ".styl"}
    if Path(norm).suffix in style_extensions or "styles/" in norm or "theme/" in norm:
        return 0.25

    # 3. Tests (0.50)
    if (
        "test_" in filename
        or "_test." in filename
        or ".test." in filename
        or ".spec." in filename
        or "/tests/" in norm
        or norm.startswith("tests/")
        or "/test/" in norm
        or norm.startswith("test/")
        or "/spec/" in norm
        or "__tests__" in norm
    ):
        return 0.50

    # 4. Infra & Config (0.85)
    infra_names = {
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
        "makefile",
        "pyproject.toml",
        "cargo.toml",
        "package.json",
        "tsconfig.json",
        "settings.py",
        "config.py",
        ".env.example",
        "nginx.conf",
    }
    if (
        filename in infra_names
        or "k8s/" in norm
        or "kubernetes/" in norm
        or "terraform/" in norm
        or "helm/" in norm
        or "infra/" in norm
        or "ci/" in norm
        or ".github/" in norm
        or ".gitlab/" in norm
    ):
        return 0.85

    # 5. Core logic / domain / auth / db / api default (1.00)
    return 1.00


def has_interface_signature(hunk_header_line: str) -> bool:
    """Check if hunk header contains function, class, route, or export signatures.

    Args:
        hunk_header_line: The raw @@ ... @@ header line.

    Returns:
        True if interface signature detected, False otherwise.
    """
    match = HUNK_HEADER_REGEX.match(hunk_header_line.strip())
    if not match:
        return False
    context_text = match.group(5)
    if not context_text:
        return False
    return bool(INTERFACE_SIGNATURE_COMPILED.search(context_text))


def score_hunk(
    additions: int,
    deletions: int,
    w_type: float,
    has_signature: bool = False,
) -> float:
    r"""Compute semantic priority score for a hunk or file.

    Formula:
    $$S = W_{type} \times (1 + \ln(1 + additions + deletions)) \times C_{interface}$$

    Args:
        additions: Number of lines added.
        deletions: Number of lines deleted.
        w_type: File category weight ($W_{type}$).
        has_signature: Whether hunk header includes class/function/route signatures.

    Returns:
        Calculated semantic score.
    """
    c_interface = 1.5 if has_signature else 1.0
    delta = additions + deletions
    # math.log1p(x) calculates ln(1 + x) accurately
    score = w_type * (1.0 + math.log1p(delta)) * c_interface
    return score


@dataclass
class DiffHunk:
    """Represents an individual diff hunk with scoring and token economics."""

    file_path: str
    header: str
    lines: list[str]
    additions: int
    deletions: int
    w_type: float
    has_interface: bool
    score: float
    is_compressed: bool = False
    is_included: bool = True

    @property
    def raw_text(self) -> str:
        """Complete raw hunk text."""
        return self.header + "\n" + "\n".join(self.lines) + "\n"

    @property
    def token_count(self) -> int:
        """Estimated tokens for this hunk."""
        return estimate_tokens(self.raw_text)

    @property
    def density(self) -> float:
        """Value density: Score per Token."""
        tokens = self.token_count
        if tokens == 0:
            return 0.0
        return self.score / tokens


@dataclass
class DiffFile:
    """Represents a file's diff containing header metadata and parsed hunks."""

    path: str
    headers: list[str]
    hunks: list[DiffHunk]
    w_type: float

    @property
    def header_text(self) -> str:
        if not self.headers:
            return f"diff --git a/{self.path} b/{self.path}\n--- a/{self.path}\n+++ b/{self.path}\n"
        return "\n".join(self.headers) + "\n"

    @property
    def header_tokens(self) -> int:
        return estimate_tokens(self.header_text)

    @property
    def total_score(self) -> float:
        return sum(h.score for h in self.hunks)


def compress_hunk_context(hunk: DiffHunk) -> DiffHunk:
    """Adaptive context reduction: reduce context lines from -U3 to -U1.

    Leaves at most 1 line of context before the first edit line and after the last
    edit line, drastically reducing tokens while maintaining human and LLM readability.

    Args:
        hunk: Original DiffHunk.

    Returns:
        A new compressed DiffHunk with reduced context lines.
    """
    if hunk.is_compressed or not hunk.lines:
        return hunk

    lines = hunk.lines
    # Find first and last change lines
    first_edit_idx: Optional[int] = None
    last_edit_idx: Optional[int] = None

    for idx, line in enumerate(lines):
        if line.startswith(("+", "-")):
            if first_edit_idx is None:
                first_edit_idx = idx
            last_edit_idx = idx

    if first_edit_idx is None or last_edit_idx is None:
        # No actual edits found in hunk lines
        return hunk

    # Keep at most 1 context line before first edit
    start_idx = max(0, first_edit_idx - 1)
    # Keep at most 1 context line after last edit
    end_idx = min(len(lines), last_edit_idx + 2)

    trimmed_lines = lines[start_idx:end_idx]

    # Recompute header if possible
    # We can preserve the original header or update counts
    old_count = sum(1 for line in trimmed_lines if not line.startswith("+"))
    new_count = sum(1 for line in trimmed_lines if not line.startswith("-"))

    match = HUNK_HEADER_REGEX.match(hunk.header)
    if match:
        old_start_str, _, new_start_str, _, ctx = match.groups()
        ctx_suffix = f" {ctx}" if ctx else ""
        new_header = f"@@ -{old_start_str},{old_count} +{new_start_str},{new_count} @@{ctx_suffix}"
    else:
        new_header = hunk.header

    compressed = DiffHunk(
        file_path=hunk.file_path,
        header=new_header,
        lines=trimmed_lines,
        additions=hunk.additions,
        deletions=hunk.deletions,
        w_type=hunk.w_type,
        has_interface=hunk.has_interface,
        score=hunk.score,
        is_compressed=True,
        is_included=hunk.is_included,
    )
    return compressed


def parse_diff_files(diff_text: str) -> list[DiffFile]:
    """Parse raw git diff string into structured DiffFile and DiffHunk instances.

    Args:
        diff_text: Raw unified diff string.

    Returns:
        List of DiffFile instances.
    """
    chunks = split_diff_into_file_chunks(diff_text)
    files: list[DiffFile] = []

    for chunk in chunks:
        fpath = chunk.file_path
        w_type = classify_file_weight(fpath)

        lines = chunk.raw_chunk.splitlines()
        headers: list[str] = []
        hunks: list[DiffHunk] = []

        current_hunk_header: Optional[str] = None
        current_hunk_lines: list[str] = []

        def finish_hunk():
            nonlocal current_hunk_header, current_hunk_lines
            if current_hunk_header is not None:
                additions = sum(1 for l in current_hunk_lines if l.startswith("+"))
                deletions = sum(1 for l in current_hunk_lines if l.startswith("-"))
                has_sig = has_interface_signature(current_hunk_header)
                s = score_hunk(additions, deletions, w_type, has_sig)
                hunks.append(
                    DiffHunk(
                        file_path=fpath,
                        header=current_hunk_header,
                        lines=current_hunk_lines,
                        additions=additions,
                        deletions=deletions,
                        w_type=w_type,
                        has_interface=has_sig,
                        score=s,
                    )
                )
            current_hunk_header = None
            current_hunk_lines = []

        for line in lines:
            if line.startswith("@@"):
                finish_hunk()
                current_hunk_header = line
            elif current_hunk_header is None:
                headers.append(line)
            else:
                current_hunk_lines.append(line)

        finish_hunk()

        files.append(
            DiffFile(
                path=fpath,
                headers=headers,
                hunks=hunks,
                w_type=w_type,
            )
        )

    return files


@dataclass
class KnapsackResult:
    """Summary and payload of knapsack token budget optimization."""

    optimized_diff: str
    total_tokens: int
    token_budget: int
    total_hunks: int
    included_hunks: int
    omitted_hunks: int
    compressed_hunks: int
    omitted_files: list[str] = field(default_factory=list)


class KnapsackBudgetOptimizer:
    """Greedy knapsack budget allocator with adaptive context reduction."""

    def __init__(self, token_budget: int = 16000):
        self.token_budget = token_budget

    def optimize(self, diff_text: str) -> KnapsackResult:
        r"""Fit highest value-density hunks into token budget.

        Steps:
        1. Parse diff into files and hunks.
        2. Reserve token budget for required file headers.
        3. Score each hunk using $S = W_{type} \times (1 + \ln(1 + \Delta)) \times C_{interface}$.
        4. Sort hunks by value density ($Score / Tokens$) descending.
        5. Greedily pack hunks into budget.
           If a hunk exceeds remaining budget, attempt adaptive context compression (-U1).
        6. Format final diff with clean truncation markers where hunks were omitted.

        Args:
            diff_text: Sanitized git diff.

        Returns:
            KnapsackResult containing optimized diff and token analytics.
        """
        if not diff_text or not diff_text.strip():
            return KnapsackResult(
                optimized_diff="",
                total_tokens=0,
                token_budget=self.token_budget,
                total_hunks=0,
                included_hunks=0,
                omitted_hunks=0,
                compressed_hunks=0,
            )

        files = parse_diff_files(diff_text)
        all_hunks: list[DiffHunk] = []
        for f in files:
            all_hunks.extend(f.hunks)

        total_hunks_count = len(all_hunks)
        if total_hunks_count == 0:
            return KnapsackResult(
                optimized_diff=diff_text,
                total_tokens=estimate_tokens(diff_text),
                token_budget=self.token_budget,
                total_hunks=0,
                included_hunks=0,
                omitted_hunks=0,
                compressed_hunks=0,
            )

        # Estimate uncompressed full size
        raw_tokens = estimate_tokens(diff_text)
        if raw_tokens <= self.token_budget:
            # Everything fits comfortably within budget!
            return KnapsackResult(
                optimized_diff=diff_text,
                total_tokens=raw_tokens,
                token_budget=self.token_budget,
                total_hunks=total_hunks_count,
                included_hunks=total_hunks_count,
                omitted_hunks=0,
                compressed_hunks=0,
            )

        # Reserve minimal tokens for headers (~150 tokens)
        reserved_overhead = 150
        effective_budget = max(200, self.token_budget - reserved_overhead)

        # Sort hunks by value density descending
        # Ties broken by higher raw score, then additions
        sorted_hunks = sorted(
            all_hunks,
            key=lambda h: (h.density, h.score, h.additions),
            reverse=True,
        )

        selected_hunks: set[int] = set()
        compressed_map: dict[int, DiffHunk] = {}
        used_tokens = 0
        compressed_count = 0

        for hunk in sorted_hunks:
            h_id = id(hunk)
            h_tokens = hunk.token_count

            if used_tokens + h_tokens <= effective_budget:
                selected_hunks.add(h_id)
                used_tokens += h_tokens
            else:
                # Try adaptive compression (-U1)
                comp = compress_hunk_context(hunk)
                comp_tokens = comp.token_count
                if used_tokens + comp_tokens <= effective_budget:
                    selected_hunks.add(h_id)
                    compressed_map[h_id] = comp
                    used_tokens += comp_tokens
                    compressed_count += 1

        # Reconstruct output diff
        output_chunks: list[str] = []
        included_count = 0
        omitted_count = 0
        omitted_files: list[str] = []

        for f in files:
            f_included_hunks: list[str] = []
            f_omitted_count = 0

            for hunk in f.hunks:
                h_id = id(hunk)
                if h_id in selected_hunks:
                    actual_hunk = compressed_map.get(h_id, hunk)
                    f_included_hunks.append(actual_hunk.raw_text)
                    included_count += 1
                else:
                    f_omitted_count += 1
                    omitted_count += 1

            if f_included_hunks:
                # Add file header
                output_chunks.append(f.header_text)
                output_chunks.extend(f_included_hunks)
                if f_omitted_count > 0:
                    marker = f"[... {f_omitted_count} hunk(s) omitted in {f.path} - minor changes ...]\n"
                    output_chunks.append(marker)
            elif f_omitted_count > 0:
                # All hunks omitted for this file
                omitted_files.append(f.path)
                output_chunks.append(f.header_text)
                marker = f"[... All {f_omitted_count} hunk(s) omitted in {f.path} - minor changes ...]\n"
                output_chunks.append(marker)

        optimized_diff = "".join(output_chunks)
        final_tokens = estimate_tokens(optimized_diff)

        return KnapsackResult(
            optimized_diff=optimized_diff,
            total_tokens=final_tokens,
            token_budget=self.token_budget,
            total_hunks=total_hunks_count,
            included_hunks=included_count,
            omitted_hunks=omitted_count,
            compressed_hunks=compressed_count,
            omitted_files=omitted_files,
        )


def optimize_diff_tokens(diff_text: str, token_budget: int = 16000) -> KnapsackResult:
    """Convenience function: apply greedy knapsack token budgeting to a diff."""
    optimizer = KnapsackBudgetOptimizer(token_budget=token_budget)
    return optimizer.optimize(diff_text)
