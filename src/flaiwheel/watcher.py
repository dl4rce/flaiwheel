# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# Non-commercial use only. Commercial licensing: info@4rce.com

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
from .indexer import DocsIndexer


class GitWatcher:
    def __init__(
        self,
        config: Config,
        indexer: DocsIndexer,
        index_lock: threading.Lock,
    ):
        self.config = config
        self.indexer = indexer
        self.index_lock = index_lock
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

        files = [
            line[3:].strip().strip('"')
            for line in changed_lines.splitlines()
            if line.strip()
        ]

        subprocess.run(
            ["git", "-C", str(git_dir), "add", "-A"],
            check=True, timeout=10,
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
            print(f"Warning: git push failed: {push_result.stderr}")
        else:
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
            pull_url = self._auth_url(self.config.git_repo_url)
            subprocess.run(
                ["git", "-C", str(git_dir), "pull", "--ff-only"],
                capture_output=True, timeout=30, check=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"Warning: Git pull failed: {e}")
            return False

        new_commit = self._get_current_commit()
        changed = old_commit != new_commit

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
                        result = self.indexer.index_all()
                    print(f"Reindex complete: {result}")
            except Exception as e:
                print(f"Warning: Git sync error: {e}")
