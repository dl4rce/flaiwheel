# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.md.

"""
Git Watcher – periodic pull + push + re-index on changes.
Runs as a background daemon thread.

Two-way sync:
  - PULL: fetch remote changes, reindex if new commits
  - PUSH: detect local changes (e.g. bugfix summaries), commit + push
"""
import subprocess
import time
import threading
from datetime import datetime
from pathlib import Path
from .config import Config
from .health import HealthTracker
from .indexer import DocsIndexer
from .quality import KnowledgeQualityChecker


class GitWatcher:
    def __init__(
        self,
        config: Config,
        indexer: DocsIndexer,
        index_lock: threading.Lock,
        health: HealthTracker | None = None,
        quality_checker: KnowledgeQualityChecker | None = None,
    ):
        self.config = config
        self.indexer = indexer
        self.index_lock = index_lock
        self.health = health
        self.quality_checker = quality_checker
        self._running = False
        self._thread: threading.Thread | None = None

    def clone_if_needed(self) -> bool:
        if not self.config.git_repo_url:
            return False

        docs = Path(self.config.docs_path)

        if (docs / ".git").exists():
            return False

        if docs.exists() and any(docs.iterdir()):
            print(f"Warning: {docs} is not empty, skipping git clone")
            return False

        print(f"Cloning {self.config.git_repo_url} -> {docs}")

        clone_url = self._auth_url(self.config.git_repo_url)

        subprocess.run(
            [
                "git", "clone",
                "--branch", self.config.git_branch,
                "--single-branch",
                "--depth", "1",
                clone_url,
                str(docs),
            ],
            check=True,
        )

        self._configure_git_identity()

        if self.config.git_docs_subpath:
            actual_path = docs / self.config.git_docs_subpath
            if actual_path.exists():
                print(f"Git subpath: {actual_path}")

        return True

    # ── Push (outgoing changes) ──────────────────────

    def push_pending(self):
        """Immediately push local changes if auto-push is enabled.
        Called after write operations (e.g. write_bugfix_summary)."""
        if not self.config.git_auto_push or not self.config.git_repo_url:
            return
        try:
            self._push_local_changes()
        except Exception as e:
            print(f"Warning: Auto-push failed: {e}")

    def _push_local_changes(self):
        """Detect uncommitted changes, commit + push them."""
        git_dir = self._find_git_dir()
        if not git_dir:
            return

        status = subprocess.run(
            ["git", "-C", str(git_dir), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        changed_lines = status.stdout.strip()
        if not changed_lines:
            return

        docs_path = Path(self.config.docs_path)
        try:
            rel_prefix = str(docs_path.relative_to(git_dir)) if git_dir != docs_path else ""
        except ValueError:
            rel_prefix = ""

        files = []
        for line in changed_lines.splitlines():
            if not line.strip():
                continue
            fpath = line[3:].strip().strip('"')
            if rel_prefix and not fpath.startswith(rel_prefix + "/") and fpath != rel_prefix:
                continue
            files.append(fpath)

        if not files:
            return

        for f in files:
            subprocess.run(
                ["git", "-C", str(git_dir), "add", "--", f],
                capture_output=True, timeout=10,
            )

        msg = self._build_commit_message(files)
        subprocess.run(
            ["git", "-C", str(git_dir), "commit", "-m", msg],
            capture_output=True, check=True, timeout=10,
        )

        push_result = subprocess.run(
            ["git", "-C", str(git_dir), "push"],
            capture_output=True, text=True, timeout=30,
        )
        if push_result.returncode != 0:
            if self.health:
                self.health.record_push(ok=False, error=push_result.stderr)
            print(f"Warning: git push failed: {push_result.stderr}")
        else:
            if self.health:
                self.health.record_push(ok=True)
            print(f"Pushed {len(files)} file(s) to remote")

    def _build_commit_message(self, files: list[str]) -> str:
        prefix = self.config.git_commit_prefix
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")

        if len(files) == 1:
            return f"{prefix}: update {files[0]} [{ts}]"

        bugfix_count = sum(1 for f in files if "bugfix" in f.lower())
        if bugfix_count == len(files):
            return f"{prefix}: add {bugfix_count} bugfix summary(ies) [{ts}]"

        return f"{prefix}: update {len(files)} file(s) [{ts}]"

    def _configure_git_identity(self):
        """Set git identity for auto-commits inside the docs repo."""
        git_dir = self._find_git_dir()
        if not git_dir:
            return
        subprocess.run(
            ["git", "-C", str(git_dir), "config", "user.name", "flaiwheel"],
            capture_output=True, timeout=5,
        )
        subprocess.run(
            ["git", "-C", str(git_dir), "config", "user.email", "bot@flaiwheel.local"],
            capture_output=True, timeout=5,
        )

    # ── Pull (incoming changes) ──────────────────────

    def _find_git_dir(self) -> Path | None:
        docs = Path(self.config.docs_path)
        git_dir = docs
        while git_dir != git_dir.parent:
            if (git_dir / ".git").exists():
                return git_dir
            git_dir = git_dir.parent
        return None

    def _get_current_commit(self) -> str:
        git_dir = self._find_git_dir()
        if not git_dir:
            return ""
        try:
            result = subprocess.run(
                ["git", "-C", str(git_dir), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def pull_and_check(self) -> bool:
        git_dir = self._find_git_dir()
        if not git_dir:
            return False

        # Unshallow if needed (legacy shallow clones can't fast-forward)
        shallow_file = git_dir / ".git" / "shallow"
        if shallow_file.exists():
            try:
                subprocess.run(
                    ["git", "-C", str(git_dir), "fetch", "--unshallow"],
                    capture_output=True, timeout=60,
                )
                print("Unshallowed git repo for proper pull support")
            except Exception:
                pass

        old_commit = self._get_current_commit()

        try:
            subprocess.run(
                ["git", "-C", str(git_dir), "pull", "--ff-only"],
                capture_output=True, timeout=30, check=True,
            )
        except subprocess.CalledProcessError as e:
            if self.health:
                self.health.record_pull(ok=False, error=str(e))
            print(f"Warning: Git pull failed: {e}")
            return False

        new_commit = self._get_current_commit()
        changed = old_commit != new_commit

        if self.health:
            self.health.record_pull(ok=True, changed=changed)
            self.health.record_git_info(git_dir, self.config.git_repo_url, self.config.git_branch)

        if changed:
            print(f"New commit: {old_commit[:8]} -> {new_commit[:8]}")

        return changed

    # ── Auth URL helper ──────────────────────────────

    def _auth_url(self, url: str) -> str:
        if self.config.git_token and "github.com" in url:
            return url.replace("https://", f"https://{self.config.git_token}@")
        return url

    # ── Background sync loop ─────────────────────────

    def start(self):
        if not self.config.git_repo_url:
            print("No git repo configured, watcher disabled")
            return

        if self.config.git_sync_interval <= 0:
            print("Git sync interval = 0, watcher disabled")
            return

        self.clone_if_needed()
        self._configure_git_identity()

        git_dir = self._find_git_dir()
        if git_dir and self.health:
            self.health.record_git_info(git_dir, self.config.git_repo_url, self.config.git_branch)

        self._running = True
        self._thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._thread.start()
        print(f"Git watcher started (every {self.config.git_sync_interval}s)")

    def stop(self):
        self._running = False

    def _sync_loop(self):
        while self._running:
            time.sleep(self.config.git_sync_interval)
            try:
                if self.config.git_auto_push:
                    self._push_local_changes()

                if self.pull_and_check():
                    print("Changes detected, reindexing...")
                    with self.index_lock:
                        result = self.indexer.index_all(quality_checker=self.quality_checker)
                    if self.health:
                        self.health.record_index(
                            ok=result.get("status") == "success",
                            chunks=result.get("chunks_upserted", 0),
                            files=result.get("files_indexed", 0),
                        )
                        self.health.record_skipped_files(result.get("quality_skipped", []))
                    if self.quality_checker and self.health:
                        try:
                            qr = self.quality_checker.check_all()
                            self.health.record_quality(
                                qr["score"], qr.get("critical", 0),
                                qr.get("warnings", 0), qr.get("info", 0),
                            )
                        except Exception as e:
                            print(f"Warning: Quality check failed: {e}")
                    print(f"Reindex complete: {result}")
            except Exception as e:
                if self.health:
                    self.health.record_pull(ok=False, error=str(e))
                print(f"Warning: Git sync error: {e}")
