"""Git engine: high-performance git inspection, change detection, and diff extraction."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Literal, Optional, Sequence


class GitError(Exception):
    """Base exception for all git operations."""


class GitNotFoundError(GitError):
    """Raised when git executable is not found in system PATH."""


class GitCommandError(GitError):
    """Raised when a git command returns a non-zero exit code."""

    def __init__(self, command: list[str], returncode: int, stdout: str, stderr: str):
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        cmd_str = " ".join(command)
        super().__init__(
            f"Git command failed [{returncode}]: {cmd_str}\n"
            f"STDERR: {stderr.strip()}\n"
            f"STDOUT: {stdout.strip()}"
        )


@dataclass(frozen=True)
class FileNumStat:
    """Numstat entry for a file in a diff."""

    path: str
    additions: int
    deletions: int
    old_path: Optional[str] = None
    is_binary: bool = False


@dataclass(frozen=True)
class CommitInfo:
    """Metadata extracted for a git commit."""

    sha: str
    short_sha: str
    author_name: str
    author_email: str
    date: str
    subject: str
    body: str
    parents: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        """Full commit message (subject + body)."""
        if self.body:
            return f"{self.subject}\n\n{self.body}".strip()
        return self.subject


ChangeScopeType = Literal["staged", "unstaged", "commit", "range", "empty"]


@dataclass
class ChangeScope:
    """Detected scope of changes in the git repository."""

    scope_type: ChangeScopeType
    ref: Optional[str] = None
    description: str = ""
    staged_files: list[str] = field(default_factory=list)
    unstaged_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)
    commit_info: Optional[CommitInfo] = None


def run_git(
    args: Sequence[str],
    cwd: Path | str | None = None,
    timeout: float = 15.0,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Execute a git command with fast subprocess execution.

    Args:
        args: Sequence of git arguments (without 'git' prefix).
        cwd: Directory where the command should be run.
        timeout: Execution timeout in seconds.
        check: Whether to raise GitCommandError if returncode != 0.

    Returns:
        CompletedProcess with decoded stdout and stderr.

    Raises:
        GitNotFoundError: If git binary is missing from PATH.
        GitCommandError: If command fails and check=True.
    """
    git_bin = shutil.which("git")
    if not git_bin:
        raise GitNotFoundError("git executable not found in system PATH.")

    cmd = [git_bin, "--no-pager"] + list(args)

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"Git command timed out after {timeout}s: {' '.join(cmd)}") from exc
    except OSError as exc:
        raise GitError(f"Failed to execute git process: {exc}") from exc

    if check and proc.returncode != 0:
        raise GitCommandError(
            command=cmd,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    return proc


def is_git_repo(repo_path: Path | str = ".") -> bool:
    """Check if the provided directory is inside a git working tree.

    Args:
        repo_path: Path to inspect.

    Returns:
        True if inside a git repository, False otherwise.
    """
    proc = run_git(["rev-parse", "--is-inside-work-tree"], cwd=repo_path)
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def get_repo_root(repo_path: Path | str = ".") -> Path:
    """Get the absolute root directory of the git repository.

    Args:
        repo_path: Directory inside the repository.

    Returns:
        Path to the repository root.

    Raises:
        GitError: If not inside a git repository.
    """
    proc = run_git(["rev-parse", "--show-toplevel"], cwd=repo_path)
    if proc.returncode != 0:
        raise GitError(f"Not a git repository: {repo_path}")
    return Path(proc.stdout.strip()).resolve()


def get_current_branch(repo_path: Path | str = ".") -> str:
    """Get current branch name or short commit SHA if in detached HEAD state.

    Args:
        repo_path: Repository path.

    Returns:
        Branch name or detached head identifier.
    """
    proc = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    if proc.returncode != 0:
        return "HEAD"
    branch = proc.stdout.strip()
    if branch == "HEAD":
        # Detached HEAD, obtain short SHA
        short_sha_proc = run_git(["rev-parse", "--short", "HEAD"], cwd=repo_path)
        if short_sha_proc.returncode == 0:
            return f"HEAD (detached at {short_sha_proc.stdout.strip()})"
    return branch


def get_commit_context(repo_path: Path | str = ".", commit_ref: str = "HEAD") -> CommitInfo:
    """Extract metadata for a specific commit.

    Args:
        repo_path: Repository path.
        commit_ref: Commit ref (e.g., 'HEAD', SHA, tag).

    Returns:
        CommitInfo object.

    Raises:
        GitCommandError: If the commit ref cannot be resolved.
    """
    # Format: SHA, short SHA, author name, author email, author date ISO, subject, body, parents
    # Delimited by null bytes
    fmt = "%H%x00%h%x00%an%x00%ae%x00%aI%x00%s%x00%b%x00%P"
    proc = run_git(["log", "-1", f"--format={fmt}", commit_ref], cwd=repo_path, check=True)

    parts = proc.stdout.split("\x00")
    if len(parts) < 8:
        raise GitError(f"Unexpected git log output format for commit {commit_ref}")

    sha = parts[0].strip()
    short_sha = parts[1].strip()
    author_name = parts[2].strip()
    author_email = parts[3].strip()
    date = parts[4].strip()
    subject = parts[5].strip()
    body = parts[6].strip()
    parents = parts[7].strip().split() if parts[7].strip() else []

    return CommitInfo(
        sha=sha,
        short_sha=short_sha,
        author_name=author_name,
        author_email=author_email,
        date=date,
        subject=subject,
        body=body,
        parents=parents,
    )


def detect_change_scope(repo_path: Path | str = ".") -> ChangeScope:
    """Smartly detect the change scope in the repository.

    Evaluation order:
    1. Check for staged changes (`git diff --staged --name-only`).
    2. Check for unstaged changes in working tree (`git diff --name-only`).
    3. Fall back to HEAD commit if repository has commit history.
    4. Empty state if no commits and no working tree modifications.

    Args:
        repo_path: Repository path.

    Returns:
        ChangeScope indicating the type of changes and file lists.
    """
    if not is_git_repo(repo_path):
        raise GitError(f"Directory is not a git repository: {repo_path}")

    # Check staged changes
    staged_proc = run_git(["diff", "--staged", "--name-only"], cwd=repo_path)
    staged_files = [f for f in staged_proc.stdout.splitlines() if f.strip()]

    if staged_files:
        return ChangeScope(
            scope_type="staged",
            description=f"Staged changes ({len(staged_files)} files)",
            staged_files=staged_files,
        )

    # Check unstaged changes
    unstaged_proc = run_git(["diff", "--name-only"], cwd=repo_path)
    unstaged_files = [f for f in unstaged_proc.stdout.splitlines() if f.strip()]

    # Also detect untracked files for comprehensive context
    untracked_proc = run_git(["ls-files", "--others", "--exclude-standard"], cwd=repo_path)
    untracked_files = [f for f in untracked_proc.stdout.splitlines() if f.strip()]

    if unstaged_files or untracked_files:
        return ChangeScope(
            scope_type="unstaged",
            description=f"Unstaged working tree changes ({len(unstaged_files)} modified, {len(untracked_files)} untracked)",
            unstaged_files=unstaged_files,
            untracked_files=untracked_files,
        )

    # Check if HEAD exists (repo has at least one commit)
    head_proc = run_git(["rev-parse", "--verify", "HEAD"], cwd=repo_path)
    if head_proc.returncode == 0:
        commit_info = get_commit_context(repo_path, "HEAD")
        return ChangeScope(
            scope_type="commit",
            ref="HEAD",
            description=f"HEAD commit: {commit_info.short_sha} {commit_info.subject}",
            commit_info=commit_info,
        )

    return ChangeScope(
        scope_type="empty",
        description="Repository is clean with no commits.",
    )


def _resolve_target_args(
    repo_path: Path | str,
    target: Optional[str] = None,
    staged: bool = False,
    unified_context: int = 3,
) -> tuple[list[str], bool]:
    """Helper to convert target/staged flags into git diff arguments.

    Returns:
        Tuple of (args_list, is_diff_tree_call)
    """
    u_flag = f"-U{unified_context}"

    if staged or target == "staged":
        return ["diff", "--staged", u_flag], False

    if target is None:
        # Default unstaged diff
        return ["diff", u_flag], False

    # Check for range comparison (e.g., main..feature or commit1...commit2)
    if ".." in target:
        return ["diff", target, u_flag], False

    # Check if target is a single commit or ref
    rev_proc = run_git(["rev-parse", "--verify", f"{target}^{{commit}}"], cwd=repo_path)
    if rev_proc.returncode == 0:
        # It's a valid commit ref
        # Check parents
        parents_proc = run_git(["rev-list", "--parents", "-n", "1", target], cwd=repo_path)
        tokens = parents_proc.stdout.strip().split()
        if len(tokens) > 1:
            # Has at least one parent: diff parent..commit
            parent_sha = tokens[1]
            return ["diff", parent_sha, target, u_flag], False
        else:
            # Root commit (no parent) -> use diff-tree --root
            return ["diff-tree", "--root", "-p", u_flag, target], True

    # Otherwise fallback to git diff with target (e.g. tree-ish or branch)
    return ["diff", target, u_flag], False


def get_diff(
    repo_path: Path | str = ".",
    target: Optional[str] = None,
    staged: bool = False,
    unified_context: int = 3,
    pathspecs: Optional[Sequence[str]] = None,
) -> str:
    """Extract raw unified diff from repository.

    Supports staged changes, unstaged changes, arbitrary refs (e.g. `main..feature`,
    `HEAD~1`, commit hash), and root commits.

    Args:
        repo_path: Repository path.
        target: Target commit, range, or ref.
        staged: If True, inspect staged changes.
        unified_context: Number of context lines (default 3).
        pathspecs: Optional specific file paths or patterns to diff.

    Returns:
        Unified diff string.
    """
    args, _ = _resolve_target_args(repo_path, target=target, staged=staged, unified_context=unified_context)
    if pathspecs:
        args.append("--")
        args.extend(pathspecs)

    proc = run_git(args, cwd=repo_path, check=True)
    return proc.stdout


def _parse_numstat_line(line: str) -> Optional[FileNumStat]:
    """Parse a single line from `git diff --numstat`."""
    line = line.strip()
    if not line:
        return None

    parts = line.split("\t")
    if len(parts) < 3:
        return None

    add_str, del_str = parts[0], parts[1]
    path_part = parts[2]

    # Binary files are marked with '-' for additions and deletions
    if add_str == "-" and del_str == "-":
        return FileNumStat(
            path=path_part,
            additions=0,
            deletions=0,
            is_binary=True,
        )

    try:
        additions = int(add_str)
        deletions = int(del_str)
    except ValueError:
        return None

    # Handle rename syntax: {old => new}/path or old => new
    old_path: Optional[str] = None
    path = path_part
    if " => " in path_part:
        rename_match = re.search(r"^(.*?)(?:\{([^{}]*) => ([^{}]*)\})(.*?)$", path_part)
        if rename_match:
            prefix, old_mid, new_mid, suffix = rename_match.groups()
            old_path = f"{prefix}{old_mid}{suffix}".replace("//", "/")
            path = f"{prefix}{new_mid}{suffix}".replace("//", "/")
        else:
            old_p, new_p = path_part.split(" => ", 1)
            old_path = old_p.strip()
            path = new_p.strip()

    return FileNumStat(
        path=path,
        additions=additions,
        deletions=deletions,
        old_path=old_path,
        is_binary=False,
    )


def get_numstat(
    repo_path: Path | str = ".",
    target: Optional[str] = None,
    staged: bool = False,
    pathspecs: Optional[Sequence[str]] = None,
) -> list[FileNumStat]:
    """Extract file modification statistics (`git diff --numstat`).

    Args:
        repo_path: Repository path.
        target: Target commit, range, or ref.
        staged: If True, inspect staged changes.
        pathspecs: Optional specific file paths or patterns.

    Returns:
        List of FileNumStat objects containing additions, deletions, and paths.
    """
    args, is_diff_tree = _resolve_target_args(repo_path, target=target, staged=staged, unified_context=0)

    # Replace diff action with numstat flags
    if is_diff_tree:
        # For diff-tree --root -p -U0 target -> diff-tree --root --numstat target
        args = [a for a in args if a not in ("-p", "-U0")]
        args.insert(2, "--numstat")
    else:
        # For diff -U0 ... -> diff --numstat ...
        args = [a for a in args if not a.startswith("-U")]
        args.insert(1, "--numstat")

    if pathspecs:
        args.append("--")
        args.extend(pathspecs)

    proc = run_git(args, cwd=repo_path, check=True)
    results: list[FileNumStat] = []
    for line in proc.stdout.splitlines():
        stat = _parse_numstat_line(line)
        if stat is not None:
            results.append(stat)
    return results


def get_stat(
    repo_path: Path | str = ".",
    target: Optional[str] = None,
    staged: bool = False,
    pathspecs: Optional[Sequence[str]] = None,
) -> str:
    """Extract standard git diff summary (`git diff --stat`).

    Args:
        repo_path: Repository path.
        target: Target commit, range, or ref.
        staged: If True, inspect staged changes.
        pathspecs: Optional specific file paths or patterns.

    Returns:
        Raw `--stat` string output from git.
    """
    args, is_diff_tree = _resolve_target_args(repo_path, target=target, staged=staged, unified_context=0)

    if is_diff_tree:
        args = [a for a in args if a not in ("-p", "-U0")]
        args.insert(2, "--stat")
    else:
        args = [a for a in args if not a.startswith("-U")]
        args.insert(1, "--stat")

    if pathspecs:
        args.append("--")
        args.extend(pathspecs)

    proc = run_git(args, cwd=repo_path, check=True)
    return proc.stdout.strip()


class GitEngine:
    """Stateful coordinator for git repository inspection."""

    def __init__(self, repo_path: Path | str = "."):
        self.repo_path = Path(repo_path).resolve()
        self._root: Optional[Path] = None

    @property
    def root(self) -> Path:
        """Cached repository root directory."""
        if self._root is None:
            self._root = get_repo_root(self.repo_path)
        return self._root

    def is_valid_repo(self) -> bool:
        """Check if repository path is inside a git working tree."""
        return is_git_repo(self.repo_path)

    def current_branch(self) -> str:
        """Get active branch name."""
        return get_current_branch(self.repo_path)

    def detect_scope(self) -> ChangeScope:
        """Detect staged, unstaged, or commit scope."""
        return detect_change_scope(self.repo_path)

    def get_diff(
        self,
        target: Optional[str] = None,
        staged: bool = False,
        unified_context: int = 3,
        pathspecs: Optional[Sequence[str]] = None,
    ) -> str:
        """Extract diff."""
        return get_diff(
            self.repo_path,
            target=target,
            staged=staged,
            unified_context=unified_context,
            pathspecs=pathspecs,
        )

    def get_numstat(
        self,
        target: Optional[str] = None,
        staged: bool = False,
        pathspecs: Optional[Sequence[str]] = None,
    ) -> list[FileNumStat]:
        """Extract numstat."""
        return get_numstat(
            self.repo_path,
            target=target,
            staged=staged,
            pathspecs=pathspecs,
        )

    def get_stat(
        self,
        target: Optional[str] = None,
        staged: bool = False,
        pathspecs: Optional[Sequence[str]] = None,
    ) -> str:
        """Extract stat."""
        return get_stat(
            self.repo_path,
            target=target,
            staged=staged,
            pathspecs=pathspecs,
        )

    def get_commit(self, commit_ref: str = "HEAD") -> CommitInfo:
        """Extract commit context."""
        return get_commit_context(self.repo_path, commit_ref=commit_ref)
