"""git-narrator: Understand any git diff in 5 seconds.

AI-powered narrative walkthrough and risk radar for human and agentic code.
Uses PEP 562 lazy attribute loading so CLI cold start remains ultra-fast.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

__version__ = "0.2.0"
__author__ = "git-narrator contributors"

if TYPE_CHECKING:
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

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # git_engine
    "ChangeScope": ("git_narrator.git_engine", "ChangeScope"),
    "ChangeScopeType": ("git_narrator.git_engine", "ChangeScopeType"),
    "CommitInfo": ("git_narrator.git_engine", "CommitInfo"),
    "FileNumStat": ("git_narrator.git_engine", "FileNumStat"),
    "GitCommandError": ("git_narrator.git_engine", "GitCommandError"),
    "GitEngine": ("git_narrator.git_engine", "GitEngine"),
    "GitError": ("git_narrator.git_engine", "GitError"),
    "detect_change_scope": ("git_narrator.git_engine", "detect_change_scope"),
    "get_commit_context": ("git_narrator.git_engine", "get_commit_context"),
    "get_current_branch": ("git_narrator.git_engine", "get_current_branch"),
    "get_diff": ("git_narrator.git_engine", "get_diff"),
    "get_numstat": ("git_narrator.git_engine", "get_numstat"),
    "get_repo_root": ("git_narrator.git_engine", "get_repo_root"),
    "get_stat": ("git_narrator.git_engine", "get_stat"),
    "is_git_repo": ("git_narrator.git_engine", "is_git_repo"),
    "run_git": ("git_narrator.git_engine", "run_git"),
    # sanitizer
    "PrunedFileInfo": ("git_narrator.sanitizer", "PrunedFileInfo"),
    "PruneReason": ("git_narrator.sanitizer", "PruneReason"),
    "SanitizedDiffResult": ("git_narrator.sanitizer", "SanitizedDiffResult"),
    "is_binary_path": ("git_narrator.sanitizer", "is_binary_path"),
    "is_generated_content": ("git_narrator.sanitizer", "is_generated_content"),
    "is_ignored_path": ("git_narrator.sanitizer", "is_ignored_path"),
    "is_minified_path": ("git_narrator.sanitizer", "is_minified_path"),
    "load_narratorignore": ("git_narrator.sanitizer", "load_narratorignore"),
    "parse_gitattributes": ("git_narrator.sanitizer", "parse_gitattributes"),
    "sanitize_diff": ("git_narrator.sanitizer", "sanitize_diff"),
    # lockfile
    "DependencyChange": ("git_narrator.lockfile", "DependencyChange"),
    "compact_lockfile_diff": ("git_narrator.lockfile", "compact_lockfile_diff"),
    "format_lockfile_summary": ("git_narrator.lockfile", "format_lockfile_summary"),
    "is_lockfile": ("git_narrator.lockfile", "is_lockfile"),
    "process_diff_lockfiles": ("git_narrator.lockfile", "process_diff_lockfiles"),
    "strip_lockfiles_and_inject_summary": ("git_narrator.lockfile", "strip_lockfiles_and_inject_summary"),
    # knapsack
    "DiffFile": ("git_narrator.knapsack", "DiffFile"),
    "DiffHunk": ("git_narrator.knapsack", "DiffHunk"),
    "KnapsackBudgetOptimizer": ("git_narrator.knapsack", "KnapsackBudgetOptimizer"),
    "KnapsackResult": ("git_narrator.knapsack", "KnapsackResult"),
    "classify_file_weight": ("git_narrator.knapsack", "classify_file_weight"),
    "compress_hunk_context": ("git_narrator.knapsack", "compress_hunk_context"),
    "estimate_tokens": ("git_narrator.knapsack", "estimate_tokens"),
    "has_interface_signature": ("git_narrator.knapsack", "has_interface_signature"),
    "optimize_diff_tokens": ("git_narrator.knapsack", "optimize_diff_tokens"),
    "parse_diff_files": ("git_narrator.knapsack", "parse_diff_files"),
    "score_hunk": ("git_narrator.knapsack", "score_hunk"),
}

__all__ = [
    "ChangeScope",
    "ChangeScopeType",
    "CommitInfo",
    "DependencyChange",
    "DiffFile",
    "DiffHunk",
    "FileNumStat",
    "GitCommandError",
    "GitEngine",
    "GitError",
    "KnapsackBudgetOptimizer",
    "KnapsackResult",
    "PruneReason",
    "PrunedFileInfo",
    "SanitizedDiffResult",
    "classify_file_weight",
    "compact_lockfile_diff",
    "compress_hunk_context",
    "detect_change_scope",
    "estimate_tokens",
    "format_lockfile_summary",
    "get_commit_context",
    "get_current_branch",
    "get_diff",
    "get_numstat",
    "get_repo_root",
    "get_stat",
    "has_interface_signature",
    "is_binary_path",
    "is_generated_content",
    "is_git_repo",
    "is_ignored_path",
    "is_lockfile",
    "is_minified_path",
    "load_narratorignore",
    "optimize_diff_tokens",
    "parse_diff_files",
    "parse_gitattributes",
    "process_diff_lockfiles",
    "run_git",
    "sanitize_diff",
    "score_hunk",
    "strip_lockfiles_and_inject_summary",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted([*globals().keys(), *__all__])
