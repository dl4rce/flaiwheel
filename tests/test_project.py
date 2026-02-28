"""Tests for the multi-project registry (ProjectConfig, ProjectContext, ProjectRegistry)."""
import json
import threading
from pathlib import Path

import pytest

from flaiwheel.config import Config
from flaiwheel.indexer import DocsIndexer, DEFAULT_COLLECTION
from flaiwheel.project import (
    LEGACY_COLLECTION,
    ProjectConfig,
    ProjectContext,
    ProjectRegistry,
    _derive_project_name,
    _slug,
    merge_config,
)


# ── Helpers ───────────────────────────────────────────


def _make_docs(path: Path, files: dict[str, str] | None = None):
    """Create a docs directory with basic structure."""
    for d in ["architecture", "api", "bugfix-log", "best-practices", "setup", "changelog", "tests"]:
        (path / d).mkdir(parents=True, exist_ok=True)
        (path / d / "README.md").write_text(
            f"# {d}\n\nThis directory contains {d} documentation managed by Flaiwheel.\n"
            f"Add .md files here or use the corresponding write tool.\n"
        )
    (path / "README.md").write_text(
        "# Project Knowledge Base\n\n"
        "This repository contains the project knowledge base managed by Flaiwheel. "
        "It organizes architecture decisions, API documentation, bugfix logs, best practices, "
        "setup guides, changelogs, and test cases into structured Markdown files.\n"
    )
    if files:
        for name, content in files.items():
            fp = path / name
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)


def _config(tmp_path: Path, docs_name: str = "docs") -> Config:
    docs = tmp_path / docs_name
    docs.mkdir(parents=True, exist_ok=True)
    _make_docs(docs)
    return Config(
        docs_path=str(docs),
        vectorstore_path=str(tmp_path / "vectorstore"),
    )


# ── Tests ─────────────────────────────────────────────


class TestSlug:
    def test_basic(self):
        assert _slug("My Project") == "my_project"

    def test_special_chars(self):
        assert _slug("my-project-v2.0!") == "my_project_v2_0"

    def test_truncate(self):
        long = "a" * 100
        assert len(_slug(long)) <= 60


class TestProjectConfig:
    def test_ensure_defaults(self):
        pc = ProjectConfig(name="test-proj")
        pc.ensure_defaults()
        assert pc.docs_path == "/docs/test-proj"
        assert pc.collection_name == "proj_test_proj"
        assert pc.display_name == "test-proj"

    def test_safe_dict_hides_token(self):
        pc = ProjectConfig(name="x", git_token="secret123")
        d = pc.to_safe_dict()
        assert d["git_token"] == "***set***"

    def test_safe_dict_no_token(self):
        pc = ProjectConfig(name="x")
        d = pc.to_safe_dict()
        assert d["git_token"] == ""


class TestMergeConfig:
    def test_overrides_project_fields(self):
        gc = Config(
            docs_path="/docs",
            git_repo_url="https://global.git",
            git_branch="main",
            git_token="global_token",
        )
        pc = ProjectConfig(
            name="alpha",
            git_repo_url="https://alpha.git",
            git_branch="develop",
        )
        merged = merge_config(gc, pc)
        assert merged.docs_path == pc.docs_path
        assert merged.git_repo_url == "https://alpha.git"
        assert merged.git_branch == "develop"
        assert merged.git_token == "global_token"

    def test_project_token_takes_precedence(self):
        gc = Config(git_token="global")
        pc = ProjectConfig(name="alpha", git_token="project")
        merged = merge_config(gc, pc)
        assert merged.git_token == "project"

    def test_global_embedding_preserved(self):
        gc = Config(embedding_model="all-mpnet-base-v2")
        pc = ProjectConfig(name="alpha")
        merged = merge_config(gc, pc)
        assert merged.embedding_model == "all-mpnet-base-v2"


class TestDeriveProjectName:
    def test_from_git_url(self):
        cfg = Config(git_repo_url="https://github.com/org/my-app-knowledge.git")
        assert _derive_project_name(cfg) == "my-app"

    def test_from_git_url_no_knowledge_suffix(self):
        cfg = Config(git_repo_url="https://github.com/org/my-app.git")
        assert _derive_project_name(cfg) == "my-app"

    def test_from_docs_path(self):
        cfg = Config(docs_path="/docs/fallback")
        assert _derive_project_name(cfg) == "fallback"


class TestProjectRegistry:
    def test_add_and_get(self, tmp_path):
        cfg = _config(tmp_path)
        reg = ProjectRegistry(cfg)
        pc = ProjectConfig(name="alpha", docs_path=str(tmp_path / "docs"))
        ctx = reg.add(pc, start_watcher=False)
        assert ctx.name == "alpha"
        assert reg.get("alpha") is ctx
        assert reg.get_default() is ctx
        assert len(reg) == 1

    def test_add_duplicate_raises(self, tmp_path):
        cfg = _config(tmp_path)
        reg = ProjectRegistry(cfg)
        pc = ProjectConfig(name="alpha", docs_path=str(tmp_path / "docs"))
        reg.add(pc, start_watcher=False)
        with pytest.raises(ValueError, match="already exists"):
            reg.add(pc, start_watcher=False)

    def test_remove(self, tmp_path):
        cfg = _config(tmp_path)
        reg = ProjectRegistry(cfg)
        pc = ProjectConfig(name="alpha", docs_path=str(tmp_path / "docs"))
        reg.add(pc, start_watcher=False)
        assert reg.remove("alpha") is True
        assert reg.get("alpha") is None
        assert len(reg) == 0

    def test_remove_nonexistent(self, tmp_path):
        cfg = _config(tmp_path)
        reg = ProjectRegistry(cfg)
        assert reg.remove("nope") is False

    def test_resolve_with_name(self, tmp_path):
        cfg = _config(tmp_path)
        reg = ProjectRegistry(cfg)
        pc = ProjectConfig(name="alpha", docs_path=str(tmp_path / "docs"))
        ctx = reg.add(pc, start_watcher=False)
        assert reg.resolve("alpha") is ctx

    def test_resolve_default(self, tmp_path):
        cfg = _config(tmp_path)
        reg = ProjectRegistry(cfg)
        pc = ProjectConfig(name="alpha", docs_path=str(tmp_path / "docs"))
        ctx = reg.add(pc, start_watcher=False)
        assert reg.resolve(None) is ctx
        assert reg.resolve() is ctx

    def test_resolve_missing(self, tmp_path):
        cfg = _config(tmp_path)
        reg = ProjectRegistry(cfg)
        assert reg.resolve("nope") is None

    def test_names(self, tmp_path):
        cfg = _config(tmp_path)
        reg = ProjectRegistry(cfg)
        for n in ["alpha", "beta", "gamma"]:
            d = tmp_path / n
            d.mkdir(parents=True, exist_ok=True)
            _make_docs(d)
            reg.add(ProjectConfig(name=n, docs_path=str(d)), start_watcher=False)
        assert reg.names() == ["alpha", "beta", "gamma"]

    def test_save_and_load(self, tmp_path, monkeypatch):
        import flaiwheel.project as proj_mod
        pf = tmp_path / "projects.json"
        monkeypatch.setattr(proj_mod, "PROJECTS_FILE", pf)

        cfg = _config(tmp_path)
        reg = ProjectRegistry(cfg)
        pc = ProjectConfig(name="alpha", git_repo_url="https://x.git", docs_path=str(tmp_path / "docs"))
        reg.add(pc, start_watcher=False)
        reg.save()

        assert pf.exists()
        loaded = ProjectRegistry.load_project_configs()
        assert len(loaded) == 1
        assert loaded[0].name == "alpha"
        assert loaded[0].git_repo_url == "https://x.git"

    def test_update_global_config(self, tmp_path):
        cfg = _config(tmp_path)
        reg = ProjectRegistry(cfg)
        pc = ProjectConfig(name="alpha", docs_path=str(tmp_path / "docs"))
        ctx = reg.add(pc, start_watcher=False)

        new_cfg = cfg.model_copy()
        new_cfg.embedding_model = "new-model"
        reg.update_global_config(new_cfg)

        assert ctx.merged_config.embedding_model == "new-model"
        assert reg.global_config.embedding_model == "new-model"


class TestMultiProjectIsolation:
    """Verify that operations on one project don't affect another."""

    def test_separate_collections(self, tmp_path):
        cfg = _config(tmp_path)
        reg = ProjectRegistry(cfg)

        docs_a = tmp_path / "docs_a"
        docs_b = tmp_path / "docs_b"
        docs_a.mkdir()
        docs_b.mkdir()
        _make_docs(docs_a)
        _make_docs(docs_b)

        (docs_a / "bugfix-log" / "fix-a.md").write_text(
            "# Bug Alpha\n\n**Date:** 2026-01-01\n**Tags:** alpha,network\n\n"
            "## Root Cause\nThe Alpha service experienced a connection timeout because the "
            "retry logic in the HTTP client was not configured properly. The default timeout "
            "was only 5 seconds which is too short for the upstream Alpha API.\n\n"
            "## Solution\nIncreased the timeout to 30 seconds and added exponential backoff "
            "retry logic with a maximum of 3 attempts for the Alpha service client.\n\n"
            "## Lesson Learned\nAlways configure explicit timeouts and retry policies for "
            "all external service calls in the Alpha project to prevent cascading failures.\n"
        )
        (docs_b / "bugfix-log" / "fix-b.md").write_text(
            "# Bug Beta\n\n**Date:** 2026-01-01\n**Tags:** beta,database\n\n"
            "## Root Cause\nThe Beta database migration failed silently because the "
            "migration script did not check for existing columns before attempting to add them. "
            "This caused a duplicate column error in the Beta PostgreSQL schema.\n\n"
            "## Solution\nAdded IF NOT EXISTS clauses to all ALTER TABLE statements in the "
            "Beta migration scripts and implemented proper error handling with rollback.\n\n"
            "## Lesson Learned\nAll Beta database migrations must be idempotent and include "
            "proper existence checks to allow safe re-runs without data corruption.\n"
        )

        ctx_a = reg.add(ProjectConfig(name="alpha", docs_path=str(docs_a)), start_watcher=False)
        ctx_b = reg.add(ProjectConfig(name="beta", docs_path=str(docs_b)), start_watcher=False)

        res_a = ctx_a.indexer.index_all()
        res_b = ctx_b.indexer.index_all()

        assert res_a["files_indexed"] > 0
        assert res_b["files_indexed"] > 0

        hits_a = ctx_a.indexer.search("root cause", top_k=5)
        hits_b = ctx_b.indexer.search("root cause", top_k=5)

        texts_a = " ".join(h["text"] for h in hits_a)
        texts_b = " ".join(h["text"] for h in hits_b)

        assert "Alpha" in texts_a
        assert "Beta" not in texts_a
        assert "Beta" in texts_b
        assert "Alpha" not in texts_b

    def test_separate_locks(self, tmp_path):
        cfg = _config(tmp_path)
        reg = ProjectRegistry(cfg)

        for n in ["alpha", "beta"]:
            d = tmp_path / n
            d.mkdir()
            _make_docs(d)
            reg.add(ProjectConfig(name=n, docs_path=str(d)), start_watcher=False)

        ctx_a = reg.get("alpha")
        ctx_b = reg.get("beta")
        assert ctx_a.index_lock is not ctx_b.index_lock

    def test_separate_health(self, tmp_path):
        cfg = _config(tmp_path)
        reg = ProjectRegistry(cfg)

        for n in ["alpha", "beta"]:
            d = tmp_path / n
            d.mkdir()
            _make_docs(d)
            reg.add(ProjectConfig(name=n, docs_path=str(d)), start_watcher=False)

        ctx_a = reg.get("alpha")
        ctx_b = reg.get("beta")
        assert ctx_a.health is not ctx_b.health

        ctx_a.health.record_search("search_docs", True)
        assert ctx_a.health.status["searches_total"] == 1
        assert ctx_b.health.status["searches_total"] == 0

    def test_reindex_one_does_not_affect_other(self, tmp_path):
        cfg = _config(tmp_path)
        reg = ProjectRegistry(cfg)

        docs_a = tmp_path / "docs_a"
        docs_b = tmp_path / "docs_b"
        docs_a.mkdir()
        docs_b.mkdir()
        _make_docs(docs_a)
        _make_docs(docs_b)

        ctx_a = reg.add(ProjectConfig(name="alpha", docs_path=str(docs_a)), start_watcher=False)
        ctx_b = reg.add(ProjectConfig(name="beta", docs_path=str(docs_b)), start_watcher=False)

        ctx_a.indexer.index_all()
        ctx_b.indexer.index_all()

        count_b_before = ctx_b.indexer.collection.count()

        ctx_a.indexer.clear_index()
        assert ctx_a.indexer.collection.count() == 0
        assert ctx_b.indexer.collection.count() == count_b_before


class TestBackwardCompat:
    def test_legacy_mode_creates_project(self, tmp_path, monkeypatch):
        import flaiwheel.project as proj_mod
        pf = tmp_path / "projects.json"
        monkeypatch.setattr(proj_mod, "PROJECTS_FILE", pf)

        docs = tmp_path / "docs"
        docs.mkdir()
        isolated = docs / "my-app"
        isolated.mkdir()
        _make_docs(isolated)

        cfg = Config(
            docs_path=str(docs),
            vectorstore_path=str(tmp_path / "vectorstore"),
            git_repo_url="https://github.com/org/my-app-knowledge.git",
        )
        reg = ProjectRegistry(cfg)
        reg.bootstrap()

        assert len(reg) == 1
        ctx = reg.get_default()
        assert ctx.name == "my-app"
        assert ctx.project_config.docs_path == str(isolated)
        assert ctx.project_config.collection_name == LEGACY_COLLECTION

    def test_existing_projects_json_loaded(self, tmp_path, monkeypatch):
        import flaiwheel.project as proj_mod
        pf = tmp_path / "projects.json"

        docs = tmp_path / "docs"
        docs.mkdir()
        _make_docs(docs)

        pf.write_text(json.dumps([{
            "name": "loaded-proj",
            "docs_path": str(docs),
            "collection_name": "proj_loaded_proj",
        }]))
        monkeypatch.setattr(proj_mod, "PROJECTS_FILE", pf)

        cfg = Config(
            docs_path=str(docs),
            vectorstore_path=str(tmp_path / "vectorstore"),
        )
        reg = ProjectRegistry(cfg)
        reg.bootstrap()

        assert len(reg) == 1
        assert reg.get("loaded-proj") is not None
