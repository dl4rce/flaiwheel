# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# Non-commercial use only. Commercial licensing: info@4rce.com

"""
Centralized health/status tracker – shared across indexer, watcher, web UI.
Thread-safe, no external dependencies.
"""
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path


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
            return self._data["last_index_ok"]
