"""Integration test: GitWatcher.log_for_file against a real temp git repo."""
import shutil
import subprocess
import threading
from unittest.mock import MagicMock

import pytest

from flaiwheel.config import Config
from flaiwheel.watcher import GitWatcher


def _git_available() -> bool:
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(not _git_available(), reason="git not installed")


def _run(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args],
                   capture_output=True, check=True, timeout=20)


def _make_watcher(docs_path) -> GitWatcher:
    cfg = Config(docs_path=str(docs_path), git_repo_url="", git_auto_push=False)
    # Indexer + lock are not used by log_for_file; pass mocks
    return GitWatcher(
        cfg,
        indexer=MagicMock(),
        index_lock=threading.Lock(),
        health=None,
    )


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "docs"
    r.mkdir()
    _run(r, "init", "-b", "main")
    _run(r, "config", "user.email", "test@flaiwheel.local")
    _run(r, "config", "user.name", "test")
    f = r / "note.md"
    f.write_text("first\n")
    _run(r, "add", "note.md")
    _run(r, "commit", "-m", "Add note")
    f.write_text("first\nsecond\n")
    _run(r, "commit", "-am", "Append second line")
    return r


def test_log_for_file_returns_two_commits(repo):
    watcher = _make_watcher(repo)
    commits = watcher.log_for_file("note.md", limit=10)
    assert len(commits) == 2
    # Newest first
    assert commits[0]["subject"] == "Append second line"
    assert commits[1]["subject"] == "Add note"
    for c in commits:
        assert len(c["hash"]) == 40
        assert c["author"] == "test"
        assert "T" in c["date"]  # ISO 8601


def test_log_for_file_missing_returns_empty(repo):
    watcher = _make_watcher(repo)
    assert watcher.log_for_file("does-not-exist.md") == []


def test_log_for_file_not_a_git_repo(tmp_path):
    watcher = _make_watcher(tmp_path)
    assert watcher.log_for_file("anything.md") == []
