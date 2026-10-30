"""Tests for lockfile module: delta compaction for npm, cargo, poetry, uv, yarn, pnpm, and pip."""

import pytest

from git_narrator.lockfile import (
    compact_lockfile_diff,
    format_lockfile_summary,
    is_lockfile,
    strip_lockfiles_and_inject_summary,
)


def test_is_lockfile():
    assert is_lockfile("package-lock.json") is True
    assert is_lockfile("sub/dir/package-lock.json") is True
    assert is_lockfile("Cargo.lock") is True
    assert is_lockfile("poetry.lock") is True
    assert is_lockfile("uv.lock") is True
    assert is_lockfile("pnpm-lock.yaml") is True
    assert is_lockfile("yarn.lock") is True
    assert is_lockfile("requirements.txt") is True
    assert is_lockfile("requirements-dev.txt") is True

    assert is_lockfile("Cargo.toml") is False
    assert is_lockfile("package.json") is False
    assert is_lockfile("main.py") is False


def test_package_lock_compaction():
    npm_diff = """
diff --git a/package-lock.json b/package-lock.json
index 111..222 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -10,12 +10,12 @@
     "node_modules/axios": {
-      "version": "1.2.0",
+      "version": "1.7.9",
       "resolved": "https://registry.npmjs.org/axios/-/axios-1.7.9.tgz"
     },
-    "node_modules/lodash": {
-      "version": "4.17.21"
-    },
+    "node_modules/dotenv": {
+      "version": "16.4.5"
+    }
"""
    changes = compact_lockfile_diff("package-lock.json", npm_diff)
    change_map = {c.name: c for c in changes}

    assert "axios" in change_map
    assert change_map["axios"].change_type == "UPGRADED"
    assert change_map["axios"].old_version == "1.2.0"
    assert change_map["axios"].new_version == "1.7.9"
    assert change_map["axios"].format_line() == "[UPGRADE] axios 1.2.0 -> 1.7.9"

    assert "lodash" in change_map
    assert change_map["lodash"].change_type == "REMOVED"
    assert change_map["lodash"].old_version == "4.17.21"

    assert "dotenv" in change_map
    assert change_map["dotenv"].change_type == "ADDED"
    assert change_map["dotenv"].new_version == "16.4.5"


def test_cargo_lock_compaction():
    cargo_diff = """
diff --git a/Cargo.lock b/Cargo.lock
index aaa..bbb 100644
--- a/Cargo.lock
+++ b/Cargo.lock
@@ -100,7 +100,7 @@
 [[package]]
 name = "serde"
-version = "1.0.196"
+version = "1.0.197"
 source = "registry+https://github.com/rust-lang/crates.io-index"

+[[package]]
+name = "tokio"
+version = "1.36.0"
+
-[[package]]
-name = "old-crate"
-version = "0.1.0"
"""
    changes = compact_lockfile_diff("Cargo.lock", cargo_diff)
    change_map = {c.name: c for c in changes}

    assert "serde" in change_map
    assert change_map["serde"].change_type == "UPGRADED"
    assert change_map["serde"].old_version == "1.0.196"
    assert change_map["serde"].new_version == "1.0.197"

    assert "tokio" in change_map
    assert change_map["tokio"].change_type == "ADDED"
    assert change_map["tokio"].new_version == "1.36.0"

    assert "old-crate" in change_map
    assert change_map["old-crate"].change_type == "REMOVED"
    assert change_map["old-crate"].old_version == "0.1.0"


def test_uv_and_poetry_lock_compaction():
    uv_diff = """
diff --git a/uv.lock b/uv.lock
--- a/uv.lock
+++ b/uv.lock
@@ -50,6 +50,6 @@
 [[package]]
 name = "httpx"
-version = "0.26.0"
+version = "0.27.0"
"""
    changes = compact_lockfile_diff("uv.lock", uv_diff)
    assert len(changes) == 1
    assert changes[0].name == "httpx"
    assert changes[0].change_type == "UPGRADED"
    assert changes[0].old_version == "0.26.0"
    assert changes[0].new_version == "0.27.0"


def test_requirements_txt_compaction():
    req_diff = """
diff --git a/requirements.txt b/requirements.txt
--- a/requirements.txt
+++ b/requirements.txt
@@ -1,4 +1,4 @@
-requests==2.31.0
+requests==2.32.3
+pydantic==2.7.0
-flask==2.0.1
"""
    changes = compact_lockfile_diff("requirements.txt", req_diff)
    change_map = {c.name: c for c in changes}

    assert change_map["requests"].change_type == "UPGRADED"
    assert change_map["requests"].old_version == "2.31.0"
    assert change_map["requests"].new_version == "2.32.3"

    assert change_map["pydantic"].change_type == "ADDED"
    assert change_map["pydantic"].new_version == "2.7.0"

    assert change_map["flask"].change_type == "REMOVED"
    assert change_map["flask"].old_version == "2.0.1"


def test_yarn_and_pnpm_compaction():
    yarn_diff = """
diff --git a/yarn.lock b/yarn.lock
--- a/yarn.lock
+++ b/yarn.lock
@@ -12,4 +12,4 @@
 axios@^1.2.0:
-  version "1.2.0"
+  version "1.7.9"
"""
    changes_yarn = compact_lockfile_diff("yarn.lock", yarn_diff)
    assert len(changes_yarn) == 1
    assert changes_yarn[0].name == "axios"
    assert changes_yarn[0].change_type == "UPGRADED"

    pnpm_diff = """
diff --git a/pnpm-lock.yaml b/pnpm-lock.yaml
--- a/pnpm-lock.yaml
+++ b/pnpm-lock.yaml
@@ -20,4 +20,4 @@
-  /axios@1.2.0:
+  /axios@1.7.9:
"""
    changes_pnpm = compact_lockfile_diff("pnpm-lock.yaml", pnpm_diff)
    assert len(changes_pnpm) == 1
    assert changes_pnpm[0].name == "axios"
    assert changes_pnpm[0].change_type == "UPGRADED"


def test_strip_lockfiles_and_inject_summary():
    diff_with_lockfile = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,1 +1,2 @@
+print("Hello")
diff --git a/package-lock.json b/package-lock.json
--- a/package-lock.json
+++ b/package-lock.json
@@ -5,4 +5,4 @@
   "node_modules/axios": {
-    "version": "1.2.0"
+    "version": "1.7.9"
   }
"""
    cleaned_diff, summary, changes = strip_lockfiles_and_inject_summary(diff_with_lockfile)

    # Cleaned diff should keep src/app.py but completely remove package-lock.json
    assert "src/app.py" in cleaned_diff
    assert "package-lock.json" not in cleaned_diff
    assert "node_modules/axios" not in cleaned_diff

    # Summary should contain high-signal metadata
    assert "### Dependency Updates (Compacted from Lockfiles)" in summary
    assert "[UPGRADE] axios 1.2.0 -> 1.7.9" in summary
    assert len(changes) == 1
