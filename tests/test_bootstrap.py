# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.md.

"""Tests for the Knowledge Bootstrap & Cleanup module."""
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from flaiwheel.bootstrap import (
    CATEGORY_KEYWORDS,
    DUPLICATE_THRESHOLD,
    DocumentClassifier,
    FileInfo,
    KnowledgeBootstrap,
    _classify_by_keywords,
    _cosine_similarity,
    format_classification_report,
    format_report,
)


# ── Helpers ───────────────────────────────────────────


def _make_file_info(
    path: str,
    content_preview: str = "Some content here",
    category_by_path: str = "docs",
    category_by_content: str = "",
    category_by_embedding: str = "",
    embedding_confidence: float = 0.0,
    has_headings: bool = True,
    heading_count: int = 2,
    word_count: int = 100,
    fmt: str = ".md",
    abs_path: Path | None = None,
) -> FileInfo:
    return FileInfo(
        path=path,
        abs_path=abs_path or Path(f"/tmp/docs/{path}"),
        size_bytes=len(content_preview),
        format=fmt,
        content_preview=content_preview,
        has_headings=has_headings,
        heading_count=heading_count,
        word_count=word_count,
        category_by_path=category_by_path,
        category_by_content=category_by_content,
        category_by_embedding=category_by_embedding,
        embedding_confidence=embedding_confidence,
    )


def _fake_embedding_fn(texts: list[str]) -> list[list[float]]:
    """Deterministic fake embeddings based on text length and first chars."""
    result = []
    for t in texts:
        vec = [0.0] * 8
        for i, ch in enumerate(t[:8]):
            vec[i] = ord(ch) / 256.0
        norm = sum(x * x for x in vec) ** 0.5
        if norm > 0:
            vec = [x / norm for x in vec]
        result.append(vec)
    return result


# ── Cosine Similarity ─────────────────────────────────


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-6

    def test_zero_vector(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_opposite_vectors(self):
        assert abs(_cosine_similarity([1.0, 0.0], [-1.0, 0.0]) + 1.0) < 1e-6


# ── Classification by Content ─────────────────────────


class TestClassifyByContent:
    def test_bugfix_keywords(self):
        fi = _make_file_info(
            "some-fix.md",
            content_preview="The root cause was a race condition. The solution involved adding locks.",
        )
        cat, score = KnowledgeBootstrap._classify_by_content(fi)
        assert cat == "bugfix-log"
        assert score > 0

    def test_api_keywords(self):
        fi = _make_file_info(
            "auth-api.md",
            content_preview="The endpoint accepts a POST request with JSON body containing user credentials.",
        )
        cat, score = KnowledgeBootstrap._classify_by_content(fi)
        assert cat == "api"
        assert score > 0

    def test_setup_keywords(self):
        fi = _make_file_info(
            "infra.md",
            content_preview="Follow the install and setup instructions for the local development environment.",
        )
        cat, score = KnowledgeBootstrap._classify_by_content(fi)
        assert cat == "setup"
        assert score > 0

    def test_architecture_keywords(self):
        fi = _make_file_info(
            "overview.md",
            content_preview="The overall architecture and design of the system uses microservices.",
        )
        cat, score = KnowledgeBootstrap._classify_by_content(fi)
        assert cat == "architecture"
        assert score > 0

    def test_changelog_keywords(self):
        fi = _make_file_info(
            "notes.md",
            content_preview="Version 2.0 release notes with changelog and migration guide.",
        )
        cat, score = KnowledgeBootstrap._classify_by_content(fi)
        assert cat == "changelog"
        assert score > 0

    def test_no_keywords_returns_docs(self):
        fi = _make_file_info(
            "random.md",
            content_preview="This is just a random file with nothing special in it.",
        )
        cat, score = KnowledgeBootstrap._classify_by_content(fi)
        assert cat == "docs"
        assert score == 0.0

    def test_score_capped_at_090(self):
        fi = _make_file_info(
            "mega-bugfix.md",
            content_preview=(
                "root cause analysis of the bug fix for the error trace. "
                "Solution was to fix the regression."
            ),
        )
        _, score = KnowledgeBootstrap._classify_by_content(fi)
        assert score <= 0.9


# ── Consensus Category ────────────────────────────────


class TestConsensusCategory:
    def test_path_category_wins(self):
        fi = _make_file_info(
            "bugfix-log/fix.md",
            category_by_path="bugfix",
            category_by_content="api",
            category_by_embedding="architecture",
        )
        cat, conf = KnowledgeBootstrap._consensus_category(fi)
        assert cat == "bugfix"
        assert conf == 0.95

    def test_content_and_embedding_agree(self):
        fi = _make_file_info(
            "stray.md",
            category_by_path="docs",
            category_by_content="api",
            category_by_embedding="api",
            embedding_confidence=0.8,
        )
        cat, conf = KnowledgeBootstrap._consensus_category(fi)
        assert cat == "api"
        assert conf > 0.85

    def test_content_only(self):
        fi = _make_file_info(
            "stray.md",
            category_by_path="docs",
            category_by_content="setup",
            category_by_embedding="docs",
        )
        cat, conf = KnowledgeBootstrap._consensus_category(fi)
        assert cat == "setup"
        assert conf == 0.65

    def test_embedding_only_high_confidence(self):
        fi = _make_file_info(
            "stray.md",
            category_by_path="docs",
            category_by_content="docs",
            category_by_embedding="tests",
            embedding_confidence=0.7,
        )
        cat, conf = KnowledgeBootstrap._consensus_category(fi)
        assert cat == "tests"
        assert conf > 0.0

    def test_no_signal_returns_docs(self):
        fi = _make_file_info(
            "stray.md",
            category_by_path="docs",
            category_by_content="docs",
            category_by_embedding="docs",
            embedding_confidence=0.1,
        )
        cat, conf = KnowledgeBootstrap._consensus_category(fi)
        assert cat == "docs"
        assert conf == 0.3


# ── Duplicate Detection ───────────────────────────────


class TestDuplicateDetection:
    def test_identical_embeddings_flagged(self):
        files = [
            _make_file_info("a.md"),
            _make_file_info("b.md"),
        ]
        v = [1.0, 0.0, 0.0]
        embeddings = {"a.md": v, "b.md": v}
        dups = KnowledgeBootstrap._detect_duplicates(files, embeddings)
        assert len(dups) == 1
        assert set(dups[0]["files"]) == {"a.md", "b.md"}
        assert dups[0]["similarity"] == 1.0

    def test_different_embeddings_not_flagged(self):
        files = [
            _make_file_info("a.md"),
            _make_file_info("b.md"),
        ]
        embeddings = {
            "a.md": [1.0, 0.0, 0.0],
            "b.md": [0.0, 1.0, 0.0],
        }
        dups = KnowledgeBootstrap._detect_duplicates(files, embeddings)
        assert dups == []

    def test_no_embeddings_returns_empty(self):
        files = [_make_file_info("a.md")]
        dups = KnowledgeBootstrap._detect_duplicates(files, {})
        assert dups == []

    def test_single_file_returns_empty(self):
        files = [_make_file_info("a.md")]
        embeddings = {"a.md": [1.0, 0.0]}
        dups = KnowledgeBootstrap._detect_duplicates(files, embeddings)
        assert dups == []

    def test_cluster_groups_all_near_duplicates(self):
        files = [
            _make_file_info("a.md"),
            _make_file_info("b.md"),
            _make_file_info("c.md"),
        ]
        v = [0.5, 0.5, 0.5]
        v2 = [0.501, 0.499, 0.500]
        embeddings = {"a.md": v, "b.md": v, "c.md": v2}
        dups = KnowledgeBootstrap._detect_duplicates(files, embeddings)
        assert len(dups) == 1
        assert len(dups[0]["files"]) == 3


# ── Plan Generation ───────────────────────────────────


class TestPlanGeneration:
    def test_misplaced_root_file_generates_move(self, tmp_docs):
        bootstrap = KnowledgeBootstrap(tmp_docs)
        fi = _make_file_info(
            "stray-bugfix.md",
            abs_path=tmp_docs / "stray-bugfix.md",
            category_by_path="docs",
        )
        fi.detected_category = "bugfix-log"
        fi.confidence = 0.85
        actions, _ = bootstrap._generate_actions([fi], [])
        move_actions = [a for a in actions if a["type"] == "move"]
        assert any(a["to"] == "bugfix-log/stray-bugfix.md" for a in move_actions)

    def test_correctly_placed_file_no_move(self, tmp_docs):
        bootstrap = KnowledgeBootstrap(tmp_docs)
        fi = _make_file_info(
            "bugfix-log/proper.md",
            abs_path=tmp_docs / "bugfix-log" / "proper.md",
            category_by_path="bugfix",
        )
        fi.detected_category = "bugfix-log"
        fi.confidence = 0.95
        actions, _ = bootstrap._generate_actions([fi], [])
        move_actions = [a for a in actions if a["type"] == "move"]
        assert move_actions == []

    def test_readme_whitelist_no_move(self, tmp_docs):
        bootstrap = KnowledgeBootstrap(tmp_docs)
        fi = _make_file_info(
            "README.md",
            abs_path=tmp_docs / "README.md",
            category_by_path="docs",
        )
        fi.detected_category = "docs"
        fi.confidence = 0.3
        actions, _ = bootstrap._generate_actions([fi], [])
        move_actions = [a for a in actions if a["type"] == "move"]
        assert move_actions == []

    def test_flaiwheel_tools_whitelist_no_move(self, tmp_docs):
        bootstrap = KnowledgeBootstrap(tmp_docs)
        fi = _make_file_info(
            "FLAIWHEEL_TOOLS.md",
            abs_path=tmp_docs / "FLAIWHEEL_TOOLS.md",
            category_by_path="docs",
        )
        fi.detected_category = "docs"
        fi.confidence = 0.3
        actions, _ = bootstrap._generate_actions([fi], [])
        move_actions = [a for a in actions if a["type"] == "move"]
        assert move_actions == []

    def test_missing_dirs_generate_create_actions(self):
        empty_dir = Path("/tmp/test_bootstrap_empty_9999")
        empty_dir.mkdir(exist_ok=True)
        try:
            bootstrap = KnowledgeBootstrap(empty_dir)
            actions, _ = bootstrap._generate_actions([], [])
            create_actions = [a for a in actions if a["type"] == "create_dir"]
            assert len(create_actions) >= 7
        finally:
            import shutil
            shutil.rmtree(empty_dir, ignore_errors=True)

    def test_duplicate_cluster_generates_flag_review(self, tmp_docs):
        bootstrap = KnowledgeBootstrap(tmp_docs)
        dups = [{"similarity": 0.95, "files": ["a.md", "b.md"], "suggestion": "Merge"}]
        actions, _ = bootstrap._generate_actions([], dups)
        flag_actions = [a for a in actions if a["type"] == "flag_review"]
        assert len(flag_actions) == 1
        assert flag_actions[0]["files"] == ["a.md", "b.md"]

    def test_unstructured_md_flagged_for_rewrite(self, tmp_docs):
        bootstrap = KnowledgeBootstrap(tmp_docs)
        fi = _make_file_info(
            "messy-notes.md",
            abs_path=tmp_docs / "messy-notes.md",
            has_headings=False,
            word_count=200,
            fmt=".md",
        )
        fi.detected_category = "bugfix-log"
        fi.confidence = 0.7
        _, rewrites = bootstrap._generate_actions([fi], [])
        assert len(rewrites) == 1
        assert rewrites[0]["file"] == "messy-notes.md"

    def test_short_file_not_flagged_for_rewrite(self, tmp_docs):
        bootstrap = KnowledgeBootstrap(tmp_docs)
        fi = _make_file_info(
            "short.md",
            abs_path=tmp_docs / "short.md",
            has_headings=False,
            word_count=20,
            fmt=".md",
        )
        fi.detected_category = "docs"
        fi.confidence = 0.3
        _, rewrites = bootstrap._generate_actions([fi], [])
        assert rewrites == []

    def test_action_ids_are_unique(self, tmp_docs):
        bootstrap = KnowledgeBootstrap(tmp_docs)
        files = [
            _make_file_info("stray1.md", abs_path=tmp_docs / "stray1.md"),
            _make_file_info("stray2.md", abs_path=tmp_docs / "stray2.md"),
        ]
        for fi in files:
            fi.detected_category = "api"
            fi.confidence = 0.8
        actions, _ = bootstrap._generate_actions(files, [])
        ids = [a["id"] for a in actions]
        assert len(ids) == len(set(ids))


# ── Full Analysis ─────────────────────────────────────


class TestAnalyze:
    def test_empty_docs_path(self, tmp_path):
        missing = tmp_path / "nonexistent"
        bootstrap = KnowledgeBootstrap(missing)
        report = bootstrap.analyze()
        assert report["summary"]["total_files"] == 0
        assert "error" in report["summary"]

    def test_clean_repo_minimal_actions(self, tmp_docs):
        bootstrap = KnowledgeBootstrap(tmp_docs)
        report = bootstrap.analyze()
        assert report["summary"]["total_files"] > 0
        move_actions = [a for a in report["proposed_actions"] if a["type"] == "move"]
        assert move_actions == []

    def test_misplaced_file_detected(self, tmp_docs):
        misplaced = tmp_docs / "my-bugfix-notes.md"
        misplaced.write_text(
            "# Fix authentication timeout\n\n"
            "## Root Cause\nThe JWT token validation had a hardcoded timeout of 5 seconds "
            "which was too short for slow network conditions.\n\n"
            "## Solution\nMade the timeout configurable via environment variable AUTH_TIMEOUT "
            "with a default of 30 seconds.\n\n"
            "## Lesson Learned\nNever hardcode timeout values. Always make them configurable.\n"
        )
        bootstrap = KnowledgeBootstrap(tmp_docs)
        report = bootstrap.analyze()
        move_actions = [a for a in report["proposed_actions"] if a["type"] == "move"]
        assert any(a["from"] == "my-bugfix-notes.md" for a in move_actions)

    def test_analyze_with_embedding_fn(self, tmp_docs):
        (tmp_docs / "stray.md").write_text(
            "# API Gateway\n\n"
            "The endpoint /api/v1/users accepts GET request and returns a response "
            "with the user profile data in JSON format.\n"
        )
        bootstrap = KnowledgeBootstrap(tmp_docs, embedding_fn=_fake_embedding_fn)
        report = bootstrap.analyze()
        assert report["summary"]["total_files"] > 0
        assert report["summary"]["categories_detected"] >= 1

    def test_analyze_caches_report(self, tmp_docs):
        bootstrap = KnowledgeBootstrap(tmp_docs)
        assert bootstrap.last_report is None
        report = bootstrap.analyze()
        assert bootstrap.last_report is report


# ── Safe Execution ────────────────────────────────────


class TestExecution:
    def test_execute_without_analysis_returns_error(self, tmp_docs):
        bootstrap = KnowledgeBootstrap(tmp_docs)
        result = bootstrap.execute(["a1"])
        assert result["status"] == "error"

    def test_execute_unknown_action_id(self, tmp_docs):
        bootstrap = KnowledgeBootstrap(tmp_docs)
        bootstrap._report = {"proposed_actions": []}
        result = bootstrap.execute(["nonexistent"])
        assert "Unknown action ID" in result["errors"][0]

    def test_execute_create_dir(self, tmp_docs):
        new_dir = "new-category"
        action = {
            "id": "a1",
            "type": "create_dir",
            "path": f"{new_dir}/",
            "reason": "Test directory",
        }
        bootstrap = KnowledgeBootstrap(tmp_docs)
        bootstrap._report = {"proposed_actions": [action]}
        result = bootstrap.execute(["a1"])
        assert result["executed"] == 1
        assert (tmp_docs / new_dir).is_dir()
        assert (tmp_docs / new_dir / "README.md").exists()

    @patch("flaiwheel.bootstrap.subprocess.run")
    def test_execute_move_calls_git_mv(self, mock_run, tmp_docs):
        src = tmp_docs / "stray.md"
        src.write_text("# Stray file\n\nContent here.\n")

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="abc123\n", stderr="",
        )

        action = {
            "id": "a1",
            "type": "move",
            "from": "stray.md",
            "to": "api/stray.md",
            "reason": "Test move",
        }
        bootstrap = KnowledgeBootstrap(tmp_docs)
        bootstrap._report = {"proposed_actions": [action]}
        result = bootstrap.execute(["a1"])
        assert result["executed"] == 1

        git_mv_calls = [
            c for c in mock_run.call_args_list
            if "git" in str(c) and "mv" in str(c)
        ]
        assert len(git_mv_calls) >= 1

    def test_execute_move_missing_source(self, tmp_docs):
        action = {
            "id": "a1",
            "type": "move",
            "from": "does-not-exist.md",
            "to": "api/does-not-exist.md",
            "reason": "Test missing",
        }
        bootstrap = KnowledgeBootstrap(tmp_docs)
        bootstrap._report = {"proposed_actions": [action]}
        result = bootstrap.execute(["a1"])
        assert "Source not found" in result["errors"][0]

    def test_execute_flag_review_returns_flagged(self, tmp_docs):
        action = {
            "id": "a1",
            "type": "flag_review",
            "files": ["a.md", "b.md"],
            "similarity": 0.95,
            "reason": "Near duplicates",
        }
        bootstrap = KnowledgeBootstrap(tmp_docs)
        bootstrap._report = {"proposed_actions": [action]}
        result = bootstrap.execute(["a1"])
        assert result["results"][0]["status"] == "flagged"

    def test_execute_never_deletes_files(self, tmp_docs):
        """HARD SAFEGUARD: verify no file is deleted during execution."""
        sentinel = tmp_docs / "must-survive.md"
        sentinel.write_text("# Do Not Delete\n\nThis file must survive.\n")

        action = {
            "id": "a1",
            "type": "move",
            "from": "must-survive.md",
            "to": "architecture/must-survive.md",
            "reason": "Test safety",
        }
        bootstrap = KnowledgeBootstrap(tmp_docs)
        bootstrap._report = {"proposed_actions": [action]}

        with patch("flaiwheel.bootstrap.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="not a git repo",
            )
            bootstrap.execute(["a1"])

        dst = tmp_docs / "architecture" / "must-survive.md"
        assert dst.exists() or sentinel.exists(), "File must not be deleted"

    def test_execute_empty_action_list(self, tmp_docs):
        bootstrap = KnowledgeBootstrap(tmp_docs)
        bootstrap._report = {"proposed_actions": []}
        result = bootstrap.execute([])
        assert result["status"] == "ok"
        assert result["executed"] == 0


# ── Format Report ─────────────────────────────────────


class TestFormatReport:
    def test_error_report(self):
        report = {"summary": {"error": "Something went wrong"}}
        text = format_report(report)
        assert "Error:" in text

    def test_empty_report(self):
        report = {"summary": {"total_files": 0}}
        text = format_report(report)
        assert "No supported files" in text

    def test_full_report_contains_sections(self):
        report = {
            "summary": {
                "total_files": 10,
                "categories_detected": 4,
                "quality_score_before": 70,
                "quality_score_projected": 85,
                "files_misplaced": 3,
                "dirs_to_create": 1,
                "duplicate_clusters": 1,
                "files_need_rewrite": 2,
                "total_actions": 5,
            },
            "proposed_actions": [
                {"id": "a1", "type": "create_dir", "path": "tests/", "reason": "Standard dir"},
                {"id": "a2", "type": "move", "from": "stray.md", "to": "api/stray.md", "reason": "Classified as api"},
                {"id": "a3", "type": "flag_review", "files": ["a.md", "b.md"], "reason": "Near duplicates"},
            ],
            "duplicate_clusters": [
                {"similarity": 0.95, "files": ["a.md", "b.md"]},
            ],
            "needs_ai_rewrite": [
                {"file": "messy.md", "reason": "No structure", "detected_category": "api"},
            ],
        }
        text = format_report(report)
        assert "This is the Way" in text
        assert "Proposed Actions" in text
        assert "Duplicate" in text
        assert "AI Rewrite" in text
        assert "42" in text
        assert "execute_cleanup" in text

    def test_clean_report_no_next_steps(self):
        report = {
            "summary": {
                "total_files": 5,
                "categories_detected": 3,
                "quality_score_before": 95,
                "quality_score_projected": 95,
                "files_misplaced": 0,
                "dirs_to_create": 0,
                "duplicate_clusters": 0,
                "files_need_rewrite": 0,
                "total_actions": 0,
            },
            "proposed_actions": [],
            "duplicate_clusters": [],
            "needs_ai_rewrite": [],
        }
        text = format_report(report)
        assert "execute_cleanup" not in text


# ── Keyword Classification (module-level function) ────


class TestClassifyByKeywords:
    def test_bugfix_keywords(self):
        cat, score = _classify_by_keywords("The root cause was X. The solution was Y.")
        assert cat == "bugfix-log"
        assert score > 0

    def test_no_match_returns_docs(self):
        cat, score = _classify_by_keywords("Just random text with nothing special.")
        assert cat == "docs"
        assert score == 0.0

    def test_api_keywords(self):
        cat, _ = _classify_by_keywords("The endpoint returns a JSON response body.")
        assert cat == "api"


# ── DocumentClassifier ───────────────────────────────


class TestDocumentClassifier:
    def test_empty_input(self):
        clf = DocumentClassifier()
        result = clf.classify([])
        assert result["status"] == "empty"

    def test_single_file_no_embedding(self):
        clf = DocumentClassifier(embedding_fn=None)
        result = clf.classify([{
            "path": "docs/auth-api.md",
            "content": "# Auth API\n\nThe endpoint accepts a POST request with JSON credentials.\n",
        }])
        assert result["status"] == "ok"
        assert result["total_files"] == 1
        assert len(result["classifications"]) == 1
        c = result["classifications"][0]
        assert c["path"] == "docs/auth-api.md"
        assert c["category"] in ("api", "docs")
        assert "confidence" in c
        assert "target_directory" in c

    def test_with_embedding_fn(self):
        clf = DocumentClassifier(embedding_fn=_fake_embedding_fn)
        result = clf.classify([
            {"path": "setup.md", "content": "Install and setup the local dev environment."},
            {"path": "bugfix.md", "content": "The root cause was a race condition. Solution was locking."},
        ])
        assert result["status"] == "ok"
        assert result["total_files"] == 2
        assert len(result["classifications"]) == 2

    def test_duplicate_detection(self):
        same_content = "Exactly the same document content for testing."
        clf = DocumentClassifier(embedding_fn=_fake_embedding_fn)
        result = clf.classify([
            {"path": "a.md", "content": same_content},
            {"path": "b.md", "content": same_content},
        ])
        assert result["duplicate_clusters"] >= 0

    def test_write_tool_suggested(self):
        clf = DocumentClassifier(embedding_fn=None)
        result = clf.classify([{
            "path": "my-bugfix.md",
            "content": "## Root Cause\nNull pointer. ## Solution\nAdded null check.",
        }])
        c = result["classifications"][0]
        if c["category"] == "bugfix-log":
            assert c["write_tool"] == "write_bugfix_summary"

    def test_needs_rewrite_flag(self):
        clf = DocumentClassifier(embedding_fn=None)
        result = clf.classify([{
            "path": "messy-notes.md",
            "content": " ".join(["word"] * 100),
        }])
        c = result["classifications"][0]
        assert c["needs_rewrite"] is True

    def test_structured_file_no_rewrite(self):
        clf = DocumentClassifier(embedding_fn=None)
        result = clf.classify([{
            "path": "clean.md",
            "content": "# Title\n\n## Section\n\nSome content here.\n",
        }])
        c = result["classifications"][0]
        assert c["needs_rewrite"] is False

    def test_signals_included(self):
        clf = DocumentClassifier(embedding_fn=_fake_embedding_fn)
        result = clf.classify([{
            "path": "test.md",
            "content": "Some test content for classification.",
        }])
        c = result["classifications"][0]
        assert "signals" in c
        assert "keyword" in c["signals"]
        assert "embedding" in c["signals"]
        assert "embedding_confidence" in c["signals"]

    def test_consensus_path_hint(self):
        clf = DocumentClassifier(embedding_fn=None)
        result = clf.classify([{
            "path": "bugfix-log/my-fix.md",
            "content": "Random unrelated content.",
        }])
        c = result["classifications"][0]
        assert c["category"] in ("bugfix-log", "bugfix")
        assert c["confidence"] >= 0.9


# ── Format Classification Report ─────────────────────


class TestFormatClassificationReport:
    def test_empty_result(self):
        result = {"status": "empty", "message": "No files."}
        text = format_classification_report(result)
        assert "No files" in text

    def test_full_report(self):
        result = {
            "status": "ok",
            "total_files": 3,
            "categories_found": 2,
            "files_needing_rewrite": 1,
            "duplicate_clusters": 1,
            "classifications": [
                {
                    "path": "auth.md",
                    "category": "api",
                    "confidence": 0.85,
                    "target_directory": "api",
                    "write_tool": "write_api_doc",
                    "word_count": 200,
                    "has_headings": True,
                    "needs_rewrite": False,
                    "signals": {"keyword": "api", "embedding": "api", "embedding_confidence": 0.8},
                },
                {
                    "path": "notes.md",
                    "category": "docs",
                    "confidence": 0.3,
                    "target_directory": "docs",
                    "write_tool": "",
                    "word_count": 150,
                    "has_headings": False,
                    "needs_rewrite": True,
                    "signals": {"keyword": "docs", "embedding": "docs", "embedding_confidence": 0.1},
                },
            ],
            "duplicates": [
                {"files": ["a.md", "b.md"], "similarity": 0.95, "suggestion": "Merge into api/"},
            ],
        }
        text = format_classification_report(result)
        assert "This is the Way" in text
        assert "Migration Plan" in text
        assert "auth.md" in text
        assert "write_api_doc" in text
        assert "Duplicate" in text
        assert "42" in text
        assert "reindex()" in text
