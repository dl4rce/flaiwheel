# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.

"""
Git Watcher – periodic pull + push + re-index on changes.
Runs as a background daemon thread.

Two-way sync:
  - PULL: fetch remote changes, reindex if new commits
  - PUSH: detect local changes (e.g. bugfix summaries), commit + push
"""
import json
import subprocess
import tempfile
import time
import threading
from datetime import datetime
from pathlib import Path
from .config import Config
from .health import HealthTracker
from .indexer import DocsIndexer
from .logutil import diag
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
            diag(f"Warning: {docs} is not empty, skipping git clone")
            return False

        diag(f"Cloning {self.config.git_repo_url} -> {docs}")

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
                diag(f"Git subpath: {actual_path}")

        return True

    # ── Push (outgoing changes) ──────────────────────

    def push_pending(self) -> dict:
        """Immediately push local changes if auto-push is enabled.
        Called after write operations (e.g. write_bugfix_summary).

        Returns a structured result describing the actual outcome:
        ``{"status": "ok"|"noop"|"disabled"|"failed", "files": int,
        "error": str|None}``. Never derive success from configuration —
        callers must render ``status``.
        """
        if not self.config.git_auto_push or not self.config.git_repo_url:
            return {"status": "disabled", "files": 0, "error": None}
        try:
            return self._push_local_changes()
        except Exception as e:
            if self.health:
                self.health.record_push(ok=False, error=str(e))
            diag(f"Warning: Auto-push failed: {e}")
            return {"status": "failed", "files": 0, "error": str(e)}

    def _push_local_changes(self) -> dict:
        """Detect uncommitted changes, commit + push them."""
        git_dir = self._find_git_dir()
        if not git_dir:
            return {"status": "noop", "files": 0, "error": None}

        status = subprocess.run(
            ["git", "-C", str(git_dir), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        if not status.stdout.strip():
            # "Nothing to commit" is exactly where an already-diverged repo
            # hides: no push is attempted, so no push can fail, so nothing is
            # ever reported. Check the local/remote relationship instead.
            div = self.check_divergence(fetch=False)
            if self.health:
                self.health.record_divergence(div)
            return {"status": "noop", "files": 0, "error": None, "divergence": div}

        docs_path = Path(self.config.docs_path)
        try:
            rel_prefix = str(docs_path.relative_to(git_dir)) if git_dir != docs_path else ""
        except ValueError:
            rel_prefix = ""

        files = []
        # NB: iterate the RAW stdout. Porcelain lines are 'XY <path>', where X or
        # Y may be a space (' M' = modified in worktree). Stripping the whole
        # output first eats the leading space of the FIRST line only, so line[3:]
        # then truncates that filename's first character.
        for line in status.stdout.splitlines():
            if not line.strip():
                continue
            fpath = line[3:].strip()
            # Renames/copies are reported as 'old -> new'; stage the new path.
            if line[:2].strip().startswith(("R", "C")) and " -> " in fpath:
                fpath = fpath.split(" -> ", 1)[1]
            fpath = fpath.strip('"')
            if rel_prefix and not fpath.startswith(rel_prefix + "/") and fpath != rel_prefix:
                continue
            files.append(fpath)

        if not files:
            return {"status": "noop", "files": 0, "error": None}

        for f in files:
            subprocess.run(
                ["git", "-C", str(git_dir), "add", "--", f],
                capture_output=True, timeout=10,
            )

        scan = self._scan_staged_for_secrets(git_dir)
        if scan["status"] == "blocked":
            err = (
                f"gitleaks blocked the commit: {len(scan['findings'])} potential "
                f"secret(s) in {', '.join(sorted({f['file'] for f in scan['findings']}))}. "
                "Redact them, or allowlist in .gitleaks.toml, "
                "or set MCP_GITLEAKS_MODE=warn."
            )
            if self.health:
                self.health.record_push(ok=False, error=err)
            diag(f"Warning: {err}")
            return {
                "status": "blocked", "files": len(files),
                "error": err, "findings": scan["findings"],
            }

        msg = self._build_commit_message(files)
        commit_result = subprocess.run(
            ["git", "-C", str(git_dir), "commit", "-m", msg],
            capture_output=True, text=True, timeout=10,
        )
        if commit_result.returncode != 0:
            err = (commit_result.stderr or commit_result.stdout).strip()
            if self.health:
                self.health.record_push(ok=False, error=err)
            diag(f"Warning: git commit failed: {err}")
            return {"status": "failed", "files": len(files), "error": err}

        push_result = subprocess.run(
            ["git", "-C", str(git_dir), "push"],
            capture_output=True, text=True, timeout=30,
        )
        if push_result.returncode != 0:
            err = push_result.stderr.strip()
            if self.health:
                self.health.record_push(ok=False, error=err)
            diag(f"Warning: git push failed: {err}")
            # A rejected push is the classic symptom of a diverged clone; say so
            # instead of leaving the caller to guess from the git error.
            div = self.check_divergence(fetch=False)
            if self.health:
                self.health.record_divergence(div)
            return {"status": "failed", "files": len(files), "error": err,
                    "divergence": div}

        if self.health:
            self.health.record_push(ok=True)
        # The push exited 0 — confirm it actually landed. No fetch needed: the
        # push just updated the remote-tracking ref.
        div = self.check_divergence(fetch=False)
        if self.health:
            self.health.record_divergence(div)
        diag(f"Pushed {len(files)} file(s) to remote")
        return {
            "status": "ok", "files": len(files), "error": None,
            "scan": scan["status"], "findings": scan["findings"],
            "divergence": div,
        }

    # ── Divergence detection ─────────────────────────

    def check_divergence(self, fetch: bool = True) -> dict:
        """Compare the local branch against its upstream.

        A push that is never *attempted* cannot report a failure, and a clone
        whose history was rewritten upstream stops synchronising while happily
        accepting writes. Both states are invisible to push reporting — this is
        how 325 documents lived only inside a Docker volume for 2.5 months.

        Returns ``{"status": ..., "ahead": int, "behind": int, "error": str|None}``
        where status is one of:
          ``synced``      — in step with the remote
          ``ahead``       — local commits not on the remote (unpushed knowledge)
          ``behind``      — remote commits not pulled yet (benign, next pull fixes)
          ``diverged``    — BOTH: histories have split, pushes will be rejected
          ``no-upstream`` — branch tracks nothing; nothing is being backed up
          ``unknown``     — could not determine (no repo, git error)
        """
        git_dir = self._find_git_dir()
        if not git_dir:
            return {"status": "unknown", "ahead": 0, "behind": 0,
                    "error": "no git repository"}

        if fetch:
            # Counts are meaningless against a stale remote ref.
            fetched = subprocess.run(
                ["git", "-C", str(git_dir), "fetch", "--quiet"],
                capture_output=True, text=True, timeout=30,
            )
            if fetched.returncode != 0:
                return {"status": "unknown", "ahead": 0, "behind": 0,
                        "error": (fetched.stderr or "git fetch failed").strip()}

        counts = subprocess.run(
            ["git", "-C", str(git_dir), "rev-list", "--left-right", "--count",
             "@{u}...HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        if counts.returncode != 0:
            err = (counts.stderr or "").strip()
            # No upstream is a distinct, actionable state: writes are landing
            # in a repo that pushes nowhere.
            if "no upstream" in err.lower() or "@{u}" in err:
                return {"status": "no-upstream", "ahead": 0, "behind": 0,
                        "error": err}
            return {"status": "unknown", "ahead": 0, "behind": 0, "error": err}

        try:
            behind_s, ahead_s = counts.stdout.split()
            behind, ahead = int(behind_s), int(ahead_s)
        except ValueError:
            return {"status": "unknown", "ahead": 0, "behind": 0,
                    "error": f"unparseable rev-list output: {counts.stdout!r}"}

        if ahead and behind:
            status = "diverged"
        elif ahead:
            status = "ahead"
        elif behind:
            status = "behind"
        else:
            status = "synced"

        return {"status": status, "ahead": ahead, "behind": behind, "error": None}

    @staticmethod
    def describe_divergence(div: dict) -> str | None:
        """Human-readable warning for a divergence result, or None if fine.

        Returned to agents alongside write results — a warning nobody reads
        does not exist.
        """
        status = div.get("status")
        ahead, behind = div.get("ahead", 0), div.get("behind", 0)
        if status == "diverged":
            return (
                f"WARNING: local knowledge repo has DIVERGED from origin "
                f"({ahead} local commit(s) not on remote, {behind} remote commit(s) "
                "not local). Pushes will be rejected and new knowledge is NOT "
                "being backed up. This usually follows a force-push/history "
                "rewrite upstream; the local clone must be reset onto it."
            )
        if status == "ahead":
            return (
                f"WARNING: {ahead} commit(s) exist only in the local knowledge "
                "repo and are NOT on the remote."
            )
        if status == "no-upstream":
            return (
                "WARNING: the knowledge repo branch tracks no upstream — "
                "nothing written here is being pushed anywhere."
            )
        return None

    # ── Secret scanning ──────────────────────────────

    def _run_gitleaks_on_staged(self, git_dir: Path) -> list[dict]:
        """Materialise the staged blobs to a temp dir and run ``gitleaks dir``.

        Deliberately NOT ``gitleaks git --staged``: that mode reports
        "0 commits scanned" and finds nothing on freshly-staged files, which
        would turn this gate into a permanent silent pass — the exact class of
        bug this whole change exists to remove. Materialising the staged
        content and scanning it as a directory is deterministic.

        Raises ``FileNotFoundError`` when gitleaks is not installed.
        """
        names = subprocess.run(
            ["git", "-C", str(git_dir), "diff", "--cached",
             "--name-only", "--diff-filter=ACM", "-z"],
            capture_output=True, text=True, timeout=30, check=True,
        )
        staged = [n for n in names.stdout.split("\0") if n]
        if not staged:
            return []

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for rel in staged:
                blob = subprocess.run(
                    ["git", "-C", str(git_dir), "show", f":{rel}"],
                    capture_output=True, timeout=30,
                )
                if blob.returncode != 0:
                    continue
                dest = tmp_path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(blob.stdout)

            cmd = ["gitleaks", "dir", str(tmp_path), "--no-banner", "--redact",
                   "--report-format", "json", "--report-path", "-"]
            cfg_file = git_dir / ".gitleaks.toml"
            if cfg_file.exists():
                cmd += ["--config", str(cfg_file)]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                return []
            try:
                raw = json.loads(result.stdout or "[]")
            except json.JSONDecodeError:
                raise RuntimeError(
                    result.stderr.strip() or "unparsable gitleaks output"
                )
            # Report repo-relative paths, not the scratch directory
            for f in raw:
                try:
                    f["File"] = str(Path(f.get("File", "")).relative_to(tmp_path))
                except ValueError:
                    pass
            return raw

    def _scan_staged_for_secrets(self, git_dir: Path) -> dict:
        """Scan the staged changes with gitleaks before committing.

        Commits here are machine-generated and never human-reviewed, so this
        is the only gate on the write path. Honours a ``.gitleaks.toml`` in
        the knowledge repo for allowlisting.

        Returns ``{"status": "clean"|"blocked"|"warned"|"off"|"unavailable",
        "findings": [...]}``. An unavailable scanner is reported, never
        silently skipped.
        """
        mode = self.config.gitleaks_mode
        if mode == "off":
            return {"status": "off", "findings": []}

        try:
            raw = self._run_gitleaks_on_staged(git_dir)
        except FileNotFoundError:
            diag("Warning: gitleaks not installed — staged changes were NOT scanned")
            return {"status": "unavailable", "findings": [],
                    "error": "gitleaks binary not found"}
        except Exception as e:
            diag(f"Warning: gitleaks scan failed: {e}")
            return {"status": "unavailable", "findings": [], "error": str(e)}

        findings = [
            {
                "file": f.get("File", ""),
                "line": f.get("StartLine"),
                "rule": f.get("RuleID", ""),
                "description": f.get("Description", ""),
            }
            for f in raw
        ]
        if not findings:
            return {"status": "clean", "findings": []}

        if mode == "warn":
            diag(f"Warning: gitleaks found {len(findings)} potential secret(s), committing anyway (mode=warn)")
            return {"status": "warned", "findings": findings}
        return {"status": "blocked", "findings": findings}

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

    def log_for_file(self, rel_path: str, limit: int = 50) -> list[dict]:
        """Return git history for a single file inside the docs repo.

        Read-only — used by the ``timeline()`` MCP tool. Each entry has
        keys ``hash``, ``author``, ``date`` (ISO 8601), ``subject``.
        Returns ``[]`` when the docs path is not a git repo or the file
        has no history.
        """
        git_dir = self._find_git_dir()
        if not git_dir:
            return []
        sep = "\x1f"
        fmt = sep.join(["%H", "%an", "%aI", "%s"])
        try:
            result = subprocess.run(
                ["git", "-C", str(git_dir), "log",
                 f"-n{int(limit)}", f"--format={fmt}", "--", rel_path],
                capture_output=True, text=True, timeout=15,
            )
        except Exception:
            return []
        out: list[dict] = []
        for line in result.stdout.splitlines():
            parts = line.split(sep)
            if len(parts) != 4:
                continue
            out.append({
                "hash": parts[0],
                "author": parts[1],
                "date": parts[2],
                "subject": parts[3],
            })
        return out

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
                diag("Unshallowed git repo for proper pull support")
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
                # --ff-only refuses precisely when histories have split; record
                # WHY the pull failed, not just that it did.
                self.health.record_divergence(self.check_divergence(fetch=False))
            diag(f"Warning: Git pull failed: {e}")
            return False

        new_commit = self._get_current_commit()
        changed = old_commit != new_commit

        if self.health:
            self.health.record_pull(ok=True, changed=changed)
            self.health.record_divergence(self.check_divergence(fetch=False))
            self.health.record_git_info(git_dir, self.config.git_repo_url, self.config.git_branch)

        if changed:
            diag(f"New commit: {old_commit[:8]} -> {new_commit[:8]}")

        return changed

    # ── Auth URL helper ──────────────────────────────

    def _auth_url(self, url: str) -> str:
        if self.config.git_token and "github.com" in url:
            return url.replace("https://", f"https://{self.config.git_token}@")
        return url

    # ── Background sync loop ─────────────────────────

    def start(self):
        if not self.config.git_repo_url:
            diag("No git repo configured, watcher disabled")
            return

        if self.config.git_sync_interval <= 0:
            diag("Git sync interval = 0, watcher disabled")
            return

        self.clone_if_needed()
        self._configure_git_identity()

        git_dir = self._find_git_dir()
        if git_dir and self.health:
            self.health.record_git_info(git_dir, self.config.git_repo_url, self.config.git_branch)

        self._running = True
        self._thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._thread.start()
        diag(f"Git watcher started (every {self.config.git_sync_interval}s)")

    def stop(self):
        self._running = False

    def _sync_loop(self):
        while self._running:
            time.sleep(self.config.git_sync_interval)
            try:
                if self.config.git_auto_push:
                    self._push_local_changes()

                if self.pull_and_check():
                    diag("Changes detected, reindexing...")
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
                            diag(f"Warning: Quality check failed: {e}")
                    diag(f"Reindex complete: {result}")
            except Exception as e:
                if self.health:
                    self.health.record_pull(ok=False, error=str(e))
                diag(f"Warning: Git sync error: {e}")
