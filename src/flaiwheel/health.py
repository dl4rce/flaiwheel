# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.

"""
Centralized health/status tracker – shared across indexer, watcher, web UI.
Thread-safe, no external dependencies.
"""
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

# Consecutive failed pushes before /health degrades. A single failure is often
# transient (network, a momentary lock); a sustained streak means knowledge is
# accumulating locally and reaching no remote — the 2026-08-19 failure mode.
PUSH_FAILURE_THRESHOLD = 3

# Divergence states that mean knowledge is NOT reaching the remote. "behind" is
# absent on purpose: it is the normal state between two pulls.
UNHEALTHY_DIVERGENCE = ("diverged", "ahead", "no-upstream")


class HealthTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {
            "last_index_at": None,
            "last_index_ok": False,
            "last_index_chunks": 0,
            "last_index_files": 0,
            "last_index_error": None,

            "last_pull_at": None,
            "last_pull_ok": False,
            "last_pull_changed": False,
            "last_pull_error": None,

            "last_push_at": None,
            "last_push_ok": False,
            "last_push_error": None,
            # last_push_ok is a single boolean that the next attempt overwrites,
            # so one blip and a repo that has been failing for weeks look
            # identical. Count the streak so persistent failure can escalate.
            "push_failures_consecutive": 0,

            # A repo can be perfectly "healthy" by every push/index metric and
            # still be silently disconnected from its remote — no push is
            # attempted when there is nothing to commit, so no push can fail.
            "divergence_status": None,
            "commits_ahead": 0,
            "commits_behind": 0,
            "last_divergence_at": None,

            "git_commit": None,
            "git_branch": None,
            "git_repo_url": None,
            "started_at": datetime.now(timezone.utc).isoformat(),

            "searches_total": 0,
            "searches_hits": 0,
            "searches_misses": 0,
            "searches_by_tool": {
                "search_docs": 0,
                "search_bugfixes": 0,
                "search_by_type": 0,
            },
            "last_search_at": None,

            "quality_score": None,
            "quality_issues_critical": 0,
            "quality_issues_warnings": 0,
            "quality_issues_info": 0,

            "skipped_files": [],

            "migration_status": None,
        }

    def record_index(self, ok: bool, chunks: int = 0, files: int = 0, error: str | None = None):
        with self._lock:
            self._data["last_index_at"] = datetime.now(timezone.utc).isoformat()
            self._data["last_index_ok"] = ok
            self._data["last_index_chunks"] = chunks
            self._data["last_index_files"] = files
            self._data["last_index_error"] = error

    def record_pull(self, ok: bool, changed: bool = False, error: str | None = None):
        with self._lock:
            self._data["last_pull_at"] = datetime.now(timezone.utc).isoformat()
            self._data["last_pull_ok"] = ok
            self._data["last_pull_changed"] = changed
            self._data["last_pull_error"] = error

    def record_push(self, ok: bool, error: str | None = None):
        with self._lock:
            self._data["last_push_at"] = datetime.now(timezone.utc).isoformat()
            self._data["last_push_ok"] = ok
            self._data["last_push_error"] = error
            if ok:
                self._data["push_failures_consecutive"] = 0
            else:
                self._data["push_failures_consecutive"] += 1

    def record_divergence(self, divergence: dict):
        """Store the result of ``GitWatcher.check_divergence()``.

        ``unknown`` is deliberately not persisted as a state: a transient fetch
        failure must not erase a real ``diverged`` verdict.
        """
        status = divergence.get("status")
        if status == "unknown":
            return
        with self._lock:
            self._data["divergence_status"] = status
            self._data["commits_ahead"] = divergence.get("ahead", 0)
            self._data["commits_behind"] = divergence.get("behind", 0)
            self._data["last_divergence_at"] = datetime.now(timezone.utc).isoformat()

    def record_search(self, tool: str, hit: bool):
        with self._lock:
            self._data["searches_total"] += 1
            if hit:
                self._data["searches_hits"] += 1
            else:
                self._data["searches_misses"] += 1
            by_tool = self._data["searches_by_tool"]
            if tool in by_tool:
                by_tool[tool] += 1
            self._data["last_search_at"] = datetime.now(timezone.utc).isoformat()

    def record_skipped_files(self, skipped: list[dict]):
        with self._lock:
            self._data["skipped_files"] = skipped

    def record_quality(self, score: int, critical: int = 0, warnings: int = 0, info: int = 0):
        with self._lock:
            self._data["quality_score"] = score
            self._data["quality_issues_critical"] = critical
            self._data["quality_issues_warnings"] = warnings
            self._data["quality_issues_info"] = info

    def record_migration(self, status_dict: dict | None):
        with self._lock:
            self._data["migration_status"] = status_dict

    def record_git_info(self, git_dir: Path, repo_url: str = "", branch: str = ""):
        with self._lock:
            self._data["git_repo_url"] = repo_url
            self._data["git_branch"] = branch
        try:
            result = subprocess.run(
                ["git", "-C", str(git_dir), "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            with self._lock:
                self._data["git_commit"] = result.stdout.strip() or None
        except Exception:
            pass

    @property
    def status(self) -> dict:
        with self._lock:
            return dict(self._data)

    @property
    def is_healthy(self) -> bool:
        with self._lock:
            if self._data["push_failures_consecutive"] >= PUSH_FAILURE_THRESHOLD:
                return False
            if self._data["divergence_status"] in UNHEALTHY_DIVERGENCE:
                return False
            return self._data["last_index_ok"]
