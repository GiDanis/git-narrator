"""Git engine: high-performance git inspection, change detection, and diff extraction."""

from __future__ import annotations

import difflib
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import re
import shutil
import subprocess
from typing import Literal

HOOK_MARKER = "# git-narrator-managed-hook"


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
    old_path: str | None = None
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
    ref: str | None = None
    description: str = ""
    staged_files: list[str] = field(default_factory=list)
    unstaged_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)
    commit_info: CommitInfo | None = None


@lru_cache(maxsize=1)
def _find_git_binary() -> str:
    """Locate git executable once per process."""
    git_bin = shutil.which("git")
    if not git_bin:
        raise GitNotFoundError("git executable not found in system PATH.")
    return git_bin


def run_git(
    args: Sequence[str],
    cwd: Path | str | None = None,
    timeout: float = 15.0,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Execute a git command with fast subprocess execution."""
    git_bin = _find_git_binary()
    cmd = [git_bin, "--no-pager", *args]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
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
    """Check if the provided directory is inside a git working tree."""
    proc = run_git(["rev-parse", "--is-inside-work-tree"], cwd=repo_path)
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def get_repo_root(repo_path: Path | str = ".") -> Path:
    """Get the absolute root directory of the git repository."""
    proc = run_git(["rev-parse", "--show-toplevel"], cwd=repo_path)
    if proc.returncode != 0:
        raise GitError(f"Not a git repository: {repo_path}")
    return Path(proc.stdout.strip()).resolve()


def get_current_branch(repo_path: Path | str = ".") -> str:
    """Get current branch name or short commit SHA if in detached HEAD state."""
    proc = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    if proc.returncode != 0:
        return "HEAD"
    branch = proc.stdout.strip()
    if branch == "HEAD":
        short_sha_proc = run_git(["rev-parse", "--short", "HEAD"], cwd=repo_path)
        if short_sha_proc.returncode == 0:
            return f"HEAD (detached at {short_sha_proc.stdout.strip()})"
    return branch


def get_commit_context(repo_path: Path | str = ".", commit_ref: str = "HEAD") -> CommitInfo:
    """Extract metadata for a specific commit."""
    fmt = "%H%x00%h%x00%an%x00%ae%x00%aI%x00%s%x00%b%x00%P"
    proc = run_git(["log", "-1", f"--format={fmt}", commit_ref], cwd=repo_path, check=True)

    parts = proc.stdout.split("\x00")
    if len(parts) < 8:
        raise GitError(f"Unexpected git log output format for commit {commit_ref}")

    return CommitInfo(
        sha=parts[0].strip(),
        short_sha=parts[1].strip(),
        author_name=parts[2].strip(),
        author_email=parts[3].strip(),
        date=parts[4].strip(),
        subject=parts[5].strip(),
        body=parts[6].strip(),
        parents=parts[7].strip().split() if parts[7].strip() else [],
    )


def detect_change_scope(repo_path: Path | str = ".") -> ChangeScope:
    """Smartly detect the change scope in the repository.

    Evaluation order:
    1. Staged changes (`git diff --staged --name-only`)
    2. Unstaged or untracked changes in working tree
    3. HEAD commit if repository has commit history
    4. Empty state if clean and no commits exist
    """
    if not is_git_repo(repo_path):
        raise GitError(f"Directory is not a git repository: {repo_path}")

    staged_proc = run_git(["diff", "--staged", "--name-only"], cwd=repo_path)
    staged_files = [f for f in staged_proc.stdout.splitlines() if f.strip()]

    if staged_files:
        return ChangeScope(
            scope_type="staged",
            description=f"Staged changes ({len(staged_files)} files)",
            staged_files=staged_files,
        )

    unstaged_proc = run_git(["diff", "--name-only"], cwd=repo_path)
    unstaged_files = [f for f in unstaged_proc.stdout.splitlines() if f.strip()]

    untracked_proc = run_git(["ls-files", "--others", "--exclude-standard"], cwd=repo_path)
    untracked_files = [f for f in untracked_proc.stdout.splitlines() if f.strip()]

    if unstaged_files or untracked_files:
        return ChangeScope(
            scope_type="unstaged",
            description=(
                f"Unstaged working tree changes ({len(unstaged_files)} modified, "
                f"{len(untracked_files)} untracked)"
            ),
            unstaged_files=unstaged_files,
            untracked_files=untracked_files,
        )

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
    target: str | None = None,
    staged: bool = False,
    unified_context: int = 3,
) -> tuple[list[str], bool]:
    """Convert target/staged flags into canonical git diff arguments."""
    u_flag = f"-U{unified_context}"
    prefix_cfg = ["-c", "diff.mnemonicPrefix=false", "-c", "core.quotePath=false"]

    if staged or target == "staged":
        return [*prefix_cfg, "diff", "--staged", u_flag], False

    if target is None or target == "unstaged":
        return [*prefix_cfg, "diff", u_flag], False

    if ".." in target:
        return [*prefix_cfg, "diff", target, u_flag], False

    rev_proc = run_git(["rev-parse", "--verify", f"{target}^{{commit}}"], cwd=repo_path)
    if rev_proc.returncode == 0:
        parents_proc = run_git(["rev-list", "--parents", "-n", "1", target], cwd=repo_path)
        tokens = parents_proc.stdout.strip().split()
        if len(tokens) > 1:
            parent_sha = tokens[1]
            return [*prefix_cfg, "diff", parent_sha, target, u_flag], False
        return [*prefix_cfg, "diff-tree", "--root", "-p", u_flag, target], True

    return [*prefix_cfg, "diff", target, u_flag], False


def _replace_diff_mode(args: list[str], is_diff_tree: bool, flag: str) -> list[str]:
    """Swap -p/-U context flags for --stat or --numstat safely despite leading -c flags."""
    if is_diff_tree:
        cleaned = [a for a in args if a not in ("-p", "-U0") and not a.startswith("-U")]
        idx = cleaned.index("diff-tree")
        cleaned.insert(idx + 2, flag)
        return cleaned

    cleaned = [a for a in args if not a.startswith("-U")]
    idx = cleaned.index("diff")
    cleaned.insert(idx + 1, flag)
    return cleaned


def get_diff(
    repo_path: Path | str = ".",
    target: str | None = None,
    staged: bool = False,
    unified_context: int = 3,
    pathspecs: Sequence[str] | None = None,
) -> str:
    """Extract raw unified diff from repository."""
    args, _ = _resolve_target_args(repo_path, target=target, staged=staged, unified_context=unified_context)
    if pathspecs:
        args.append("--")
        args.extend(pathspecs)

    proc = run_git(args, cwd=repo_path, check=True)
    return proc.stdout


def get_untracked_diffs(
    repo_path: Path | str,
    untracked_files: Sequence[str],
    max_files: int = 20,
    max_bytes_per_file: int = 100_000,
) -> str:
    """Synthesize unified git diff chunks for untracked files in working tree."""
    if not untracked_files:
        return ""

    root = Path(repo_path)
    chunks: list[str] = []

    for rel_path in untracked_files[:max_files]:
        file_path = root / rel_path
        if not file_path.is_file():
            continue
        try:
            raw_bytes = file_path.read_bytes()
        except OSError:
            continue

        norm_path = rel_path.replace("\\", "/")
        if b"\x00" in raw_bytes[:8192]:
            chunks.append(
                f"diff --git a/{norm_path} b/{norm_path}\n"
                f"new file mode 100644\n"
                f"Binary files /dev/null and b/{norm_path} differ\n"
            )
            continue

        if len(raw_bytes) > max_bytes_per_file:
            raw_bytes = raw_bytes[:max_bytes_per_file]

        text = raw_bytes.decode("utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        diff_lines = list(
            difflib.unified_diff(
                [],
                lines,
                fromfile="/dev/null",
                tofile=f"b/{norm_path}",
            )
        )
        if not diff_lines:
            continue

        header = (
            f"diff --git a/{norm_path} b/{norm_path}\n"
            f"new file mode 100644\n"
        )
        body = "".join(diff_lines)
        if not body.endswith("\n"):
            body += "\n"
        chunks.append(header + body)

    return "".join(chunks)


def _parse_numstat_line(line: str) -> FileNumStat | None:
    """Parse a single line from `git diff --numstat`."""
    line = line.strip()
    if not line:
        return None

    parts = line.split("\t")
    if len(parts) < 3:
        return None

    add_str, del_str, path_part = parts[0], parts[1], parts[2]

    if add_str == "-" and del_str == "-":
        return FileNumStat(path=path_part, additions=0, deletions=0, is_binary=True)

    try:
        additions = int(add_str)
        deletions = int(del_str)
    except ValueError:
        return None

    old_path: str | None = None
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
    target: str | None = None,
    staged: bool = False,
    pathspecs: Sequence[str] | None = None,
) -> list[FileNumStat]:
    """Extract file modification statistics (`git diff --numstat`)."""
    args, is_diff_tree = _resolve_target_args(repo_path, target=target, staged=staged, unified_context=0)
    args = _replace_diff_mode(args, is_diff_tree, "--numstat")

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
    target: str | None = None,
    staged: bool = False,
    pathspecs: Sequence[str] | None = None,
) -> str:
    """Extract standard git diff summary (`git diff --stat`)."""
    args, is_diff_tree = _resolve_target_args(repo_path, target=target, staged=staged, unified_context=0)
    args = _replace_diff_mode(args, is_diff_tree, "--stat")

    if pathspecs:
        args.append("--")
        args.extend(pathspecs)

    proc = run_git(args, cwd=repo_path, check=True)
    return proc.stdout.strip()


def install_prepare_commit_msg_hook(repo_path: Path | str = ".", force: bool = False) -> Path:
    """Install a `prepare-commit-msg` git hook that pre-populates AI commit messages."""
    root = get_repo_root(repo_path)
    proc = run_git(["rev-parse", "--git-path", "hooks/prepare-commit-msg"], cwd=root, check=True)
    hook_path = Path(proc.stdout.strip())
    if not hook_path.is_absolute():
        hook_path = root / hook_path

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8", errors="replace")
        if HOOK_MARKER not in existing and not force:
            raise GitError(
                f"Existing custom hook found at {hook_path}. Pass --force to overwrite."
            )

    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_script = (
        "#!/usr/bin/env sh\n"
        f"{HOOK_MARKER}\n"
        'COMMIT_MSG_FILE="$1"\n'
        'COMMIT_SOURCE="$2"\n'
        '# Only auto-populate interactive empty commits (skip merge, squash, -m, amend)\n'
        'if [ -z "$COMMIT_SOURCE" ] && command -v git-narrator >/dev/null 2>&1; then\n'
        '  git-narrator _prepare-hook "$COMMIT_MSG_FILE" || true\n'
        "fi\n"
    )
    hook_path.write_text(hook_script, encoding="utf-8")
    hook_path.chmod(0o755)
    return hook_path


class GitEngine:
    """Stateful coordinator for git repository inspection."""

    def __init__(self, repo_path: Path | str = "."):
        self.repo_path = Path(repo_path).resolve()
        self._root: Path | None = None

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
        target: str | None = None,
        staged: bool = False,
        unified_context: int = 3,
        pathspecs: Sequence[str] | None = None,
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
        target: str | None = None,
        staged: bool = False,
        pathspecs: Sequence[str] | None = None,
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
        target: str | None = None,
        staged: bool = False,
        pathspecs: Sequence[str] | None = None,
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
