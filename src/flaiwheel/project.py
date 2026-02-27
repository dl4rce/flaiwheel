# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.md.

"""
Multi-project support – one Flaiwheel instance serves N knowledge repos.

Each project gets its own ChromaDB collection, git watcher, index lock,
health tracker, and quality checker. They share one embedding model and
one MCP/Web endpoint.
"""
import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from .config import Config
from .health import HealthTracker
from .indexer import DocsIndexer
from .quality import KnowledgeQualityChecker
from .watcher import GitWatcher

PROJECTS_FILE = Path("/data/projects.json")
LEGACY_COLLECTION = "project_docs"


def _slug(text: str) -> str:
    """Safe slug for collection names (a-z, 0-9, underscore)."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


class ProjectConfig(BaseModel):
    """Per-project configuration (persisted in /data/projects.json)."""
    name: str
    display_name: str = ""
    git_repo_url: str = ""
    git_branch: str = "main"
    git_token: str = ""
    git_docs_subpath: str = ""
    git_auto_push: bool = True
    git_sync_interval: int = 300
    git_commit_prefix: str = "knowledge"
    webhook_secret: str = ""
    docs_path: str = ""
    collection_name: str = ""

    def ensure_defaults(self):
        if not self.docs_path:
            self.docs_path = f"/docs/{self.name}"
        if not self.collection_name:
            self.collection_name = f"proj_{_slug(self.name)}"
        if not self.display_name:
            self.display_name = self.name

    def to_safe_dict(self) -> dict:
        d = self.model_dump()
        if d.get("git_token"):
            d["git_token"] = "***set***"
        return d


@dataclass
class ProjectContext:
    """Runtime state for a single project."""
    name: str
    project_config: ProjectConfig
    merged_config: Config
    indexer: DocsIndexer
    watcher: GitWatcher
    health: HealthTracker
    quality_checker: KnowledgeQualityChecker
    index_lock: threading.Lock = field(default_factory=threading.Lock)


def merge_config(global_config: Config, project: ProjectConfig) -> Config:
    """Create a Config copy with project-specific overrides applied."""
    merged = global_config.model_copy()
    merged.docs_path = project.docs_path
    merged.git_repo_url = project.git_repo_url
    merged.git_branch = project.git_branch
    merged.git_token = project.git_token or global_config.git_token
    merged.git_sync_interval = project.git_sync_interval
    merged.git_auto_push = project.git_auto_push
    merged.git_commit_prefix = project.git_commit_prefix
    merged.git_docs_subpath = project.git_docs_subpath
    merged.webhook_secret = project.webhook_secret or global_config.webhook_secret
    return merged


class ProjectRegistry:
    """Manages multiple ProjectContext instances with a shared embedding model."""

    def __init__(self, global_config: Config, embedding_fn=None):
        self._global_config = global_config
        self._embedding_fn = embedding_fn
        self._projects: dict[str, ProjectContext] = {}
        self._lock = threading.Lock()

    @property
    def global_config(self) -> Config:
        return self._global_config

    @property
    def embedding_fn(self):
        return self._embedding_fn

    @embedding_fn.setter
    def embedding_fn(self, fn):
        self._embedding_fn = fn

    def get(self, name: str) -> Optional[ProjectContext]:
        with self._lock:
            return self._projects.get(name)

    def get_default(self) -> Optional[ProjectContext]:
        with self._lock:
            if not self._projects:
                return None
            return next(iter(self._projects.values()))

    def resolve(self, name: Optional[str] = None) -> Optional[ProjectContext]:
        """Resolve a project by name, falling back to the default project."""
        if name:
            return self.get(name)
        return self.get_default()

    def all(self) -> list[ProjectContext]:
        with self._lock:
            return list(self._projects.values())

    def names(self) -> list[str]:
        with self._lock:
            return list(self._projects.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._projects)

    def add(self, project_config: ProjectConfig, start_watcher: bool = True) -> ProjectContext:
        """Create and register a new project context."""
        project_config.ensure_defaults()

        with self._lock:
            if project_config.name in self._projects:
                raise ValueError(f"Project '{project_config.name}' already exists")

        merged = merge_config(self._global_config, project_config)
        Path(project_config.docs_path).mkdir(parents=True, exist_ok=True)

        indexer = DocsIndexer(
            merged,
            collection_name=project_config.collection_name,
            embedding_fn=self._embedding_fn,
        )
        health = HealthTracker()
        quality = KnowledgeQualityChecker(merged)
        index_lock = threading.Lock()
        watcher = GitWatcher(merged, indexer, index_lock, health, quality_checker=quality)

        ctx = ProjectContext(
            name=project_config.name,
            project_config=project_config,
            merged_config=merged,
            indexer=indexer,
            watcher=watcher,
            health=health,
            quality_checker=quality,
            index_lock=index_lock,
        )

        with self._lock:
            self._projects[project_config.name] = ctx

        if start_watcher:
            watcher.start()

        return ctx

    def remove(self, name: str) -> bool:
        with self._lock:
            ctx = self._projects.pop(name, None)
        if ctx is None:
            return False
        ctx.watcher.stop()
        return True

    def save(self):
        PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        configs = [ctx.project_config.model_dump() for ctx in self.all()]
        PROJECTS_FILE.write_text(json.dumps(configs, indent=2, default=str))

    @staticmethod
    def load_project_configs() -> list[ProjectConfig]:
        if not PROJECTS_FILE.exists():
            return []
        try:
            data = json.loads(PROJECTS_FILE.read_text())
            return [ProjectConfig(**p) for p in data]
        except Exception as e:
            print(f"Warning: Failed to load projects.json: {e}")
            return []

    def update_global_config(self, new_config: Config):
        """Propagate a global config change to all projects."""
        self._global_config = new_config
        for ctx in self.all():
            ctx.merged_config = merge_config(new_config, ctx.project_config)
            ctx.indexer.config = ctx.merged_config

    def bootstrap(self):
        """Load projects from disk, or auto-create from env vars (backward compat)."""
        configs = self.load_project_configs()

        if configs:
            for pc in configs:
                print(f"Loading project: {pc.name}")
                ctx = self.add(pc, start_watcher=False)
                _initial_index(ctx)
            return

        gc = self._global_config
        if gc.git_repo_url or Path(gc.docs_path).exists():
            name = _derive_project_name(gc)
            print(f"Legacy mode: creating project '{name}' from env vars")

            pc = ProjectConfig(
                name=name,
                git_repo_url=gc.git_repo_url,
                git_branch=gc.git_branch,
                git_token=gc.git_token,
                git_docs_subpath=gc.git_docs_subpath,
                git_auto_push=gc.git_auto_push,
                git_sync_interval=gc.git_sync_interval,
                git_commit_prefix=gc.git_commit_prefix,
                webhook_secret=gc.webhook_secret,
                docs_path=gc.docs_path,
                collection_name=LEGACY_COLLECTION,
            )

            ctx = self.add(pc, start_watcher=False)
            _initial_index(ctx)
            self.save()

    def start_all_watchers(self):
        for ctx in self.all():
            ctx.watcher.start()

    def setup_new_project(self, project_config: ProjectConfig) -> ProjectContext:
        """Add a project, clone its repo if needed, index, and start watcher."""
        ctx = self.add(project_config, start_watcher=False)
        ctx.watcher.clone_if_needed()
        _initial_index(ctx)
        ctx.watcher.start()
        self.save()
        return ctx


def _initial_index(ctx: ProjectContext):
    """Run initial indexing and quality check for a project."""
    print(f"  [{ctx.name}] Indexing {ctx.merged_config.docs_path} ...")
    result = ctx.indexer.index_all(quality_checker=ctx.quality_checker)
    ctx.health.record_index(
        ok=result.get("status") == "success",
        chunks=result.get("chunks_upserted", 0),
        files=result.get("files_indexed", 0),
        error=result.get("message") if result.get("status") != "success" else None,
    )
    ctx.health.record_skipped_files(result.get("quality_skipped", []))
    try:
        qr = ctx.quality_checker.check_all()
        ctx.health.record_quality(
            qr["score"], qr.get("critical", 0),
            qr.get("warnings", 0), qr.get("info", 0),
        )
        print(f"  [{ctx.name}] Quality: {qr['score']}/100")
    except Exception as e:
        print(f"  [{ctx.name}] Warning: Quality check failed: {e}")
    files = result.get("files_indexed", 0)
    chunks = result.get("chunks_upserted", 0)
    print(f"  [{ctx.name}] Done: {files} files, {chunks} chunks")


def _derive_project_name(config: Config) -> str:
    if config.git_repo_url:
        url = config.git_repo_url.rstrip("/").rstrip(".git")
        name = url.split("/")[-1]
        if name.endswith("-knowledge"):
            name = name[: -len("-knowledge")]
        return name
    return Path(config.docs_path).name or "default"
