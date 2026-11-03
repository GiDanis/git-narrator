"""git-narrator: Understand any git diff in 5 seconds.

AI-powered narrative walkthrough and risk radar for human and agentic code.
Core diff inspection, sanitization, lockfile delta compaction, and
knapsack token budgeting modules.
"""

from git_narrator.git_engine import (
    ChangeScope,
    ChangeScopeType,
    CommitInfo,
    FileNumStat,
    GitCommandError,
    GitEngine,
    GitError,
    detect_change_scope,
    get_commit_context,
    get_current_branch,
    get_diff,
    get_numstat,
    get_repo_root,
    get_stat,
    is_git_repo,
    run_git,
)
from git_narrator.knapsack import (
    DiffFile,
    DiffHunk,
    KnapsackBudgetOptimizer,
    KnapsackResult,
    classify_file_weight,
    compress_hunk_context,
    estimate_tokens,
    has_interface_signature,
    optimize_diff_tokens,
    parse_diff_files,
    score_hunk,
)
from git_narrator.lockfile import (
    DependencyChange,
    compact_lockfile_diff,
    format_lockfile_summary,
    is_lockfile,
    process_diff_lockfiles,
    strip_lockfiles_and_inject_summary,
)
from git_narrator.sanitizer import (
    PrunedFileInfo,
    PruneReason,
    SanitizedDiffResult,
    is_binary_path,
    is_generated_content,
    is_ignored_path,
    is_minified_path,
    load_narratorignore,
    parse_gitattributes,
    sanitize_diff,
)

__version__ = "0.1.0"
__author__ = "git-narrator contributors"

__all__ = [
    # git_engine
    "ChangeScope",
    "ChangeScopeType",
    "CommitInfo",
    "FileNumStat",
    "GitCommandError",
    "GitEngine",
    "GitError",
    "detect_change_scope",
    "get_commit_context",
    "get_current_branch",
    "get_diff",
    "get_numstat",
    "get_repo_root",
    "get_stat",
    "is_git_repo",
    "run_git",
    # sanitizer
    "PruneReason",
    "PrunedFileInfo",
    "SanitizedDiffResult",
    "is_binary_path",
    "is_generated_content",
    "is_ignored_path",
    "is_minified_path",
    "load_narratorignore",
    "parse_gitattributes",
    "sanitize_diff",
    # lockfile
    "DependencyChange",
    "compact_lockfile_diff",
    "format_lockfile_summary",
    "is_lockfile",
    "process_diff_lockfiles",
    "strip_lockfiles_and_inject_summary",
    # knapsack
    "DiffFile",
    "DiffHunk",
    "KnapsackBudgetOptimizer",
    "KnapsackResult",
    "classify_file_weight",
    "compress_hunk_context",
    "estimate_tokens",
    "has_interface_signature",
    "optimize_diff_tokens",
    "parse_diff_files",
    "score_hunk",
]
