"""Tests for the embedding model hot-swap (background migration)."""
import threading
import time

import pytest

from flaiwheel.config import Config
from flaiwheel.health import HealthTracker
from flaiwheel.indexer import DocsIndexer, SHADOW_COLLECTION


def _make_docs(tmp_path, count=5):
    """Create a docs directory with several .md files large enough to be indexed."""
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    for d in ["architecture", "api", "bugfix-log", "best-practices", "setup", "changelog", "tests"]:
        (docs / d).mkdir(exist_ok=True)
        (docs / d / "README.md").write_text(
            f"# {d}\n\nThis directory contains {d} documentation managed by Flaiwheel.\n"
            f"Add .md files here or use the corresponding write tool.\n"
        )
    (docs / "README.md").write_text(
        "# Project Knowledge Base\n\n"
        "This repository contains the project knowledge base managed by Flaiwheel. "
        "It organizes architecture decisions, API documentation, bugfix logs, best practices, "
        "setup guides, changelogs, and test cases into structured Markdown files.\n"
    )
    for i in range(count):
        (docs / "architecture" / f"design-{i}.md").write_text(
            f"# Architecture Design {i}\n\n"
            f"## Overview\n"
            f"This document describes component {i} of the system architecture. "
            f"It covers the key design decisions, trade-offs, and implementation details "
            f"for this particular service layer in the distributed microservices stack.\n\n"
            f"## Decisions\n"
            f"We chose approach {i} because it provides better isolation between services "
            f"while maintaining acceptable latency for cross-service communication.\n"
        )
    return docs


@pytest.fixture
def migration_env(tmp_path):
    """Environment with indexer, health, lock, and docs for migration testing."""
    docs = _make_docs(tmp_path, count=5)
    cfg = Config(
        docs_path=str(docs),
        vectorstore_path=str(tmp_path / "vectorstore"),
        embedding_provider="local",
        embedding_model="all-MiniLM-L6-v2",
    )
    indexer = DocsIndexer(cfg)
    indexer.index_all()
    health = HealthTracker()
    lock = threading.Lock()
    return {
        "indexer": indexer,
        "config": cfg,
        "health": health,
        "lock": lock,
        "docs": docs,
        "tmp_path": tmp_path,
    }


def _wait_migration(indexer, timeout=60):
    """Wait for migration to finish (complete, failed, or cancelled)."""
    start = time.time()
    while time.time() - start < timeout:
        status = indexer.migration_status
        if status and status["status"] in ("complete", "failed", "cancelled"):
            return status
        time.sleep(0.2)
    raise TimeoutError("Migration did not complete within timeout")


class TestMigrationLifecycle:
    def test_migration_completes_and_replaces_index(self, migration_env):
        indexer = migration_env["indexer"]
        old_count = indexer.collection.count()
        assert old_count > 0

        new_cfg = Config(
            docs_path=migration_env["config"].docs_path,
            vectorstore_path=migration_env["config"].vectorstore_path,
            embedding_provider="local",
            embedding_model="all-MiniLM-L12-v2",
        )
        result = indexer.start_model_swap(
            new_cfg, migration_env["lock"], health=migration_env["health"],
        )
        assert result["status"] == "started"

        status = _wait_migration(indexer)
        assert status["status"] == "complete"
        assert status["chunks_created"] > 0
        assert status["files_done"] == status["total_files"]

        new_count = indexer.collection.count()
        assert new_count > 0

    def test_health_records_migration(self, migration_env):
        new_cfg = Config(
            docs_path=migration_env["config"].docs_path,
            vectorstore_path=migration_env["config"].vectorstore_path,
            embedding_provider="local",
            embedding_model="all-MiniLM-L12-v2",
        )
        indexer = migration_env["indexer"]
        indexer.start_model_swap(
            new_cfg, migration_env["lock"], health=migration_env["health"],
        )
        _wait_migration(indexer)

        h = migration_env["health"].status
        assert h["migration_status"] is not None
        assert h["migration_status"]["status"] == "complete"


class TestSearchDuringMigration:
    def test_search_available_during_migration(self, migration_env):
        indexer = migration_env["indexer"]
        indexer.index_single(
            "architecture/auth.md",
            "# Auth Architecture\n\n## Overview\n"
            "JWT-based stateless authentication system used across all microservices.\n",
        )

        new_cfg = Config(
            docs_path=migration_env["config"].docs_path,
            vectorstore_path=migration_env["config"].vectorstore_path,
            embedding_provider="local",
            embedding_model="all-MiniLM-L12-v2",
        )
        indexer.start_model_swap(new_cfg, migration_env["lock"])

        results = indexer.search("authentication JWT", top_k=3)
        assert len(results) > 0

        _wait_migration(indexer)


class TestCancelMigration:
    def test_cancel_stops_migration(self, migration_env):
        docs = migration_env["docs"]
        for i in range(20):
            (docs / "architecture" / f"extra-{i}.md").write_text(
                f"# Extra Document {i}\n\n## Overview\n"
                f"This is extra document number {i} created specifically to slow down the "
                f"migration process so we can test cancellation behavior. It contains enough "
                f"content to be a valid chunk in the vector database and will be processed "
                f"during the migration worker loop.\n"
            )

        indexer = migration_env["indexer"]
        new_cfg = Config(
            docs_path=migration_env["config"].docs_path,
            vectorstore_path=migration_env["config"].vectorstore_path,
            embedding_provider="local",
            embedding_model="all-MiniLM-L12-v2",
        )
        indexer.start_model_swap(new_cfg, migration_env["lock"])

        time.sleep(0.1)
        result = indexer.cancel_migration()
        assert result["status"] == "cancelled"

        status = _wait_migration(indexer)
        assert status["status"] == "cancelled"

    def test_cancel_when_no_migration_returns_error(self, migration_env):
        result = migration_env["indexer"].cancel_migration()
        assert result["status"] == "error"


class TestConcurrentMigration:
    def test_concurrent_migration_rejected(self, migration_env):
        indexer = migration_env["indexer"]
        new_cfg = Config(
            docs_path=migration_env["config"].docs_path,
            vectorstore_path=migration_env["config"].vectorstore_path,
            embedding_provider="local",
            embedding_model="all-MiniLM-L12-v2",
        )
        result1 = indexer.start_model_swap(new_cfg, migration_env["lock"])
        assert result1["status"] == "started"

        result2 = indexer.start_model_swap(new_cfg, migration_env["lock"])
        assert result2["status"] == "error"
        assert "already in progress" in result2["message"]

        _wait_migration(indexer)


class TestSameModelSkipped:
    def test_same_model_returns_skipped(self, migration_env):
        indexer = migration_env["indexer"]
        result = indexer.start_model_swap(
            migration_env["config"], migration_env["lock"],
        )
        assert result["status"] == "skipped"


class TestOrphanedShadowCleanup:
    def test_orphaned_shadow_cleaned_on_init(self, tmp_path):
        docs = _make_docs(tmp_path, count=1)
        cfg = Config(
            docs_path=str(docs),
            vectorstore_path=str(tmp_path / "vectorstore"),
        )
        import chromadb
        client = chromadb.PersistentClient(path=cfg.vectorstore_path)
        client.get_or_create_collection(SHADOW_COLLECTION)
        existing = [c.name for c in client.list_collections()]
        assert SHADOW_COLLECTION in existing

        indexer = DocsIndexer(cfg)
        existing_after = [c.name for c in indexer.chroma.list_collections()]
        assert SHADOW_COLLECTION not in existing_after


class TestMigrationStatus:
    def test_no_migration_returns_none(self, migration_env):
        assert migration_env["indexer"].migration_status is None

    def test_running_migration_returns_dict(self, migration_env):
        indexer = migration_env["indexer"]
        new_cfg = Config(
            docs_path=migration_env["config"].docs_path,
            vectorstore_path=migration_env["config"].vectorstore_path,
            embedding_provider="local",
            embedding_model="all-MiniLM-L12-v2",
        )
        indexer.start_model_swap(new_cfg, migration_env["lock"])
        status = indexer.migration_status
        assert status is not None
        assert "id" in status
        assert "status" in status
        assert "percent" in status
        _wait_migration(indexer)
