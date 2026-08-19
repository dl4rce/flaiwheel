"""Divergence detection against real temp git repos.

Push reporting can only report on pushes that are ATTEMPTED. A clone whose
history was rewritten upstream, or one that tracks no upstream at all, never
attempts anything — every metric stays green while knowledge accumulates in a
Docker volume and reaches no remote. That is the blind spot these tests cover.
"""
import shutil
import subprocess
import threading
from unittest.mock import MagicMock

import pytest

from flaiwheel.config import Config
from flaiwheel.health import HealthTracker
from flaiwheel.watcher import GitWatcher

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _run(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args],
                   capture_output=True, check=True, timeout=20)


def _make_watcher(docs_path, health=None, **kw) -> GitWatcher:
    kw.setdefault("git_auto_push", True)
    kw.setdefault("gitleaks_mode", "off")
    cfg = Config(docs_path=str(docs_path),
                 git_repo_url="https://example.invalid/repo.git", **kw)
    return GitWatcher(cfg, indexer=MagicMock(),
                      index_lock=threading.Lock(), health=health)


@pytest.fixture
def repo(tmp_path):
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


def _commit(path, name, body="x\n"):
    (path / name).write_text(body)
    _run(path, "add", name)
    _run(path, "commit", "-m", f"add {name}")


class TestCheckDivergence:
    def test_synced_repo(self, repo):
        assert _make_watcher(repo).check_divergence()["status"] == "synced"

    def test_local_commit_reports_ahead(self, repo):
        _commit(repo, "local.md")
        div = _make_watcher(repo).check_divergence()
        assert div["status"] == "ahead"
        assert div["ahead"] == 1 and div["behind"] == 0

    def test_remote_commit_reports_behind(self, repo, tmp_path):
        other = tmp_path / "other"
        _run(tmp_path, "clone", str(tmp_path / "remote.git"), str(other))
        _run(other, "config", "user.email", "o@flaiwheel.local")
        _run(other, "config", "user.name", "o")
        _commit(other, "remote.md")
        _run(other, "push", "origin", "main")

        div = _make_watcher(repo).check_divergence()
        assert div["status"] == "behind"
        assert div["behind"] == 1 and div["ahead"] == 0

    def test_rewritten_upstream_reports_diverged(self, repo, tmp_path):
        """The real-world trigger: someone force-pushes a rewritten history
        (a secret purge, a squash) and every clone silently stops syncing."""
        other = tmp_path / "other"
        _run(tmp_path, "clone", str(tmp_path / "remote.git"), str(other))
        _run(other, "config", "user.email", "o@flaiwheel.local")
        _run(other, "config", "user.name", "o")
        _commit(other, "rewritten.md")
        _run(other, "push", "--force", "origin", "main")

        _commit(repo, "local.md")

        div = _make_watcher(repo).check_divergence()
        assert div["status"] == "diverged"
        assert div["ahead"] >= 1 and div["behind"] >= 1

    def test_no_upstream_is_its_own_state(self, tmp_path):
        r = tmp_path / "solo"
        r.mkdir()
        _run(r, "init", "-b", "main")
        _run(r, "config", "user.email", "t@flaiwheel.local")
        _run(r, "config", "user.name", "t")
        _commit(r, "note.md")

        div = _make_watcher(r).check_divergence(fetch=False)
        assert div["status"] == "no-upstream"

    def test_unknown_when_not_a_repo(self, tmp_path):
        assert _make_watcher(tmp_path / "nope").check_divergence()["status"] == "unknown"


class TestPushSurfacesDivergence:
    def test_noop_still_reports_divergence(self, repo, tmp_path):
        """The critical case: nothing to commit, so no push is attempted and no
        push can fail — yet the repo is disconnected from its remote."""
        other = tmp_path / "other"
        _run(tmp_path, "clone", str(tmp_path / "remote.git"), str(other))
        _run(other, "config", "user.email", "o@flaiwheel.local")
        _run(other, "config", "user.name", "o")
        _commit(other, "rewritten.md")
        _run(other, "push", "--force", "origin", "main")
        _commit(repo, "local.md")
        _run(repo, "fetch")

        result = _make_watcher(repo).push_pending()
        assert result["status"] == "noop"
        assert result["divergence"]["status"] == "diverged"

    def test_successful_push_reports_synced(self, repo):
        (repo / "new.md").write_text("hello\n")
        result = _make_watcher(repo).push_pending()
        assert result["status"] == "ok"
        assert result["divergence"]["status"] == "synced"


class TestHealthIntegration:
    def test_divergence_degrades_health(self, repo, tmp_path):
        health = HealthTracker()
        health.record_index(ok=True, chunks=10)
        assert health.is_healthy is True

        other = tmp_path / "other"
        _run(tmp_path, "clone", str(tmp_path / "remote.git"), str(other))
        _run(other, "config", "user.email", "o@flaiwheel.local")
        _run(other, "config", "user.name", "o")
        _commit(other, "rewritten.md")
        _run(other, "push", "--force", "origin", "main")
        _commit(repo, "local.md")

        w = _make_watcher(repo, health=health)
        health.record_divergence(w.check_divergence())

        assert health.status["divergence_status"] == "diverged"
        assert health.is_healthy is False

    def test_behind_is_not_unhealthy(self):
        """Being behind is the normal state between two pulls — not a fault."""
        health = HealthTracker()
        health.record_index(ok=True, chunks=10)
        health.record_divergence({"status": "behind", "ahead": 0, "behind": 4})
        assert health.is_healthy is True

    def test_unknown_does_not_erase_a_real_verdict(self):
        """A transient fetch failure must not clear a diverged state."""
        health = HealthTracker()
        health.record_index(ok=True, chunks=10)
        health.record_divergence({"status": "diverged", "ahead": 1, "behind": 1})
        health.record_divergence({"status": "unknown", "ahead": 0, "behind": 0})
        assert health.status["divergence_status"] == "diverged"
        assert health.is_healthy is False

    def test_recovery_restores_health(self):
        health = HealthTracker()
        health.record_index(ok=True, chunks=10)
        health.record_divergence({"status": "diverged", "ahead": 1, "behind": 1})
        health.record_divergence({"status": "synced", "ahead": 0, "behind": 0})
        assert health.is_healthy is True


class TestDescribeDivergence:
    @pytest.mark.parametrize("status", ["synced", "behind", "unknown"])
    def test_benign_states_produce_no_warning(self, status):
        assert GitWatcher.describe_divergence({"status": status}) is None

    @pytest.mark.parametrize("status", ["diverged", "ahead", "no-upstream"])
    def test_actionable_states_warn(self, status):
        msg = GitWatcher.describe_divergence({"status": status, "ahead": 2, "behind": 3})
        assert msg and "WARNING" in msg

    def test_empty_dict_is_safe(self):
        assert GitWatcher.describe_divergence({}) is None
