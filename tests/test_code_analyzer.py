# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.md.

"""Tests for the Cold-Start Codebase Analyzer."""
import textwrap
from pathlib import Path

import pytest

from flaiwheel.code_analyzer import (
    CodebaseAnalyzer,
    CodeUnit,
    _extract_python,
    _extract_ts_js,
    _score_documentability,
    _walk_repo,
    format_codebase_report,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Minimal fake repo layout."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        textwrap.dedent("""\
        \"\"\"Entry point for the application.\"\"\"
        import os
        import sys
        from pathlib import Path

        def run():
            \"\"\"Run the app.\"\"\"
            pass

        def _internal():
            pass

        class App:
            \"\"\"Main application class.\"\"\"
            def __init__(self):
                pass
        """),
        encoding="utf-8",
    )
    (tmp_path / "src" / "utils.py").write_text(
        textwrap.dedent("""\
        def helper_a(x):
            return x + 1

        def helper_b(x):
            return x + 2
        """),
        encoding="utf-8",
    )
    (tmp_path / "src" / "api.ts").write_text(
        textwrap.dedent("""\
        /** API service for user management. */
        import axios from 'axios';
        import { User } from './types';

        export async function getUser(id: string): Promise<User> {
            return axios.get(`/users/${id}`);
        }

        export class UserService {
            async create(data: Partial<User>) {}
        }
        """),
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# My Project\n\nA cool project.", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name": "my-project"}', encoding="utf-8")

    # Should be skipped
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lodash.js").write_text("module.exports = {};")
    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "src" / "__pycache__" / "main.cpython-311.pyc").write_bytes(b"\x00" * 100)

    return tmp_path


# ── _walk_repo ─────────────────────────────────────────────────────────────


def test_walk_repo_skips_node_modules(repo: Path) -> None:
    files = _walk_repo(repo)
    paths = [str(f) for f in files]
    assert not any("node_modules" in p for p in paths)


def test_walk_repo_skips_pycache(repo: Path) -> None:
    files = _walk_repo(repo)
    paths = [str(f) for f in files]
    assert not any("__pycache__" in p for p in paths)


def test_walk_repo_finds_source_files(repo: Path) -> None:
    files = _walk_repo(repo)
    names = {f.name for f in files}
    assert "main.py" in names
    assert "utils.py" in names
    assert "api.ts" in names
    assert "README.md" in names


# ── _extract_python ────────────────────────────────────────────────────────


def test_extract_python_symbols(repo: Path) -> None:
    path = repo / "src" / "main.py"
    symbols, doc, imports, pub_fns, has_docs = _extract_python(path)
    assert "run" in symbols
    assert "class App" in symbols
    assert "_internal" in symbols
    assert imports >= 3
    assert pub_fns >= 1          # run, App — _internal is private
    assert has_docs is True
    assert "Entry point" in doc or "Run the app" in doc or "Main application" in doc


def test_extract_python_no_docstrings(repo: Path) -> None:
    path = repo / "src" / "utils.py"
    symbols, doc, imports, pub_fns, has_docs = _extract_python(path)
    assert "helper_a" in symbols
    assert "helper_b" in symbols
    assert has_docs is False
    assert doc == ""


def test_extract_python_syntax_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n    pass", encoding="utf-8")
    symbols, doc, imports, pub_fns, has_docs = _extract_python(bad)
    assert symbols == []
    assert has_docs is False


# ── _extract_ts_js ─────────────────────────────────────────────────────────


def test_extract_ts_js_symbols(repo: Path) -> None:
    path = repo / "src" / "api.ts"
    symbols, doc, imports, pub_fns, has_docs = _extract_ts_js(path)
    assert "getUser" in symbols or "UserService" in symbols
    assert imports >= 2
    assert has_docs is True
    assert "API service" in doc or "user management" in doc.lower()


def test_extract_ts_js_no_jsdoc(tmp_path: Path) -> None:
    f = tmp_path / "plain.js"
    f.write_text("function foo() {}\nconst bar = () => {};", encoding="utf-8")
    symbols, doc, imports, pub_fns, has_docs = _extract_ts_js(f)
    assert "foo" in symbols
    assert has_docs is False


# ── _score_documentability ────────────────────────────────────────────────


def test_score_high_for_entry_point_with_docstrings() -> None:
    unit = CodeUnit(
        path="src/main.py",
        language="python",
        size_bytes=500,
        line_count=50,
        symbols=["run", "class App"],
        docstring_preview="Entry point for the app.",
        import_count=5,
        public_function_count=3,
        has_docstrings=True,
    )
    score = _score_documentability(unit)
    assert score >= 6.0  # docstring(3) + imports(1) + fns(1.8) + entry_point(2)


def test_score_low_for_empty_file() -> None:
    unit = CodeUnit(
        path="src/empty.py",
        language="python",
        size_bytes=0,
        line_count=0,
        has_docstrings=False,
        import_count=0,
        public_function_count=0,
    )
    score = _score_documentability(unit)
    assert score == 0.0


def test_score_capped_at_ten() -> None:
    unit = CodeUnit(
        path="src/router.py",
        language="python",
        size_bytes=5000,
        line_count=200,
        symbols=[f"fn_{i}" for i in range(20)],
        has_docstrings=True,
        import_count=50,
        public_function_count=20,
    )
    score = _score_documentability(unit)
    assert score <= 10.0


# ── CodebaseAnalyzer ───────────────────────────────────────────────────────


def test_analyzer_basic(repo: Path) -> None:
    analyzer = CodebaseAnalyzer(embedding_fn=None)
    result = analyzer.analyze(str(repo))

    assert result.get("total_files", 0) >= 4
    assert result["language_distribution"].get("python", 0) >= 2
    assert result["language_distribution"].get("typescript", 0) >= 1


def test_analyzer_nonexistent_path() -> None:
    analyzer = CodebaseAnalyzer(embedding_fn=None)
    result = analyzer.analyze("/nonexistent/path/xyz")
    assert "error" in result


def test_analyzer_top_files_are_parsed_only(repo: Path) -> None:
    analyzer = CodebaseAnalyzer(embedding_fn=None)
    result = analyzer.analyze(str(repo))
    for f in result.get("top_files_to_document", []):
        assert f["language"] in {"python", "typescript", "javascript"}


def test_analyzer_main_py_in_top_files(repo: Path) -> None:
    analyzer = CodebaseAnalyzer(embedding_fn=None)
    result = analyzer.analyze(str(repo))
    top_paths = [f["path"] for f in result.get("top_files_to_document", [])]
    assert any("main.py" in p for p in top_paths)


def test_analyzer_with_embedding_fn(repo: Path) -> None:
    """Embedding fn provided — classification runs."""
    def fake_embed(texts: list[str]) -> list[list[float]]:
        # deterministic unit vectors for testing
        import math
        result = []
        for i, t in enumerate(texts):
            n = len(t) % 10 + 1
            vec = [math.sin(i + j) for j in range(16)]
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            result.append([x / norm for x in vec])
        return result

    analyzer = CodebaseAnalyzer(embedding_fn=fake_embed)
    result = analyzer.analyze(str(repo))
    # With embedding fn, category_distribution should be populated
    assert isinstance(result.get("category_distribution"), dict)


def test_analyzer_duplicate_detection(tmp_path: Path) -> None:
    """Two nearly identical files should be flagged as duplicates."""
    for name in ("service_a.py", "service_b.py"):
        (tmp_path / name).write_text(
            textwrap.dedent("""\
            \"\"\"User authentication service.\"\"\"
            import os

            def authenticate(user, password):
                \"\"\"Authenticate user with password.\"\"\"
                return True
            """),
            encoding="utf-8",
        )

    call_count = 0

    def fake_embed(texts: list[str]) -> list[list[float]]:
        nonlocal call_count
        call_count += 1
        # Return nearly identical vectors for both
        return [[1.0, 0.0, 0.0] for _ in texts]

    analyzer = CodebaseAnalyzer(embedding_fn=fake_embed)
    result = analyzer.analyze(str(tmp_path))
    # Two identical vectors → cosine similarity = 1.0 ≥ 0.92 threshold
    assert len(result.get("duplicate_clusters", [])) >= 1


# ── format_codebase_report ────────────────────────────────────────────────


def test_format_report_error() -> None:
    report = format_codebase_report({"error": "Not a directory"})
    assert "Error" in report
    assert "Not a directory" in report


def test_format_report_structure(repo: Path) -> None:
    analyzer = CodebaseAnalyzer(embedding_fn=None)
    result = analyzer.analyze(str(repo))
    report = format_codebase_report(result)

    assert "# Flaiwheel Cold-Start Report" in report
    assert "Language Distribution" in report
    assert "Top Files to Document First" in report
    assert "Recommended Next Steps" in report
    assert "zero tokens" in report.lower() or "zero-token" in report.lower() or "zero tokens" in report


def test_format_report_lists_main_py(repo: Path) -> None:
    analyzer = CodebaseAnalyzer(embedding_fn=None)
    result = analyzer.analyze(str(repo))
    report = format_codebase_report(result)
    assert "main.py" in report
