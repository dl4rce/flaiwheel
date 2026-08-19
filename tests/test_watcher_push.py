"""GitWatcher push reporting + gitleaks gate against a real temp git repo.

Regression cover for the 2026-08-19 incident where push_pending() returned
None, swallowed every exception, and the MCP layer reported success derived
from configuration rather than outcome.
"""
import shutil
import subprocess
import threading
from unittest.mock import MagicMock

import pytest

from flaiwheel.config import Config
from flaiwheel.health import HealthTracker
from flaiwheel.watcher import GitWatcher


def _git_available() -> bool:
    return shutil.which("git") is not None


def _gitleaks_available() -> bool:
    return shutil.which("gitleaks") is not None


pytestmark = pytest.mark.skipif(not _git_available(), reason="git not installed")

# A syntactically valid but entirely fictitious GitHub PAT, assembled at runtime
# so this test file does not itself trip secret scanners in CI.
FAKE_PAT = "ghp_" + "a1B2c3D4e5F6g7H8i9J0kLmNoPqRsTuVwXyZ12"


def _run(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args],
                   capture_output=True, check=True, timeout=20)


def _make_watcher(docs_path, health=None, **cfg_kwargs) -> GitWatcher:
    cfg_kwargs.setdefault("git_auto_push", True)
    cfg = Config(
        docs_path=str(docs_path),
        git_repo_url="https://example.invalid/repo.git",
        **cfg_kwargs,
    )
    return GitWatcher(
        cfg,
        indexer=MagicMock(),
        index_lock=threading.Lock(),
        health=health,
    )


@pytest.fixture
def repo(tmp_path):
    """Local repo with a bare 'remote' so push actually succeeds."""
    remote = tmp_path / "remote.git"
    _run(tmp_path, "init", "--bare", "-b", "main", str(remote))

    r = tmp_path / "docs"
    r.mkdir()
    _run(r, "init", "-b", "main")
    _run(r, "config", "user.email", "test@flaiwheel.local")
    _run(r, "config", "user.name", "test")
    _run(r, "remote", "add", "origin", str(remote))
    (r / "note.md").write_text("first\n")
    _run(r, "add", "note.md")
    _run(r, "commit", "-m", "Add note")
    _run(r, "push", "-u", "origin", "main")
    return r


def test_push_disabled_reports_disabled(repo):
    w = _make_watcher(repo, git_auto_push=False)
    assert w.push_pending()["status"] == "disabled"


def test_push_noop_when_nothing_changed(repo):
    w = _make_watcher(repo, gitleaks_mode="off")
    assert w.push_pending()["status"] == "noop"


def test_push_ok_reports_files(repo):
    health = HealthTracker()
    w = _make_watcher(repo, health=health, gitleaks_mode="off")
    (repo / "new.md").write_text("content\n")

    result = w.push_pending()

    assert result["status"] == "ok"
    assert result["files"] == 1
    assert result["error"] is None
    assert health.status["last_push_ok"] is True


def test_push_failure_is_reported_not_swallowed(repo):
    """The core regression: a rejected push must surface as failed."""
    health = HealthTracker()
    w = _make_watcher(repo, health=health, gitleaks_mode="off")
    _run(repo, "remote", "set-url", "origin", "/nonexistent/path/repo.git")
    (repo / "new.md").write_text("content\n")

    result = w.push_pending()

    assert result["status"] == "failed"
    assert result["error"]
    assert health.status["last_push_ok"] is False
    assert health.status["last_push_error"]


@pytest.mark.skipif(not _gitleaks_available(), reason="gitleaks not installed")
def test_gitleaks_blocks_commit_on_secret(repo):
    health = HealthTracker()
    w = _make_watcher(repo, health=health, gitleaks_mode="block")
    (repo / "nested").mkdir()
    (repo / "nested" / "leak.md").write_text(f"export GITHUB_TOKEN={FAKE_PAT}\n")

    result = w.push_pending()

    assert result["status"] == "blocked"
    assert result["findings"]
    # Paths are repo-relative, not scratch-directory paths
    assert any(f["file"] == "nested/leak.md" for f in result["findings"])
    assert health.status["last_push_ok"] is False
    # Nothing was committed
    log = subprocess.run(["git", "-C", str(repo), "log", "--oneline"],
                         capture_output=True, text=True, timeout=10)
    assert log.stdout.strip().count("\n") == 0


@pytest.mark.skipif(not _gitleaks_available(), reason="gitleaks not installed")
def test_gitleaks_warn_mode_pushes_anyway(repo):
    w = _make_watcher(repo, gitleaks_mode="warn")
    (repo / "leak.md").write_text(f"export GITHUB_TOKEN={FAKE_PAT}\n")

    result = w.push_pending()

    assert result["status"] == "ok"
    assert result["scan"] == "warned"
    assert result["findings"]


@pytest.mark.skipif(not _gitleaks_available(), reason="gitleaks not installed")
def test_gitleaks_clean_content_passes(repo):
    w = _make_watcher(repo, gitleaks_mode="block")
    (repo / "clean.md").write_text("# Notes\n\nNothing secret here.\n")

    result = w.push_pending()

    assert result["status"] == "ok"
    assert result["scan"] == "clean"


def test_missing_gitleaks_is_reported_not_silent(repo, monkeypatch):
    """An unavailable scanner must be visible, never a silent pass."""
    w = _make_watcher(repo, gitleaks_mode="block")
    monkeypatch.setattr(
        "flaiwheel.watcher.subprocess.run",
        MagicMock(side_effect=FileNotFoundError("gitleaks")),
    )
    scan = w._scan_staged_for_secrets(repo)
    assert scan["status"] == "unavailable"
    assert scan["error"]
