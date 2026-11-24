"""Lockfile delta compactor: extracts concise dependency updates from massive lockfile diffs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Literal

from git_narrator.sanitizer import split_diff_into_file_chunks

LOCKFILE_FILENAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "cargo.lock",
    "poetry.lock",
    "uv.lock",
    "pdm.lock",
    "go.sum",
    "gemfile.lock",
    "composer.lock",
}

ChangeType = Literal["ADDED", "REMOVED", "UPGRADED", "DOWNGRADED"]

_IGNORED_NPM_KEYS = {
    "version", "resolved", "integrity", "dev", "requires", "dependencies",
    "peerDependencies", "devDependencies", "packages", "engines", "license",
    "funding", "optional", "peer", "bin", "name", "description", "homepage",
    "repository", "keywords", "author", "bugs", "main", "module", "types",
    "typings", "sideEffects", "os", "cpu", "scripts",
}

_IGNORED_PNPM_KEYS = {
    "lockfileVersion", "dev", "optional", "hasBin", "deprecated", "resolution",
    "integrity", "tarball", "engines", "os", "cpu", "libc", "requiresBuild",
    "transitivePeerDependencies",
}


@dataclass(frozen=True)
class DependencyChange:
    """Represents a discrete dependency delta extracted from a lockfile."""

    name: str
    change_type: ChangeType
    old_version: str | None
    new_version: str | None
    file: str
    manager: str

    def format_line(self) -> str:
        """Format into high-signal metadata string."""
        if self.change_type == "UPGRADED":
            return f"[UPGRADE] {self.name} {self.old_version} -> {self.new_version}"
        if self.change_type == "DOWNGRADED":
            return f"[DOWNGRADE] {self.name} {self.old_version} -> {self.new_version}"
        if self.change_type == "ADDED":
            ver = f" {self.new_version}" if self.new_version else ""
            return f"[ADD] {self.name}{ver}"
        if self.change_type == "REMOVED":
            ver = f" {self.old_version}" if self.old_version else ""
            return f"[REMOVE] {self.name}{ver}"
        return f"[{self.change_type}] {self.name}"


def is_lockfile(path: str | Path) -> bool:
    """Determine if a file path is a known package manager lockfile or requirements file."""
    filename = Path(path).name.lower()
    if filename in LOCKFILE_FILENAMES:
        return True
    return "requirements" in filename and filename.endswith(".txt")


def detect_package_manager(path: str | Path) -> str:
    """Identify package manager from lockfile path."""
    filename = Path(path).name.lower()
    mapping = {
        "package-lock.json": "npm",
        "pnpm-lock.yaml": "pnpm",
        "yarn.lock": "yarn",
        "bun.lock": "bun",
        "cargo.lock": "cargo",
        "poetry.lock": "poetry",
        "uv.lock": "uv",
        "pdm.lock": "pdm",
        "go.sum": "go",
        "gemfile.lock": "bundler",
        "composer.lock": "composer",
    }
    if filename in mapping:
        return mapping[filename]
    if "requirements" in filename:
        return "pip"
    return "unknown"


def _parse_semver_key(ver: str) -> tuple[tuple[int, ...], int, str]:
    """Build comparable version sort key supporting prereleases (1.0.0-alpha.1 < 1.0.0)."""
    clean = re.sub(r"^[vV]", "", ver.strip())
    core_part, _, pre_part = clean.partition("-")
    # Split build metadata if present
    core_part = core_part.split("+", 1)[0]
    nums: list[int] = []
    for seg in core_part.split("."):
        m = re.match(r"^(\d+)", seg)
        nums.append(int(m.group(1)) if m else 0)
    # Stable release (no prerelease) sorts ABOVE any prerelease (1 > 0)
    is_stable = 0 if pre_part else 1
    return (tuple(nums), is_stable, pre_part)


def _compare_versions(old_ver: str, new_ver: str) -> ChangeType:
    """Compare two version strings to determine UPGRADED vs DOWNGRADED."""
    try:
        old_nums, old_stable, old_pre = _parse_semver_key(old_ver)
        new_nums, new_stable, new_pre = _parse_semver_key(new_ver)

        max_len = max(len(old_nums), len(new_nums))
        o_pad = old_nums + (0,) * (max_len - len(old_nums))
        n_pad = new_nums + (0,) * (max_len - len(new_nums))

        if (n_pad, new_stable, new_pre) > (o_pad, old_stable, old_pre):
            return "UPGRADED"
        if (n_pad, new_stable, new_pre) < (o_pad, old_stable, old_pre):
            return "DOWNGRADED"
        return "UPGRADED"
    except (ValueError, TypeError):
        return "UPGRADED"


def _build_changes_from_maps(
    removed: dict[str, str],
    added: dict[str, str],
    file_path: str,
    manager: str,
) -> list[DependencyChange]:
    """Shared delta assembler turning {pkg: old_ver} and {pkg: new_ver} into DependencyChanges."""
    changes: list[DependencyChange] = []
    for name in sorted(set(removed) | set(added)):
        in_rem = name in removed
        in_add = name in added
        if in_rem and in_add:
            old_v, new_v = removed[name], added[name]
            if old_v != new_v:
                changes.append(
                    DependencyChange(
                        name=name,
                        change_type=_compare_versions(old_v, new_v),
                        old_version=old_v,
                        new_version=new_v,
                        file=file_path,
                        manager=manager,
                    )
                )
        elif in_add:
            changes.append(
                DependencyChange(
                    name=name,
                    change_type="ADDED",
                    old_version=None,
                    new_version=added[name],
                    file=file_path,
                    manager=manager,
                )
            )
        else:
            changes.append(
                DependencyChange(
                    name=name,
                    change_type="REMOVED",
                    old_version=removed[name],
                    new_version=None,
                    file=file_path,
                    manager=manager,
                )
            )
    return changes


def _parse_requirements_diff(diff_content: str, file_path: str) -> list[DependencyChange]:
    """Parse requirements.txt diffs."""
    req_pattern = re.compile(
        r"^([+-])\s*([a-zA-Z0-9_\-\.]+)\s*(?:==|>=|<=|~=|===)\s*([a-zA-Z0-9_\-\.\+]+)"
    )
    removed: dict[str, str] = {}
    added: dict[str, str] = {}

    for line in diff_content.splitlines():
        if not line or line.startswith(("---", "+++")):
            continue
        match = req_pattern.match(line)
        if match:
            sign, name, ver = match.groups()
            norm = name.lower()
            if sign == "-":
                removed[norm] = ver
            elif sign == "+":
                added[norm] = ver

    return _build_changes_from_maps(removed, added, file_path, "pip")


def _parse_toml_lock_diff(diff_content: str, file_path: str, manager: str) -> list[DependencyChange]:
    """Parse Cargo.lock, uv.lock, poetry.lock, and pdm.lock diffs."""
    removed: dict[str, str] = {}
    added: dict[str, str] = {}

    current_name: str | None = None
    old_ver: str | None = None
    new_ver: str | None = None

    def commit_package() -> None:
        nonlocal current_name, old_ver, new_ver
        if current_name:
            if old_ver and not new_ver:
                removed[current_name] = old_ver
            elif new_ver and not old_ver:
                added[current_name] = new_ver
            elif old_ver and new_ver and old_ver != new_ver:
                removed[current_name] = old_ver
                added[current_name] = new_ver
        current_name = None
        old_ver = None
        new_ver = None

    name_regex = re.compile(r'^[+-]?\s*name\s*=\s*"([^"]+)"')
    ver_regex = re.compile(r'^([+-])\s*version\s*=\s*"([^"]+)"')
    pkg_header_regex = re.compile(r'^[+-]?\s*\[\[package\]\]')

    for line in diff_content.splitlines():
        if pkg_header_regex.match(line):
            commit_package()
            continue

        n_match = name_regex.match(line)
        if n_match:
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
    return _build_changes_from_maps(removed, added, file_path, manager)


def _parse_npm_diff(diff_content: str, file_path: str, manager: str = "npm") -> list[DependencyChange]:
    """Parse package-lock.json and composer.lock style JSON diffs."""
    removed: dict[str, str] = {}
    added: dict[str, str] = {}

    pkg_entry_regex = re.compile(r'^\s*[+-]?\s*"((?:node_modules/)*([@a-zA-Z0-9_\-\./]+))":\s*\{?')
    ver_regex = re.compile(r'^\s*([+-])\s*"version":\s*"([^"]+)"')
    simple_dep_regex = re.compile(r'^\s*([+-])\s*"([@a-zA-Z0-9_\-\./]+)":\s*"([^"]+)",?\s*$')

    current_pkg: str | None = None

    for line in diff_content.splitlines():
        if line.startswith(("---", "+++")):
            continue

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
            clean_name = full_target.rsplit("node_modules/", 1)[-1]
            if clean_name and clean_name not in _IGNORED_NPM_KEYS and not clean_name.startswith("."):
                current_pkg = clean_name
            continue

        s_match = simple_dep_regex.match(line)
        if s_match:
            sign, name, ver = s_match.groups()
            clean_name = name.rsplit("node_modules/", 1)[-1]
            if clean_name and clean_name not in _IGNORED_NPM_KEYS and not clean_name.startswith("."):
                if sign == "-":
                    removed[clean_name] = ver
                elif sign == "+":
                    added[clean_name] = ver

    return _build_changes_from_maps(removed, added, file_path, manager)


def _parse_yarn_diff(diff_content: str, file_path: str) -> list[DependencyChange]:
    """Parse yarn.lock diffs."""
    header_regex = re.compile(r'^[+-]?\s*"?([@a-zA-Z0-9_\-\./]+)@[^:]+:\s*$')
    ver_regex = re.compile(r'^([+-])\s*version\s+"([^"]+)"')

    removed: dict[str, str] = {}
    added: dict[str, str] = {}
    current_pkg: str | None = None

    for line in diff_content.splitlines():
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

    return _build_changes_from_maps(removed, added, file_path, "yarn")


def _parse_pnpm_diff(diff_content: str, file_path: str) -> list[DependencyChange]:
    """Parse pnpm-lock.yaml diffs."""
    pkg_regex = re.compile(r"^[+-]?\s*['\"]?/?([@a-zA-Z0-9_\-\./]+)@([a-zA-Z0-9_\-\.\+]+)['\"]?:\s*$")
    simple_regex = re.compile(r"^([+-])\s*([@a-zA-Z0-9_\-\./]+):\s*([0-9]+\.[0-9]+[^\s,]*)$")

    removed: dict[str, str] = {}
    added: dict[str, str] = {}

    for line in diff_content.splitlines():
        if line.startswith(("---", "+++")):
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
            if name not in _IGNORED_PNPM_KEYS:
                if s_sign == "-":
                    removed[name] = ver
                elif s_sign == "+":
                    added[name] = ver

    return _build_changes_from_maps(removed, added, file_path, "pnpm")


def _parse_gosum_diff(diff_content: str, file_path: str) -> list[DependencyChange]:
    """Parse Go `go.sum` dependency deltas."""
    gosum_re = re.compile(r"^([+-])\s*([^\s]+)\s+(v[^\s/]+?)(?:/go\.mod)?\s+h1:")
    removed: dict[str, str] = {}
    added: dict[str, str] = {}

    for line in diff_content.splitlines():
        m = gosum_re.match(line)
        if m:
            sign, mod, ver = m.groups()
            if sign == "-":
                removed[mod] = ver
            elif sign == "+":
                added[mod] = ver

    return _build_changes_from_maps(removed, added, file_path, "go")


def compact_lockfile_diff(file_path: str, diff_content: str) -> list[DependencyChange]:
    """Extract added, removed, or upgraded dependencies from a lockfile diff."""
    manager = detect_package_manager(file_path)

    if manager in ("npm", "composer"):
        return _parse_npm_diff(diff_content, file_path, manager=manager)
    if manager in ("cargo", "poetry", "uv", "pdm"):
        return _parse_toml_lock_diff(diff_content, file_path, manager=manager)
    if manager == "yarn":
        return _parse_yarn_diff(diff_content, file_path)
    if manager == "pnpm":
        return _parse_pnpm_diff(diff_content, file_path)
    if manager == "pip":
        return _parse_requirements_diff(diff_content, file_path)
    if manager == "go":
        return _parse_gosum_diff(diff_content, file_path)

    return []


def format_lockfile_summary(changes: Sequence[DependencyChange]) -> str:
    """Format dependency changes into a high-signal markdown block for LLM consumption."""
    if not changes:
        return ""

    lines = ["### Dependency Updates (Compacted from Lockfiles)"]
    for change in changes:
        lines.append(f"- {change.format_line()} ({change.manager}: `{change.file}`)")

    return "\n".join(lines)


def strip_lockfiles_and_inject_summary(diff_text: str) -> tuple[str, str, list[DependencyChange]]:
    """Remove lockfile noise from unified diff and produce a compacted summary."""
    chunks = split_diff_into_file_chunks(diff_text)
    if not chunks:
        return diff_text, "", []

    all_changes: list[DependencyChange] = []
    clean_chunks: list[str] = []

    for chunk in chunks:
        if is_lockfile(chunk.file_path):
            all_changes.extend(compact_lockfile_diff(chunk.file_path, chunk.raw_chunk))
        else:
            clean_chunks.append(chunk.raw_chunk)

    return "".join(clean_chunks), format_lockfile_summary(all_changes), all_changes


def process_diff_lockfiles(diff_text: str) -> tuple[str, str]:
    """Convenience wrapper: strip lockfiles and return (cleaned_diff, summary)."""
    cleaned_diff, summary, _ = strip_lockfiles_and_inject_summary(diff_text)
    return cleaned_diff, summary
