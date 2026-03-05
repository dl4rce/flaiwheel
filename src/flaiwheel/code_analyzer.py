# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.md.

"""
Cold-Start Codebase Analyzer.

Performs a zero-token, server-side structural analysis of a source code
directory. Designed to eliminate the expensive LLM agent file-reading loop
during cold-start onboarding of legacy codebases.

No new dependencies: uses Python's built-in `ast` module for Python files,
regex for TypeScript/JavaScript, and extension-based analysis for everything
else. Classification reuses the existing MiniLM embedding model already
loaded in the container.
"""
import ast
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .bootstrap import (
    DUPLICATE_THRESHOLD,
    _cosine_similarity,
)

# ── Constants ──────────────────────────────────────────────────────────────

_SKIP_DIRS: set[str] = {
    "node_modules", ".git", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "dist", "build", ".venv", "venv", "env", ".env",
    "vendor", "target", ".next", ".nuxt", "out", "coverage", ".tox",
    ".eggs", "*.egg-info",
}

_SKIP_EXTENSIONS: set[str] = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".exe", ".bin",
    ".jpg", ".jpeg", ".png", ".gif", ".ico", ".svg", ".webp", ".avif",
    ".mp3", ".mp4", ".wav", ".zip", ".tar", ".gz", ".tgz", ".lock",
    ".sum", ".woff", ".woff2", ".ttf", ".eot", ".map",
}

_PYTHON_EXTENSIONS: set[str] = {".py", ".pyi"}
_TS_JS_EXTENSIONS: set[str] = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}

_ENTRY_POINT_PATTERNS: tuple[str, ...] = (
    "main", "app", "index", "server", "router", "routes",
    "api", "handler", "controller", "service", "middleware",
    "gateway", "cli", "__main__",
)

# ── Code-specific category templates ──────────────────────────────────────
# Intentionally different from CATEGORY_TEMPLATES in bootstrap.py, which is
# tuned for documentation files. These describe what source *code* looks like.

_CODE_CATEGORY_TEMPLATES: dict[str, str] = {
    "api": (
        "HTTP route handler REST endpoint FastAPI Express router controller "
        "request response schema authentication middleware gateway service"
    ),
    "architecture": (
        "core service orchestrator dependency injection class hierarchy "
        "design pattern main entry point application bootstrap lifespan"
    ),
    "setup": (
        "configuration environment variable deployment Docker database "
        "connection string CLI entrypoint settings secrets credentials"
    ),
    "tests": (
        "test function assert mock fixture pytest jest describe it expect "
        "unit test integration test spec beforeEach afterEach"
    ),
    "best-practices": (
        "utility helper validation sanitization formatter shared constants "
        "common patterns reusable library type definitions interfaces"
    ),
    "bugfix-log": (
        "error handler exception retry logic fallback patch workaround "
        "traceback logging warning error recovery circuit breaker"
    ),
    "changelog": (
        "version history release notes migration breaking change upgrade "
        "CHANGELOG what is new deprecated removed added"
    ),
}

# ── Path-based heuristics (Option B) ──────────────────────────────────────
# Applied before the embedding classifier; high-confidence path signals
# override the nearest-centroid result.

_PATH_API_PATTERNS = (
    "route", "router", "routes", "handler", "controller", "endpoint",
    "api", "gateway", "service", "middleware", "main", "server", "app",
    "jump-host", "proxy",
)
_PATH_TEST_PATTERNS = ("test_", "_test", ".spec.", ".test.", "/tests/", "/test/", "/spec/")
_PATH_SETUP_PATTERNS = (
    "config", "settings", "env", "deploy", "docker", "makefile",
    "setup", "install", "migrate", "migration", "seed", "seed_",
)
_PATH_BEST_PRACTICE_PATTERNS = (
    "util", "utils", "helper", "helpers", "shared", "common",
    "lib", "types", "constants", "validators", "formatters",
)
_PATH_BUGFIX_PATTERNS = ("error", "exception", "retry", "fallback", "patch")
_PATH_SUPABASE_FUNCTION = "supabase/functions/"

# Extension → category for non-code "other" files
_EXT_CATEGORY: dict[str, str] = {
    # Config / infra
    ".yml": "setup", ".yaml": "setup", ".toml": "setup",
    ".env": "setup", ".ini": "setup", ".conf": "setup",
    ".cfg": "setup", ".properties": "setup", ".dockerfile": "setup",
    # Schema / data model
    ".sql": "architecture", ".prisma": "architecture",
    ".graphql": "architecture", ".gql": "architecture",
    ".proto": "architecture",
    # Docs / markdown handled by stem checks below
}

# Filenames (lowercased stem) that are definitively changelog
_CHANGELOG_STEMS = {"changelog", "changes", "history", "releases", "release-notes"}


def _code_path_hint(rel_path: str) -> str:
    """Return a high-confidence category based on file path/extension, or '' if unsure."""
    p = rel_path.lower().replace("\\", "/")
    stem = Path(rel_path).stem.lower()
    ext = Path(rel_path).suffix.lower()

    # Supabase edge functions are always API
    if _PATH_SUPABASE_FUNCTION in p:
        return "api"

    # Dockerfile / docker-compose by name
    if stem in ("dockerfile", "docker-compose", "compose"):
        return "setup"

    # Definitive changelog filenames
    if stem in _CHANGELOG_STEMS:
        return "changelog"

    # Test files
    if any(pat in p for pat in _PATH_TEST_PATTERNS):
        return "tests"

    # Extension-based for non-code files (covers all the "other" bucket)
    if ext in _EXT_CATEGORY:
        return _EXT_CATEGORY[ext]

    # Markdown: only flag as changelog if name matches, otherwise let embedding decide
    if ext == ".md":
        if stem in _CHANGELOG_STEMS:
            return "changelog"
        # docs/ or documentation/ dirs → architecture (high-level content)
        if "/docs/" in p or "/documentation/" in p or p.startswith("docs/") or p.startswith("documentation/"):
            return "architecture"
        return ""  # let embedding handle other markdown

    # Entry-point / API files by stem
    if any(stem == pat or stem.endswith(pat) or stem.startswith(pat)
           for pat in _PATH_API_PATTERNS):
        return "api"

    if any(pat in stem for pat in _PATH_SETUP_PATTERNS):
        return "setup"

    if any(pat in stem for pat in _PATH_BEST_PRACTICE_PATTERNS):
        return "best-practices"

    if any(pat in stem for pat in _PATH_BUGFIX_PATTERNS):
        return "bugfix-log"

    return ""


_PREVIEW_CHARS = 500
_MAX_FILE_SIZE = 500_000  # 500KB — skip very large generated files


# ── Data structures ────────────────────────────────────────────────────────

@dataclass
class CodeUnit:
    """Represents one analysed source file."""
    path: str                          # relative path from repo root
    language: str                      # "python", "typescript", "javascript", "other"
    size_bytes: int
    line_count: int
    symbols: list[str] = field(default_factory=list)   # function/class names
    docstring_preview: str = ""        # first docstring or comment block found
    import_count: int = 0
    public_function_count: int = 0
    has_docstrings: bool = False
    preview: str = ""                  # first 500 chars (fallback for non-parsed)
    category: str = "docs"
    category_confidence: float = 0.0
    documentability_score: float = 0.0


# ── Language parsers ───────────────────────────────────────────────────────

def _extract_python(path: Path) -> tuple[list[str], str, int, int, bool]:
    """Return (symbols, docstring_preview, import_count, public_fn_count, has_docstrings)."""
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return [], "", 0, 0, False

    symbols: list[str] = []
    docstring_preview = ""
    import_count = 0
    public_fn_count = 0
    has_docstrings = False

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(node.name)
            if not node.name.startswith("_"):
                public_fn_count += 1
            doc = ast.get_docstring(node)
            if doc and not docstring_preview:
                docstring_preview = doc[:300]
                has_docstrings = True
        elif isinstance(node, ast.ClassDef):
            symbols.append(f"class {node.name}")
            doc = ast.get_docstring(node)
            if doc and not docstring_preview:
                docstring_preview = doc[:300]
                has_docstrings = True
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            import_count += 1

    # Module-level docstring
    module_doc = ast.get_docstring(tree)
    if module_doc:
        has_docstrings = True
        if not docstring_preview:
            docstring_preview = module_doc[:300]

    return symbols, docstring_preview, import_count, public_fn_count, has_docstrings


_TS_SYMBOL_RE = re.compile(
    r"(?:export\s+)?(?:async\s+)?(?:function|class|interface|type|enum|const|let|var)\s+"
    r"([A-Za-z_$][A-Za-z0-9_$]*)"
)
_TS_IMPORT_RE = re.compile(r"^(?:import|require)\b", re.MULTILINE)
_TS_DOC_RE = re.compile(r"/\*\*\s*(.*?)\s*\*/", re.DOTALL)


def _extract_ts_js(path: Path) -> tuple[list[str], str, int, int, bool]:
    """Return (symbols, docstring_preview, import_count, public_fn_count, has_docstrings)."""
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return [], "", 0, 0, False

    symbols = _TS_SYMBOL_RE.findall(source[:50_000])
    import_count = len(_TS_IMPORT_RE.findall(source[:50_000]))
    public_fn_count = len([s for s in symbols if not s.startswith("_")])

    docstring_preview = ""
    has_docstrings = False
    m = _TS_DOC_RE.search(source[:10_000])
    if m:
        raw = re.sub(r"\s*\*\s*", " ", m.group(1)).strip()
        docstring_preview = raw[:300]
        has_docstrings = bool(docstring_preview)

    return symbols, docstring_preview, import_count, public_fn_count, has_docstrings


# ── Directory walker ───────────────────────────────────────────────────────

def _load_gitignore_patterns(root: Path) -> list[str]:
    """Read top-level .gitignore and return a list of simple patterns."""
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return []
    patterns: list[str] = []
    for line in gitignore.read_text(errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line.rstrip("/"))
    return patterns


def _is_gitignored(rel_path: str, patterns: list[str]) -> bool:
    parts = Path(rel_path).parts
    for pat in patterns:
        if pat in parts:
            return True
        if parts and parts[0] == pat:
            return True
    return False


def _walk_repo(root: Path) -> list[Path]:
    """Walk directory tree, skipping irrelevant dirs and file types."""
    gitignore_patterns = _load_gitignore_patterns(root)
    result: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        rel_dir = str(current.relative_to(root))

        # Prune skip dirs in-place so os.walk doesn't descend into them
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS
            and not d.startswith(".")
            and not _is_gitignored(str((current / d).relative_to(root)), gitignore_patterns)
        ]

        for fname in filenames:
            fpath = current / fname
            rel = str(fpath.relative_to(root))

            if _is_gitignored(rel, gitignore_patterns):
                continue
            if fpath.suffix.lower() in _SKIP_EXTENSIONS:
                continue
            try:
                if fpath.stat().st_size > _MAX_FILE_SIZE:
                    continue
            except OSError:
                continue

            result.append(fpath)

    return result


# ── Documentability scoring ────────────────────────────────────────────────

def _score_documentability(unit: CodeUnit) -> float:
    """Score 0-10: higher = more worth documenting."""
    score = 0.0
    if unit.has_docstrings:
        score += 3.0
    score += min(unit.import_count / 5, 2.0)
    score += min(unit.public_function_count, 5) * 0.6
    stem = Path(unit.path).stem.lower()
    if any(pat in stem for pat in _ENTRY_POINT_PATTERNS):
        score += 2.0
    return round(min(score, 10.0), 2)


# ── Nearest-centroid classifier ────────────────────────────────────────────

def _build_category_embeddings(
    embedding_fn: Callable[[list[str]], list[list[float]]],
) -> dict[str, list[float]]:
    cats = list(_CODE_CATEGORY_TEMPLATES.keys())
    texts = [_CODE_CATEGORY_TEMPLATES[c] for c in cats]
    try:
        vecs = embedding_fn(texts)
        return dict(zip(cats, vecs))
    except Exception:
        return {}


def _classify_unit(
    embedding: list[float],
    category_embeddings: dict[str, list[float]],
) -> tuple[str, float]:
    best_cat = "docs"
    best_sim = 0.0
    for cat, cat_emb in category_embeddings.items():
        sim = _cosine_similarity(embedding, cat_emb)
        if sim > best_sim:
            best_sim = sim
            best_cat = cat
    return best_cat, round(best_sim, 3)


# ── Main analyzer ──────────────────────────────────────────────────────────

class CodebaseAnalyzer:
    """Analyze a source code directory server-side at zero token cost.

    Reuses the existing MiniLM embedding function from the Flaiwheel
    registry — no new models, no new dependencies.
    """

    def __init__(self, embedding_fn: Optional[Callable] = None):
        self._embedding_fn = embedding_fn
        self._category_embeddings: dict[str, list[float]] = {}

    def _ensure_category_embeddings(self) -> None:
        if not self._category_embeddings and self._embedding_fn:
            self._category_embeddings = _build_category_embeddings(self._embedding_fn)

    def _embed_and_classify(
        self, units: list[CodeUnit],
    ) -> None:
        """Classify units: path heuristics first, embedding fallback for the rest."""
        # Pass 1 — path heuristics (zero-cost, high precision)
        needs_embedding: list[CodeUnit] = []
        for u in units:
            hint = _code_path_hint(u.path)
            if hint:
                u.category = hint
                u.category_confidence = 0.9
            else:
                needs_embedding.append(u)

        if not needs_embedding or not self._embedding_fn:
            return

        # Pass 2 — embedding nearest-centroid for remaining files
        self._ensure_category_embeddings()
        if not self._category_embeddings:
            return

        texts = []
        for u in needs_embedding:
            if u.docstring_preview:
                rep = f"{Path(u.path).stem} {u.docstring_preview}"
            elif u.symbols:
                rep = f"{Path(u.path).stem} " + " ".join(u.symbols[:10])
            else:
                rep = u.preview or Path(u.path).stem
            texts.append(rep[:500])

        try:
            all_vecs = self._embedding_fn(texts)
        except Exception:
            return

        for unit, vec in zip(needs_embedding, all_vecs):
            cat, conf = _classify_unit(vec, self._category_embeddings)
            unit.category = cat
            unit.category_confidence = conf

    def _detect_duplicates(
        self, units: list[CodeUnit],
    ) -> list[dict]:
        """Find semantically similar files using embedding cosine similarity."""
        if not self._embedding_fn or len(units) < 2:
            return []

        texts = []
        for u in units:
            if u.docstring_preview:
                rep = f"{Path(u.path).stem} {u.docstring_preview}"
            elif u.symbols:
                rep = f"{Path(u.path).stem} " + " ".join(u.symbols[:10])
            else:
                rep = u.preview or Path(u.path).stem
            texts.append(rep[:500])

        try:
            vecs = self._embedding_fn(texts)
        except Exception:
            return []

        paths = [u.path for u in units]
        used: set[int] = set()
        duplicates: list[dict] = []

        for i in range(len(paths)):
            if i in used:
                continue
            cluster_indices = [i]
            cluster_sims: list[float] = []
            for j in range(i + 1, len(paths)):
                if j in used:
                    continue
                sim = _cosine_similarity(vecs[i], vecs[j])
                if sim >= DUPLICATE_THRESHOLD:
                    cluster_indices.append(j)
                    cluster_sims.append(round(sim, 3))
            if len(cluster_indices) > 1:
                for idx in cluster_indices:
                    used.add(idx)
                avg_sim = round(sum(cluster_sims) / len(cluster_sims), 3)
                duplicates.append({
                    "files": [paths[idx] for idx in cluster_indices],
                    "similarity": avg_sim,
                })

        return duplicates

    def analyze(self, path: str) -> dict:
        """Run full analysis on a source directory.

        Args:
            path: Absolute path to the project/source directory.

        Returns:
            Structured analysis result dict.
        """
        root = Path(path).resolve()
        if not root.exists() or not root.is_dir():
            return {"error": f"Path does not exist or is not a directory: {path}"}

        all_files = _walk_repo(root)

        units: list[CodeUnit] = []
        lang_counts: dict[str, int] = {}

        for fpath in all_files:
            rel = str(fpath.relative_to(root))
            suffix = fpath.suffix.lower()

            try:
                size = fpath.stat().st_size
            except OSError:
                continue

            if suffix in _PYTHON_EXTENSIONS:
                lang = "python"
                symbols, doc_preview, imports, pub_fns, has_docs = _extract_python(fpath)
                try:
                    lines = fpath.read_text(encoding="utf-8", errors="ignore").count("\n")
                except OSError:
                    lines = 0
                preview = doc_preview or (", ".join(symbols[:5]) if symbols else "")
            elif suffix in _TS_JS_EXTENSIONS:
                lang = "typescript" if suffix in {".ts", ".tsx"} else "javascript"
                symbols, doc_preview, imports, pub_fns, has_docs = _extract_ts_js(fpath)
                try:
                    lines = fpath.read_text(encoding="utf-8", errors="ignore").count("\n")
                except OSError:
                    lines = 0
                preview = doc_preview or (", ".join(symbols[:5]) if symbols else "")
            else:
                lang = "other"
                symbols, doc_preview, imports, pub_fns, has_docs = [], "", 0, 0, False
                try:
                    raw = fpath.read_text(encoding="utf-8", errors="ignore")
                    lines = raw.count("\n")
                    preview = raw[:_PREVIEW_CHARS].strip()
                except (OSError, UnicodeDecodeError):
                    lines = 0
                    preview = ""

            lang_counts[lang] = lang_counts.get(lang, 0) + 1

            unit = CodeUnit(
                path=rel,
                language=lang,
                size_bytes=size,
                line_count=lines,
                symbols=symbols,
                docstring_preview=doc_preview,
                import_count=imports,
                public_function_count=pub_fns,
                has_docstrings=has_docs,
                preview=preview,
            )
            unit.documentability_score = _score_documentability(unit)
            units.append(unit)

        # Embed + classify (reuses existing MiniLM, zero new deps)
        self._embed_and_classify(units)

        # Score documentability after classification
        for unit in units:
            unit.documentability_score = _score_documentability(unit)

        # Sort by documentability descending
        units.sort(key=lambda u: u.documentability_score, reverse=True)

        # Duplicate detection (only for parsed files with meaningful content)
        parsed_units = [u for u in units if u.language in {"python", "typescript", "javascript"}]
        duplicates = self._detect_duplicates(parsed_units)

        # Coverage gaps: directories with only "other" files (no parsed code)
        dirs_with_code: set[str] = set()
        dirs_all: set[str] = set()
        for u in units:
            parent = str(Path(u.path).parent)
            dirs_all.add(parent)
            if u.language != "other":
                dirs_with_code.add(parent)
        undocumented_dirs = sorted(dirs_all - dirs_with_code - {"."})

        # Category distribution
        cat_dist: dict[str, int] = {}
        for u in units:
            cat_dist[u.category] = cat_dist.get(u.category, 0) + 1

        total_lines = sum(u.line_count for u in units)
        total_files = len(units)
        parsed_count = len(parsed_units)

        return {
            "root": str(root),
            "total_files": total_files,
            "total_lines": total_lines,
            "parsed_files": parsed_count,
            "language_distribution": lang_counts,
            "category_distribution": cat_dist,
            "top_files_to_document": [
                {
                    "path": u.path,
                    "language": u.language,
                    "score": u.documentability_score,
                    "category": u.category,
                    "symbols": u.symbols[:5],
                    "import_count": u.import_count,
                    "line_count": u.line_count,
                    "has_docstrings": u.has_docstrings,
                }
                for u in units[:20]
                if u.language != "other"
            ],
            "all_units": [
                {
                    "path": u.path,
                    "language": u.language,
                    "category": u.category,
                    "score": u.documentability_score,
                    "line_count": u.line_count,
                }
                for u in units
            ],
            "duplicate_clusters": duplicates,
            "undocumented_dirs": undocumented_dirs[:20],
        }


# ── Report formatter ───────────────────────────────────────────────────────

def format_codebase_report(result: dict) -> str:
    """Render the analysis result as a markdown bootstrap report."""
    if "error" in result:
        return f"**Error:** {result['error']}"

    root = result.get("root", "")
    total_files = result.get("total_files", 0)
    total_lines = result.get("total_lines", 0)
    parsed = result.get("parsed_files", 0)
    lang_dist = result.get("language_distribution", {})
    cat_dist = result.get("category_distribution", {})
    top_files = result.get("top_files_to_document", [])
    duplicates = result.get("duplicate_clusters", [])
    undoc_dirs = result.get("undocumented_dirs", [])

    lines = [
        "# Flaiwheel Cold-Start Report\n",
        f"**Project:** `{root}`  ",
        f"**Files scanned:** {total_files}  ",
        f"**Lines of code:** {total_lines:,}  ",
        f"**Parsed (Python/TS/JS):** {parsed}  \n",
    ]

    if lang_dist:
        lines.append("## Language Distribution\n")
        for lang, count in sorted(lang_dist.items(), key=lambda x: -x[1]):
            lines.append(f"- **{lang}**: {count} files")
        lines.append("")

    if cat_dist:
        lines.append("## Inferred Category Distribution\n")
        for cat, count in sorted(cat_dist.items(), key=lambda x: -x[1]):
            lines.append(f"- **{cat}**: {count} files")
        lines.append("")

    if top_files:
        lines.append("## Top Files to Document First\n")
        lines.append(
            "*Ranked by documentability: has docstrings, import density, "
            "public API surface, entry-point patterns.*\n"
        )
        lines.append("| # | File | Lang | Score | Category | Symbols | Lines |")
        lines.append("|---|------|------|-------|----------|---------|-------|")
        for i, f in enumerate(top_files, 1):
            syms = ", ".join(f.get("symbols", []))[:40] or "—"
            lines.append(
                f"| {i} | `{f['path']}` | {f['language']} | {f['score']} "
                f"| {f['category']} | {syms} | {f['line_count']} |"
            )
        lines.append("")

    if duplicates:
        lines.append("## Potential Duplicate Files\n")
        lines.append(
            "*Files with high semantic similarity — consider merging or reviewing.*\n"
        )
        for d in duplicates:
            files_str = ", ".join(f"`{f}`" for f in d["files"])
            lines.append(f"- **{d['similarity']:.0%}** similarity: {files_str}")
        lines.append("")

    if undoc_dirs:
        lines.append("## Directories With No Parsed Code\n")
        lines.append("*These directories contain only config/static/other files.*\n")
        for d in undoc_dirs[:10]:
            lines.append(f"- `{d}/`")
        lines.append("")

    lines.append("## Recommended Next Steps\n")
    lines.append(
        "1. Use the **Top Files to Document First** table above to prioritize\n"
        "2. For each top file, ask your AI agent to read it and call the "
        "appropriate `write_*()` Flaiwheel tool\n"
        "3. For duplicate pairs, merge content and write once\n"
        "4. Run `classify_documents()` for any existing `.md` docs in the repo\n"
        "5. Run `reindex()` after writing all docs\n"
    )
    lines.append(
        "*Generated by Flaiwheel Cold-Start Analyzer — zero tokens, zero cloud.*"
    )

    return "\n".join(lines)
