"""Tests for the DocsIndexer."""
import pytest
from flaiwheel.indexer import DocsIndexer, DOC_TYPES


class TestDocTypes:
    def test_all_expected_types_present(self):
        expected = {"docs", "bugfix", "best-practice", "api", "architecture", "changelog", "setup", "readme", "test"}
        assert set(DOC_TYPES) == expected


class TestDetectType:
    @pytest.mark.parametrize("path,expected", [
        ("bugfix-log/2026-01-01-fix.md", "bugfix"),
        ("bug-fix/fix.md", "bugfix"),
        ("best-practices/error-handling.md", "best-practice"),
        ("bestpractice/tips.md", "best-practice"),
        ("api/users.md", "api"),
        ("architecture/design.md", "architecture"),
        ("changelog/1-0-0.md", "changelog"),
        ("release/notes.md", "changelog"),
        ("setup/local-dev.md", "setup"),
        ("install/guide.md", "setup"),
        ("README.md", "readme"),
        ("tests/login-test.md", "test"),
        ("test-cases/auth.md", "test"),
        ("docs/general.md", "docs"),
        ("random/file.md", "docs"),
    ])
    def test_detect_type(self, path, expected):
        assert DocsIndexer._detect_type(path) == expected


class TestChunking:
    @pytest.fixture
    def indexer(self, config):
        return DocsIndexer(config)

    def test_basic_heading_chunking(self, indexer):
        content = (
            "# Title\n\n"
            "Introduction paragraph with enough content to pass the minimum.\n\n"
            "## Section One\n\n"
            "Content for section one with enough detail to be meaningful.\n\n"
            "## Section Two\n\n"
            "Content for section two with enough detail to be meaningful.\n"
        )
        chunks = indexer.chunk_markdown(content, "test.md")
        assert len(chunks) >= 2

    def test_chunks_have_required_metadata(self, indexer):
        content = "# Title\n\nSome meaningful content that is long enough to pass checks.\n"
        chunks = indexer.chunk_markdown(content, "architecture/design.md")
        if chunks:
            meta = chunks[0]["metadata"]
            assert "source" in meta
            assert "heading" in meta
            assert "type" in meta
            assert "char_count" in meta
            assert "word_count" in meta
            assert meta["type"] == "architecture"

    def test_empty_content_no_chunks(self, indexer):
        chunks = indexer.chunk_markdown("", "test.md")
        assert chunks == []

    def test_very_short_content_skipped(self, indexer):
        chunks = indexer.chunk_markdown("# Hi\n\nShort.", "test.md")
        assert chunks == []

    def test_chunk_id_deterministic(self, indexer):
        id1 = DocsIndexer._make_chunk_id("file.md", "some text")
        id2 = DocsIndexer._make_chunk_id("file.md", "some text")
        assert id1 == id2

    def test_chunk_id_differs_for_different_content(self, indexer):
        id1 = DocsIndexer._make_chunk_id("file.md", "text A")
        id2 = DocsIndexer._make_chunk_id("file.md", "text B")
        assert id1 != id2


class TestIndexSingle:
    @pytest.fixture
    def indexer(self, config):
        return DocsIndexer(config)

    def test_index_and_search(self, indexer):
        content = (
            "# Authentication Architecture\n\n"
            "## Overview\n"
            "We use JWT tokens for stateless authentication across all microservices.\n\n"
            "## Decisions\n"
            "Chose JWT over session cookies for horizontal scaling.\n"
        )
        n = indexer.index_single("architecture/auth.md", content)
        assert n > 0

        results = indexer.search("JWT authentication", top_k=3)
        assert len(results) > 0
        assert results[0]["type"] == "architecture"

    def test_search_with_type_filter(self, indexer):
        indexer.index_single("architecture/auth.md",
            "# Auth\n\n## Overview\nJWT-based authentication system design.\n")
        indexer.index_single("bugfix-log/2026-01-01-fix.md",
            "# Fix auth bug\n\n## Root Cause\nToken validation was wrong.\n\n"
            "## Solution\nFixed the validator.\n\n## Lesson Learned\nTest tokens.\n")

        arch_results = indexer.search("authentication", top_k=5, type_filter="architecture")
        bug_results = indexer.search("authentication", top_k=5, type_filter="bugfix")

        assert all(r["type"] == "architecture" for r in arch_results)
        assert all(r["type"] == "bugfix" for r in bug_results)

    def test_search_empty_index(self, indexer):
        results = indexer.search("anything")
        assert results == []


class TestRerankerConfig:
    @pytest.fixture
    def indexer(self, config):
        return DocsIndexer(config)

    def test_reranker_off_by_default(self, config):
        assert config.reranker_enabled is False

    def test_rrf_k_configurable(self, config, indexer):
        config.rrf_k = 30
        config.rrf_vector_weight = 0.4
        config.rrf_bm25_weight = 0.6
        indexer.config = config
        indexer.index_single("architecture/auth.md",
            "# Auth\n\n## Overview\nJWT-based authentication system design.\n")
        results = indexer.search("JWT authentication", top_k=3)
        assert isinstance(results, list)

    def test_min_relevance_filters(self, config, indexer):
        config.min_relevance = 99.9
        indexer.config = config
        indexer.index_single("architecture/auth.md",
            "# Auth\n\n## Overview\nJWT-based authentication system design.\n")
        results = indexer.search("unrelated random banana query", top_k=3)
        assert len(results) == 0

    def test_bm25_relevance_normalization(self, indexer):
        hits = [
            {"id": "a", "score": 10.0, "_from": "bm25"},
            {"id": "b", "score": 5.0, "_from": "bm25"},
            {"id": "c", "score": 0.0, "_from": "bm25"},
        ]
        DocsIndexer._normalize_bm25_relevance(hits)
        assert hits[0]["bm25_relevance"] == 100.0
        assert hits[1]["bm25_relevance"] == 50.0
        assert hits[2]["bm25_relevance"] == 0.0

    def test_normalize_empty(self):
        DocsIndexer._normalize_bm25_relevance([])

    def test_rrf_fuse_with_weights(self, config, indexer):
        vector_hits = [
            {"id": "a", "text": "x", "metadata": {"source": "a.md", "heading": "h", "type": "docs"}, "score": 0.1, "_from": "vector"},
            {"id": "b", "text": "y", "metadata": {"source": "b.md", "heading": "h", "type": "docs"}, "score": 0.2, "_from": "vector"},
        ]
        bm25_hits = [
            {"id": "b", "text": "y", "metadata": {"source": "b.md", "heading": "h", "type": "docs"}, "score": 5.0, "_from": "bm25"},
            {"id": "c", "text": "z", "metadata": {"source": "c.md", "heading": "h", "type": "docs"}, "score": 3.0, "_from": "bm25"},
        ]
        result = indexer._rrf_fuse(vector_hits, bm25_hits, top_k=3, vector_weight=0.5, bm25_weight=1.5)
        assert result[0]["id"] == "b"
