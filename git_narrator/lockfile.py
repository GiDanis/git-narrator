"""Lockfile delta compactor: extracts concise dependency updates from massive lockfile diffs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
from typing import Literal, Optional, Sequence

from git_narrator.sanitizer import split_diff_into_file_chunks

# Recognized lockfile names and patterns
LOCKFILE_FILENAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "cargo.lock",
    "poetry.lock",
    "uv.lock",
}

ChangeType = Literal["ADDED", "REMOVED", "UPGRADED", "DOWNGRADED"]


@dataclass(frozen=True)
class DependencyChange:
    """Represents a discrete dependency delta extracted from a lockfile."""

    name: str
    change_type: ChangeType
    old_version: Optional[str]
    new_version: Optional[str]
    file: str
    manager: str

    def format_line(self) -> str:
        """Format into high-signal metadata string."""
        if self.change_type == "UPGRADED":
            return f"[UPGRADE] {self.name} {self.old_version} -> {self.new_version}"
        elif self.change_type == "DOWNGRADED":
            return f"[DOWNGRADE] {self.name} {self.old_version} -> {self.new_version}"
        elif self.change_type == "ADDED":
            ver = f" {self.new_version}" if self.new_version else ""
            return f"[ADD] {self.name}{ver}"
        elif self.change_type == "REMOVED":
            ver = f" {self.old_version}" if self.old_version else ""
            return f"[REMOVE] {self.name}{ver}"
        return f"[{self.change_type}] {self.name}"


def is_lockfile(path: str | Path) -> bool:
    """Determine if a file path is a known package manager lockfile or requirements file.

    Args:
        path: File path to inspect.

    Returns:
        True if the file matches recognized lockfile patterns.
    """
    filename = Path(path).name.lower()
    if filename in LOCKFILE_FILENAMES:
        return True

    # Requirements files
    if "requirements" in filename and filename.endswith(".txt"):
        return True

    return False


def detect_package_manager(path: str | Path) -> str:
    """Identify package manager from lockfile path."""
    filename = Path(path).name.lower()
    if filename == "package-lock.json":
        return "npm"
    elif filename == "pnpm-lock.yaml":
        return "pnpm"
    elif filename == "yarn.lock":
        return "yarn"
    elif filename == "cargo.lock":
        return "cargo"
    elif filename == "poetry.lock":
        return "poetry"
    elif filename == "uv.lock":
        return "uv"
    elif "requirements" in filename:
        return "pip"
    return "unknown"


def _compare_versions(old_ver: str, new_ver: str) -> ChangeType:
    """Compare two version strings to determine UPGRADED vs DOWNGRADED."""
    # Extract digit sequences
    def parse_parts(v: str) -> list[int]:
        clean = re.sub(r"^[vV]", "", v.strip())
        parts = []
        for segment in re.split(r"[\.-]", clean):
            match = re.match(r"^\d+", segment)
            if match:
                parts.append(int(match.group(0)))
            else:
                parts.append(0)
        return parts

    try:
        p_old = parse_parts(old_ver)
        p_new = parse_parts(new_ver)
        # Pad with zeros
        max_len = max(len(p_old), len(p_new))
        p_old += [0] * (max_len - len(p_old))
        p_new += [0] * (max_len - len(p_new))
        if p_new > p_old:
            return "UPGRADED"
        elif p_new < p_old:
            return "DOWNGRADED"
        else:
            return "UPGRADED"
    except Exception:
        return "UPGRADED"


# ---------------------------------------------------------------------------
# Format Parsers
# ---------------------------------------------------------------------------

def _parse_requirements_diff(diff_content: str, file_path: str) -> list[DependencyChange]:
    """Parse requirements.txt diffs."""
    # Matches: +requests==2.31.0 or -urllib3>=1.26.0
    req_pattern = re.compile(
        r"^([+-])\s*([a-zA-Z0-9_\-\.]+)\s*(?:==|>=|<=|~=|===)\s*([a-zA-Z0-9_\-\.\+]+)"
    )

    removed: dict[str, str] = {}
    added: dict[str, str] = {}

    for line in diff_content.splitlines():
        if not line or line.startswith("---") or line.startswith("+++"):
            continue
        match = req_pattern.match(line)
        if match:
            sign, name, ver = match.groups()
            name = name.lower()
            if sign == "-":
                removed[name] = ver
            elif sign == "+":
                added[name] = ver

    changes: list[DependencyChange] = []
    all_names = set(removed.keys()).union(added.keys())

    for name in sorted(all_names):
        if name in removed and name in added:
            old_v = removed[name]
            new_v = added[name]
            if old_v != new_v:
                c_type = _compare_versions(old_v, new_v)
                changes.append(
                    DependencyChange(
                        name=name,
                        change_type=c_type,
                        old_version=old_v,
                        new_version=new_v,
                        file=file_path,
                        manager="pip",
                    )
                )
        elif name in added:
            changes.append(
                DependencyChange(
                    name=name,
                    change_type="ADDED",
                    old_version=None,
                    new_version=added[name],
                    file=file_path,
                    manager="pip",
                )
            )
        elif name in removed:
            changes.append(
                DependencyChange(
                    name=name,
                    change_type="REMOVED",
                    old_version=removed[name],
                    new_version=None,
                    file=file_path,
                    manager="pip",
                )
            )

    return changes


def _parse_toml_lock_diff(diff_content: str, file_path: str, manager: str) -> list[DependencyChange]:
    """Parse Cargo.lock, uv.lock, poetry.lock diffs."""
    lines = diff_content.splitlines()

    # Track package modifications
    # Cargo/uv/poetry packages are organized in blocks:
    # [[package]]
    # name = "serde"
    # version = "1.0.197"
    removed_packages: dict[str, str] = {}
    added_packages: dict[str, str] = {}

    # State machine for diff blocks
    current_name: Optional[str] = None
    old_ver: Optional[str] = None
    new_ver: Optional[str] = None

    def commit_package():
        nonlocal current_name, old_ver, new_ver
        if current_name:
            if old_ver and not new_ver:
                removed_packages[current_name] = old_ver
            elif new_ver and not old_ver:
                added_packages[current_name] = new_ver
            elif old_ver and new_ver and old_ver != new_ver:
                removed_packages[current_name] = old_ver
                added_packages[current_name] = new_ver
        current_name = None
        old_ver = None
        new_ver = None

    name_regex = re.compile(r'^[+-]?\s*name\s*=\s*"([^"]+)"')
    ver_regex = re.compile(r'^([+-])\s*version\s*=\s*"([^"]+)"')
    pkg_header_regex = re.compile(r'^[+-]?\s*\[\[package\]\]')

    for line in lines:
        if pkg_header_regex.match(line):
            commit_package()
            continue

        n_match = name_regex.match(line)
        if n_match:
            # If name changed inside block, commit previous
            if current_name and current_name != n_match.group(1):
                commit_package()
            current_name = n_match.group(1)
            continue

        v_match = ver_regex.match(line)
        if v_match:
            sign, ver = v_match.groups()
            if sign == "-":
                old_ver = ver
            elif sign == "+":
                new_ver = ver

    commit_package()

    changes: list[DependencyChange] = []
    all_names = set(removed_packages.keys()).union(added_packages.keys())

    for name in sorted(all_names):
        if name in removed_packages and name in added_packages:
            o_v = removed_packages[name]
            n_v = added_packages[name]
            if o_v != n_v:
                c_type = _compare_versions(o_v, n_v)
                changes.append(
                    DependencyChange(
                        name=name,
                        change_type=c_type,
                        old_version=o_v,
                        new_version=n_v,
                        file=file_path,
                        manager=manager,
                    )
                )
        elif name in added_packages:
            changes.append(
                DependencyChange(
                    name=name,
                    change_type="ADDED",
                    old_version=None,
                    new_version=added_packages[name],
                    file=file_path,
                    manager=manager,
                )
            )
        elif name in removed_packages:
            changes.append(
                DependencyChange(
                    name=name,
                    change_type="REMOVED",
                    old_version=removed_packages[name],
                    new_version=None,
                    file=file_path,
                    manager=manager,
                )
            )

    return changes


def _parse_npm_diff(diff_content: str, file_path: str) -> list[DependencyChange]:
    """Parse package-lock.json diffs."""
    lines = diff_content.splitlines()

    removed: dict[str, str] = {}
    added: dict[str, str] = {}

    # Ignored npm json property keys
    ignored_npm_keys = {
        "version", "resolved", "integrity", "dev", "requires", "dependencies",
        "peerDependencies", "devDependencies", "packages", "engines", "license",
        "funding", "optional", "peer", "bin"
    }

    # Matches "node_modules/axios": { or "axios": {
    pkg_entry_regex = re.compile(r'^\s*[+-]?\s*"((?:node_modules/)?([@a-zA-Z0-9_\-\./]+))":\s*\{?')
    ver_regex = re.compile(r'^\s*([+-])\s*"version":\s*"([^"]+)"')
    simple_dep_regex = re.compile(r'^\s*([+-])\s*"([@a-zA-Z0-9_\-\./]+)":\s*"([^"]+)"')

    current_pkg: Optional[str] = None

    for line in lines:
        if line.startswith("---") or line.startswith("+++"):
            continue

        # Check version diff first
        v_match = ver_regex.match(line)
        if v_match and current_pkg:
            sign, ver = v_match.groups()
            if sign == "-":
                removed[current_pkg] = ver
            elif sign == "+":
                added[current_pkg] = ver
            continue

        p_match = pkg_entry_regex.match(line)
        if p_match:
            full_target = p_match.group(1)
            # Normalize node_modules/foo -> foo
            clean_name = full_target.replace("node_modules/", "")
            if clean_name and clean_name not in ignored_npm_keys and not clean_name.startswith("."):
                current_pkg = clean_name
            continue

        s_match = simple_dep_regex.match(line)
        if s_match:
            sign, name, ver = s_match.groups()
            clean_name = name.replace("node_modules/", "")
            if clean_name and clean_name not in ignored_npm_keys and not clean_name.startswith("."):
                if sign == "-":
                    removed[clean_name] = ver
                elif sign == "+":
                    added[clean_name] = ver

    changes: list[DependencyChange] = []
    all_names = set(removed.keys()).union(added.keys())

    for name in sorted(all_names):
        if name in removed and name in added:
            old_v = removed[name]
            new_v = added[name]
            if old_v != new_v:
                changes.append(
                    DependencyChange(
                        name=name,
                        change_type=_compare_versions(old_v, new_v),
                        old_version=old_v,
                        new_version=new_v,
                        file=file_path,
                        manager="npm",
                    )
                )
        elif name in added:
            changes.append(
                DependencyChange(
                    name=name,
                    change_type="ADDED",
                    old_version=None,
                    new_version=added[name],
                    file=file_path,
                    manager="npm",
                )
            )
        elif name in removed:
            changes.append(
                DependencyChange(
                    name=name,
                    change_type="REMOVED",
                    old_version=removed[name],
                    new_version=None,
                    file=file_path,
                    manager="npm",
                )
            )

    return changes


def _parse_yarn_diff(diff_content: str, file_path: str) -> list[DependencyChange]:
    """Parse yarn.lock diffs."""
    lines = diff_content.splitlines()

    # Matches axios@^1.2.0: or "@babel/core@^7.0.0":
    header_regex = re.compile(r'^[+-]?\s*"?([@a-zA-Z0-9_\-\./]+)@[^:]+:\s*$')
    ver_regex = re.compile(r'^([+-])\s*version\s*"([^"]+)"')

    removed: dict[str, str] = {}
    added: dict[str, str] = {}
    current_pkg: Optional[str] = None

    for line in lines:
        h_match = header_regex.match(line)
        if h_match:
            current_pkg = h_match.group(1)
            continue

        v_match = ver_regex.match(line)
        if v_match and current_pkg:
            sign, ver = v_match.groups()
            if sign == "-":
                removed[current_pkg] = ver
            elif sign == "+":
                added[current_pkg] = ver

    changes: list[DependencyChange] = []
    all_names = set(removed.keys()).union(added.keys())

    for name in sorted(all_names):
        if name in removed and name in added:
            old_v = removed[name]
            new_v = added[name]
            if old_v != new_v:
                changes.append(
                    DependencyChange(
                        name=name,
                        change_type=_compare_versions(old_v, new_v),
                        old_version=old_v,
                        new_version=new_v,
                        file=file_path,
                        manager="yarn",
                    )
                )
        elif name in added:
            changes.append(
                DependencyChange(
                    name=name,
                    change_type="ADDED",
                    old_version=None,
                    new_version=added[name],
                    file=file_path,
                    manager="yarn",
                )
            )
        elif name in removed:
            changes.append(
                DependencyChange(
                    name=name,
                    change_type="REMOVED",
                    old_version=removed[name],
                    new_version=None,
                    file=file_path,
                    manager="yarn",
                )
            )

    return changes


def _parse_pnpm_diff(diff_content: str, file_path: str) -> list[DependencyChange]:
    """Parse pnpm-lock.yaml diffs."""
    lines = diff_content.splitlines()

    # Matches: /axios@1.2.0: or axios@1.2.0:
    pkg_regex = re.compile(r"^[+-]?\s*['\"]?/?([@a-zA-Z0-9_\-\./]+)@([a-zA-Z0-9_\-\.\+]+)['\"]?:\s*$")
    # Matches: specifier or inline version
    simple_regex = re.compile(r"^([+-])\s*([@a-zA-Z0-9_\-\./]+):\s*([0-9\.\w\-]+)")

    removed: dict[str, str] = {}
    added: dict[str, str] = {}

    for line in lines:
        if line.startswith("---") or line.startswith("+++"):
            continue

        sign = line[0] if line and line[0] in ("+", "-") else None

        p_match = pkg_regex.match(line)
        if p_match:
            name, ver = p_match.groups()
            if sign == "-":
                removed[name] = ver
            elif sign == "+":
                added[name] = ver
            continue

        s_match = simple_regex.match(line)
        if s_match:
            s_sign, name, ver = s_match.groups()
            if not name.startswith("lockfileVersion"):
                if s_sign == "-":
                    removed[name] = ver
                elif s_sign == "+":
                    added[name] = ver

    changes: list[DependencyChange] = []
    all_names = set(removed.keys()).union(added.keys())

    for name in sorted(all_names):
        if name in removed and name in added:
            old_v = removed[name]
            new_v = added[name]
            if old_v != new_v:
                changes.append(
                    DependencyChange(
                        name=name,
                        change_type=_compare_versions(old_v, new_v),
                        old_version=old_v,
                        new_version=new_v,
                        file=file_path,
                        manager="pnpm",
                    )
                )
        elif name in added:
            changes.append(
                DependencyChange(
                    name=name,
                    change_type="ADDED",
                    old_version=None,
                    new_version=added[name],
                    file=file_path,
                    manager="pnpm",
                )
            )
        elif name in removed:
            changes.append(
                DependencyChange(
                    name=name,
                    change_type="REMOVED",
                    old_version=removed[name],
                    new_version=None,
                    file=file_path,
                    manager="pnpm",
                )
            )

    return changes


def compact_lockfile_diff(file_path: str, diff_content: str) -> list[DependencyChange]:
    """Extract added, removed, or upgraded dependencies from a lockfile diff.

    Args:
        file_path: Relative path to the lockfile.
        diff_content: Raw diff content for this lockfile.

    Returns:
        List of DependencyChange objects.
    """
    manager = detect_package_manager(file_path)

    if manager == "npm":
        return _parse_npm_diff(diff_content, file_path)
    elif manager in ("cargo", "poetry", "uv"):
        return _parse_toml_lock_diff(diff_content, file_path, manager=manager)
    elif manager == "yarn":
        return _parse_yarn_diff(diff_content, file_path)
    elif manager == "pnpm":
        return _parse_pnpm_diff(diff_content, file_path)
    elif manager == "pip":
        return _parse_requirements_diff(diff_content, file_path)

    return []


def format_lockfile_summary(changes: Sequence[DependencyChange]) -> str:
    """Format dependency changes into a high-signal markdown block for LLM consumption.

    Args:
        changes: Sequence of DependencyChange objects.

    Returns:
        Formatted summary markdown string.
    """
    if not changes:
        return ""

    lines = ["### Dependency Updates (Compacted from Lockfiles)"]
    for change in changes:
        lines.append(f"- {change.format_line()} ({change.manager}: `{change.file}`)")

    return "\n".join(lines)


def strip_lockfiles_and_inject_summary(diff_text: str) -> tuple[str, str, list[DependencyChange]]:
    """Remove lockfile noise from unified diff and produce a compacted summary.

    Args:
        diff_text: Full unified git diff.

    Returns:
        Tuple of (cleaned_diff, compacted_summary_markdown, list_of_changes).
    """
    chunks = split_diff_into_file_chunks(diff_text)
    if not chunks:
        return diff_text, "", []

    all_changes: list[DependencyChange] = []
    clean_chunks: list[str] = []

    for chunk in chunks:
        if is_lockfile(chunk.file_path):
            changes = compact_lockfile_diff(chunk.file_path, chunk.raw_chunk)
            all_changes.extend(changes)
        else:
            clean_chunks.append(chunk.raw_chunk)

    cleaned_diff = "".join(clean_chunks)
    summary = format_lockfile_summary(all_changes)

    return cleaned_diff, summary, all_changes


def process_diff_lockfiles(diff_text: str) -> tuple[str, str]:
    """Convenience wrapper: strip lockfiles and return (cleaned_diff, summary)."""
    cleaned_diff, summary, _ = strip_lockfiles_and_inject_summary(diff_text)
    return cleaned_diff, summary
