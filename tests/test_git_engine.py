"""Tests for git_engine module: repository inspection, change detection, and diff extraction."""

from pathlib import Path
import subprocess
import tempfile
import pytest

from git_narrator.git_engine import (
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


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Fixture that initializes a temporary git repository with initial commits."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Configure local git
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Author"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    # Initial commit
    file1 = repo_dir / "app.py"
    file1.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "feat: initial commit\n\nExtended commit body message."], cwd=repo_dir, check=True)

    return repo_dir


def test_is_git_repo(temp_git_repo: Path, tmp_path: Path):
    assert is_git_repo(temp_git_repo) is True
    # Non-repo folder
    non_repo = tmp_path / "not_git"
    non_repo.mkdir()
    assert is_git_repo(non_repo) is False


def test_get_repo_root(temp_git_repo: Path, tmp_path: Path):
    root = get_repo_root(temp_git_repo)
    assert root.resolve() == temp_git_repo.resolve()

    sub_dir = temp_git_repo / "src" / "deep"
    sub_dir.mkdir(parents=True)
    assert get_repo_root(sub_dir).resolve() == temp_git_repo.resolve()

    non_repo = tmp_path / "empty_dir"
    non_repo.mkdir()
    with pytest.raises(GitError):
        get_repo_root(non_repo)


def test_get_current_branch(temp_git_repo: Path):
    branch = get_current_branch(temp_git_repo)
    assert branch == "main"

    # Create new branch
    run_git(["checkout", "-b", "feature/awesome"], cwd=temp_git_repo, check=True)
    assert get_current_branch(temp_git_repo) == "feature/awesome"


def test_detect_change_scope_staged(temp_git_repo: Path):
    # Staging a modification
    app_file = temp_git_repo / "app.py"
    app_file.write_text("def hello():\n    return 'narrator'\n", encoding="utf-8")
    run_git(["add", "app.py"], cwd=temp_git_repo, check=True)

    scope = detect_change_scope(temp_git_repo)
    assert scope.scope_type == "staged"
    assert "app.py" in scope.staged_files


def test_detect_change_scope_unstaged(temp_git_repo: Path):
    # Unstaged modification
    app_file = temp_git_repo / "app.py"
    app_file.write_text("def hello():\n    return 'changed unstaged'\n", encoding="utf-8")

    scope = detect_change_scope(temp_git_repo)
    assert scope.scope_type == "unstaged"
    assert "app.py" in scope.unstaged_files


def test_detect_change_scope_fallback_head(temp_git_repo: Path):
    # Clean working tree -> falls back to HEAD commit
    scope = detect_change_scope(temp_git_repo)
    assert scope.scope_type == "commit"
    assert scope.ref == "HEAD"
    assert scope.commit_info is not None
    assert scope.commit_info.subject == "feat: initial commit"


def test_get_commit_context(temp_git_repo: Path):
    commit = get_commit_context(temp_git_repo, "HEAD")
    assert commit.author_name == "Test Author"
    assert commit.author_email == "test@example.com"
    assert commit.subject == "feat: initial commit"
    assert "Extended commit body message." in commit.body
    assert len(commit.sha) == 40
    assert len(commit.short_sha) >= 7


def test_get_diff_and_numstat_staged_and_unstaged(temp_git_repo: Path):
    app_file = temp_git_repo / "app.py"
    app_file.write_text("def hello():\n    print('debug')\n    return 'world'\n", encoding="utf-8")

    # Unstaged diff
    diff_unstaged = get_diff(temp_git_repo, unified_context=3)
    assert "print('debug')" in diff_unstaged

    # Staged diff
    run_git(["add", "app.py"], cwd=temp_git_repo, check=True)
    diff_staged = get_diff(temp_git_repo, staged=True)
    assert "print('debug')" in diff_staged

    # Numstat
    numstats = get_numstat(temp_git_repo, staged=True)
    assert len(numstats) == 1
    assert numstats[0].path == "app.py"
    assert numstats[0].additions == 1
    assert numstats[0].deletions == 0

    # Stat
    stat_str = get_stat(temp_git_repo, staged=True)
    assert "app.py" in stat_str


def test_arbitrary_ref_comparison(temp_git_repo: Path):
    # Commit change on main
    app_file = temp_git_repo / "app.py"
    app_file.write_text("def hello():\n    return 'v1'\n", encoding="utf-8")
    run_git(["commit", "-am", "commit v1"], cwd=temp_git_repo, check=True)

    # Branch feature
    run_git(["checkout", "-b", "feature"], cwd=temp_git_repo, check=True)
    feature_file = temp_git_repo / "feature.py"
    feature_file.write_text("def feature(): pass\n", encoding="utf-8")
    run_git(["add", "feature.py"], cwd=temp_git_repo, check=True)
    run_git(["commit", "-m", "add feature"], cwd=temp_git_repo, check=True)

    # Range comparison main..feature
    diff_range = get_diff(temp_git_repo, target="main..feature")
    assert "feature.py" in diff_range

    # Commit ref HEAD (inspects HEAD commit)
    diff_head = get_diff(temp_git_repo, target="HEAD")
    assert "feature.py" in diff_head

    # Commit ref HEAD~1 (inspects HEAD~1 commit)
    diff_head_1 = get_diff(temp_git_repo, target="HEAD~1")
    assert "app.py" in diff_head_1


def test_git_engine_wrapper(temp_git_repo: Path):
    engine = GitEngine(temp_git_repo)
    assert engine.is_valid_repo() is True
    assert engine.root == temp_git_repo.resolve()
    assert engine.current_branch() == "main"
    scope = engine.detect_scope()
    assert scope.scope_type == "commit"
