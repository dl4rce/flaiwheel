# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.md.

"""
Knowledge Base Bootstrap & Cleanup – analyses a messy docs repo,
classifies documents, detects duplicates, and proposes a cleanup plan.

All analysis is READ-ONLY.  Execution requires explicit user approval
and NEVER deletes files – only mkdir + git mv.
"""
import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .quality import EXPECTED_DIRS, _detect_category
from .readers import SUPPORTED_EXTENSIONS, extract_text

CATEGORY_TEMPLATES: dict[str, str] = {
    "architecture": (
        "Software architecture design decisions, system components, "
        "data flow diagrams, technology stack choices, design patterns"
    ),
    "api": (
        "API endpoint documentation, REST HTTP methods, request response schemas, "
        "authentication headers, rate limits, GraphQL queries"
    ),
    "bugfix-log": (
        "Bug report, root cause analysis, solution, fix, lesson learned, "
        "error trace, stack trace, debugging, regression"
    ),
    "best-practices": (
        "Coding standards, style guide, best practices, conventions, "
        "linting rules, code review checklist, naming conventions"
    ),
    "setup": (
        "Installation setup deployment configuration, environment variables, "
        "Docker compose, CI/CD pipeline, infrastructure provisioning"
    ),
    "changelog": (
        "Release notes, version changelog, what's new, breaking changes, "
        "migration guide, upgrade instructions, release date"
    ),
    "tests": (
        "Test case scenario, test steps, expected result, preconditions, "
        "regression test, integration test, unit test, QA"
    ),
}

CATEGORY_KEYWORDS: dict[str, list[list[str]]] = {
    "bugfix-log": [
        ["root cause", "solution"],
        ["bug", "fix"],
        ["error", "trace", "fix"],
    ],
    "api": [
        ["endpoint", "request"],
        ["endpoint", "response"],
        ["rest", "http"],
    ],
    "architecture": [
        ["architecture", "design"],
        ["system", "component", "diagram"],
        ["design decision"],
        ["technology stack"],
    ],
    "setup": [
        ["install", "setup"],
        ["deploy", "configuration"],
        ["docker", "compose"],
        ["environment", "variable"],
    ],
    "changelog": [
        ["version", "release"],
        ["changelog"],
        ["breaking change"],
    ],
    "best-practices": [
        ["best practice"],
        ["coding standard"],
        ["convention"],
        ["style guide"],
    ],
    "tests": [
        ["test case", "scenario"],
        ["test", "expected result"],
        ["regression test"],
    ],
}

EMBED_PREVIEW_CHARS = 2000
DUPLICATE_THRESHOLD = 0.92

ROOT_WHITELIST = {"README.md", "FLAIWHEEL_TOOLS.md"}

CAT_TO_DIR: dict[str, str] = {
    "architecture": "architecture",
    "api": "api",
    "bugfix-log": "bugfix-log",
    "bugfix": "bugfix-log",
    "best-practices": "best-practices",
    "best-practice": "best-practices",
    "setup": "setup",
    "changelog": "changelog",
    "tests": "tests",
    "test": "tests",
}


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass
class FileInfo:
    path: str
    abs_path: Path
    size_bytes: int
    format: str
    content_preview: str
    has_headings: bool
    heading_count: int
    word_count: int
    category_by_path: str
    category_by_content: str = ""
    category_by_embedding: str = ""
    embedding_confidence: float = 0.0
    detected_category: str = ""
    confidence: float = 0.0
    quality_issues: list[str] = field(default_factory=list)


class KnowledgeBootstrap:
    """Analyse and bootstrap a messy knowledge repository.

    HARD SAFEGUARDS:
    - analyze() is completely read-only
    - execute() NEVER deletes any file
    - execute() only runs actions the user explicitly approved
    - All file moves use 'git mv' to preserve history
    """

    def __init__(self, docs_path: Path, embedding_fn=None, quality_checker=None):
        self.docs_path = docs_path
        self.ef = embedding_fn
        self.quality_checker = quality_checker
        self._report: Optional[dict] = None
        self._category_embeddings: Optional[dict[str, list[float]]] = None

    # ── Phase 1: Scan ──────────────────────────────────

    def _scan_files(self) -> list[FileInfo]:
        files: list[FileInfo] = []
        seen: set[Path] = set()

        for ext in sorted(SUPPORTED_EXTENSIONS):
            for p in self.docs_path.rglob(f"*{ext}"):
                if p in seen:
                    continue
                seen.add(p)
                try:
                    content = extract_text(p)
                except Exception:
                    content = None
                if content is None:
                    continue

                rel_path = str(p.relative_to(self.docs_path))
                headings = re.findall(r"^#{1,6}\s+", content, re.MULTILINE)

                fi = FileInfo(
                    path=rel_path,
                    abs_path=p,
                    size_bytes=p.stat().st_size,
                    format=p.suffix.lower(),
                    content_preview=content[:EMBED_PREVIEW_CHARS],
                    has_headings=bool(headings),
                    heading_count=len(headings),
                    word_count=len(content.split()),
                    category_by_path=_detect_category(rel_path),
                )

                if self.quality_checker:
                    try:
                        issues = self.quality_checker.check_file(p, rel_path)
                        fi.quality_issues = [i["message"] for i in issues]
                    except Exception:
                        pass

                files.append(fi)

        return files

    # ── Phase 2: Classify ──────────────────────────────

    @staticmethod
    def _classify_by_content(fi: FileInfo) -> tuple[str, float]:
        text_lower = fi.content_preview.lower()
        best_cat = "docs"
        best_score = 0.0

        for category, patterns in CATEGORY_KEYWORDS.items():
            for keyword_group in patterns:
                if all(kw in text_lower for kw in keyword_group):
                    score = len(keyword_group) * 0.25
                    if score > best_score:
                        best_score = min(score, 0.9)
                        best_cat = category

        return best_cat, best_score

    def _compute_category_embeddings(self):
        if self._category_embeddings is not None:
            return
        if self.ef is None:
            self._category_embeddings = {}
            return

        cats = list(CATEGORY_TEMPLATES.keys())
        texts = [CATEGORY_TEMPLATES[c] for c in cats]
        try:
            embeddings = self.ef(texts)
            self._category_embeddings = dict(zip(cats, embeddings))
        except Exception as e:
            print(f"Bootstrap: failed to compute category embeddings: {e}")
            self._category_embeddings = {}

    def _classify_by_embedding(self, embedding: list[float]) -> tuple[str, float]:
        if not self._category_embeddings:
            return "docs", 0.0

        best_cat = "docs"
        best_sim = 0.0

        for cat, cat_emb in self._category_embeddings.items():
            sim = _cosine_similarity(embedding, cat_emb)
            if sim > best_sim:
                best_sim = sim
                best_cat = cat

        return best_cat, round(best_sim, 3)

    @staticmethod
    def _consensus_category(fi: FileInfo) -> tuple[str, float]:
        path_cat = fi.category_by_path
        content_cat = fi.category_by_content
        embed_cat = fi.category_by_embedding
        embed_conf = fi.embedding_confidence

        if path_cat != "docs":
            return path_cat, 0.95

        if content_cat != "docs" and content_cat == embed_cat:
            return content_cat, min(0.85 + embed_conf * 0.1, 0.95)

        if content_cat != "docs":
            return content_cat, 0.65

        if embed_cat != "docs" and embed_conf > 0.4:
            return embed_cat, round(embed_conf * 0.7, 2)

        return "docs", 0.3

    # ── Phase 3: Detect duplicates ─────────────────────

    @staticmethod
    def _detect_duplicates(
        files: list[FileInfo], embeddings: dict[str, list[float]],
    ) -> list[dict]:
        paths = [fi.path for fi in files if fi.path in embeddings]
        if len(paths) < 2:
            return []

        clusters: list[dict] = []
        used: set[str] = set()

        for i in range(len(paths)):
            if paths[i] in used:
                continue
            cluster_files = [paths[i]]
            cluster_sims: list[float] = []

            for j in range(i + 1, len(paths)):
                if paths[j] in used:
                    continue
                sim = _cosine_similarity(
                    embeddings[paths[i]], embeddings[paths[j]],
                )
                if sim >= DUPLICATE_THRESHOLD:
                    cluster_files.append(paths[j])
                    cluster_sims.append(round(sim, 3))

            if len(cluster_files) > 1:
                avg_sim = round(sum(cluster_sims) / len(cluster_sims), 3)
                for f in cluster_files:
                    used.add(f)
                clusters.append({
                    "similarity": avg_sim,
                    "files": cluster_files,
                    "suggestion": f"Review and merge into {cluster_files[0]}",
                })

        return clusters

    # ── Phase 4: Generate plan ─────────────────────────

    def _generate_actions(
        self, files: list[FileInfo], duplicates: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        actions: list[dict] = []
        needs_rewrite: list[dict] = []
        action_id = 0

        existing_dirs = {
            d.name for d in self.docs_path.iterdir() if d.is_dir()
        }
        for dirname in EXPECTED_DIRS:
            if dirname not in existing_dirs:
                action_id += 1
                actions.append({
                    "id": f"a{action_id}",
                    "type": "create_dir",
                    "path": f"{dirname}/",
                    "reason": "Standard knowledge base directory",
                })

        expected_set = set(EXPECTED_DIRS)
        for fi in files:
            rel = Path(fi.path)
            parts = rel.parts
            is_root_file = len(parts) == 1
            is_in_wrong_dir = len(parts) > 1 and parts[0] not in expected_set
            is_correctly_placed = len(parts) > 1 and parts[0] in expected_set

            if is_correctly_placed:
                continue

            if is_root_file and fi.path in ROOT_WHITELIST:
                continue

            target_dir = CAT_TO_DIR.get(fi.detected_category, "")
            if not target_dir:
                continue

            if is_root_file or is_in_wrong_dir:
                dest = f"{target_dir}/{rel.name}"
                if dest != fi.path:
                    action_id += 1
                    actions.append({
                        "id": f"a{action_id}",
                        "type": "move",
                        "from": fi.path,
                        "to": dest,
                        "reason": (
                            f"Classified as '{fi.detected_category}' "
                            f"(confidence: {fi.confidence:.0%})"
                        ),
                    })

            if (
                not fi.has_headings
                and fi.word_count > 50
                and fi.format == ".md"
            ):
                needs_rewrite.append({
                    "file": fi.path,
                    "reason": "No headings or structure — needs reorganization",
                    "detected_category": fi.detected_category,
                })

        for dup in duplicates:
            action_id += 1
            actions.append({
                "id": f"a{action_id}",
                "type": "flag_review",
                "files": dup["files"],
                "similarity": dup["similarity"],
                "reason": (
                    f"Near-duplicate files (similarity: {dup['similarity']:.0%}). "
                    f"{dup['suggestion']}"
                ),
            })

        return actions, needs_rewrite

    # ── Public API ─────────────────────────────────────

    def analyze(self) -> dict:
        """Run full analysis. Read-only, safe to call anytime.

        IMPORTANT: This method NEVER modifies or deletes any files.
        """
        if not self.docs_path.exists():
            return {
                "summary": {"total_files": 0, "error": "Docs path does not exist"},
                "file_inventory": [],
                "duplicate_clusters": [],
                "proposed_actions": [],
                "needs_ai_rewrite": [],
            }

        files = self._scan_files()
        if not files:
            return {
                "summary": {
                    "total_files": 0, "supported_files": 0,
                    "quality_score_before": 100, "quality_score_projected": 100,
                },
                "file_inventory": [],
                "duplicate_clusters": [],
                "proposed_actions": [],
                "needs_ai_rewrite": [],
            }

        for fi in files:
            cat, _ = self._classify_by_content(fi)
            fi.category_by_content = cat

        file_embeddings: dict[str, list[float]] = {}
        if self.ef:
            self._compute_category_embeddings()
            previews = [fi.content_preview for fi in files]
            try:
                all_embeddings = self.ef(previews)
                for fi, emb in zip(files, all_embeddings):
                    file_embeddings[fi.path] = emb
                    cat, conf = self._classify_by_embedding(emb)
                    fi.category_by_embedding = cat
                    fi.embedding_confidence = conf
            except Exception as e:
                print(f"Bootstrap: embedding classification failed: {e}")

        for fi in files:
            cat, conf = self._consensus_category(fi)
            fi.detected_category = cat
            fi.confidence = conf

        duplicates = self._detect_duplicates(files, file_embeddings)

        quality_before = 100
        if self.quality_checker:
            try:
                qr = self.quality_checker.check_all()
                quality_before = qr.get("score", 100)
            except Exception:
                pass

        actions, needs_rewrite = self._generate_actions(files, duplicates)

        action_map: dict[str, dict] = {}
        for a in actions:
            if a["type"] == "move":
                action_map[a["from"]] = a

        inventory = []
        for fi in files:
            entry: dict = {
                "path": fi.path,
                "size_bytes": fi.size_bytes,
                "format": fi.format,
                "word_count": fi.word_count,
                "has_headings": fi.has_headings,
                "detected_category": fi.detected_category,
                "confidence": round(fi.confidence, 2),
                "quality_issues": fi.quality_issues,
            }
            move = action_map.get(fi.path)
            if move:
                entry["proposed_action"] = "move"
                entry["proposed_destination"] = move["to"]
            inventory.append(entry)

        move_count = sum(1 for a in actions if a["type"] == "move")
        dir_count = sum(1 for a in actions if a["type"] == "create_dir")
        projected_improvement = min(move_count * 2 + dir_count * 1, 30)
        quality_projected = min(quality_before + projected_improvement, 100)

        report = {
            "summary": {
                "total_files": len(files),
                "supported_files": len(files),
                "categories_detected": len({fi.detected_category for fi in files}),
                "files_misplaced": move_count,
                "duplicate_clusters": len(duplicates),
                "dirs_to_create": dir_count,
                "files_need_rewrite": len(needs_rewrite),
                "quality_score_before": quality_before,
                "quality_score_projected": quality_projected,
                "total_actions": len(actions),
            },
            "file_inventory": inventory,
            "duplicate_clusters": duplicates,
            "proposed_actions": actions,
            "needs_ai_rewrite": needs_rewrite,
        }

        self._report = report
        return report

    @property
    def last_report(self) -> Optional[dict]:
        return self._report

    def execute(self, action_ids: list[str]) -> dict:
        """Execute approved actions. NEVER deletes files.

        HARD SAFEGUARDS:
        - Only mkdir and git mv operations
        - No file content is modified
        - No file is ever deleted
        - Returns rollback command for easy undo
        """
        if not self._report:
            return {"status": "error", "message": "No analysis report. Run analyze() first."}

        actions_by_id = {a["id"]: a for a in self._report["proposed_actions"]}
        results: list[dict] = []
        errors: list[str] = []

        rollback_hash = ""
        try:
            r = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=str(self.docs_path),
            )
            if r.returncode == 0:
                rollback_hash = r.stdout.strip()
        except Exception:
            pass

        for aid in action_ids:
            action = actions_by_id.get(aid)
            if action is None:
                errors.append(f"Unknown action ID: {aid}")
                continue

            try:
                if action["type"] == "create_dir":
                    dirpath = self.docs_path / action["path"]
                    dirpath.mkdir(parents=True, exist_ok=True)
                    readme = dirpath / "README.md"
                    if not readme.exists():
                        category = action["path"].rstrip("/")
                        readme.write_text(
                            f"# {category.replace('-', ' ').title()}\n\n"
                            f"Documentation for {category}.\n",
                            encoding="utf-8",
                        )
                    results.append({"id": aid, "status": "ok", "type": "create_dir"})

                elif action["type"] == "move":
                    src = self.docs_path / action["from"]
                    dst = self.docs_path / action["to"]
                    if not src.exists():
                        errors.append(f"Source not found: {action['from']}")
                        continue
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    r = subprocess.run(
                        ["git", "mv", str(src), str(dst)],
                        capture_output=True, text=True, timeout=10,
                        cwd=str(self.docs_path),
                    )
                    if r.returncode != 0:
                        src.rename(dst)
                    results.append({
                        "id": aid, "status": "ok", "type": "move",
                        "from": action["from"], "to": action["to"],
                    })

                elif action["type"] == "flag_review":
                    results.append({
                        "id": aid, "status": "flagged", "type": "flag_review",
                        "message": "Flagged for AI agent review",
                    })

            except Exception as e:
                errors.append(f"Action {aid} failed: {e}")

        commit_hash = ""
        moved = [r for r in results if r.get("type") == "move"]
        created = [r for r in results if r.get("type") == "create_dir"]
        if moved or created:
            try:
                subprocess.run(
                    ["git", "add", "-A"],
                    capture_output=True, timeout=10,
                    cwd=str(self.docs_path),
                )
                msg = (
                    f"Bootstrap cleanup: {len(moved)} file(s) moved, "
                    f"{len(created)} dir(s) created"
                )
                subprocess.run(
                    ["git", "commit", "-m", msg],
                    capture_output=True, text=True, timeout=15,
                    cwd=str(self.docs_path),
                )
                r = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True, text=True, timeout=5,
                    cwd=str(self.docs_path),
                )
                if r.returncode == 0:
                    commit_hash = r.stdout.strip()
            except Exception:
                pass

        return {
            "status": "ok" if not errors else "partial",
            "executed": len(results),
            "errors": errors,
            "results": results,
            "rollback_hash": rollback_hash,
            "commit_hash": commit_hash,
            "rollback_command": (
                f"git revert {commit_hash}" if commit_hash else
                f"git reset --hard {rollback_hash}" if rollback_hash else
                "Manual rollback required"
            ),
        }


def format_report(report: dict) -> str:
    """Format an analysis report as readable text for MCP tool output."""
    s = report.get("summary", {})
    if s.get("error"):
        return f"Error: {s['error']}"
    if s.get("total_files", 0) == 0:
        return "No supported files found in the knowledge repository."

    lines = [
        "## \"This is the Way\" — Knowledge Base Analysis Report\n",
        f"**Files scanned:** {s['total_files']}",
        f"**Categories detected:** {s['categories_detected']}",
        f"**Quality score (current):** {s['quality_score_before']}/100",
        f"**Quality score (projected after cleanup):** {s['quality_score_projected']}/100\n",
        f"**Files misplaced:** {s['files_misplaced']}",
        f"**Directories to create:** {s['dirs_to_create']}",
        f"**Duplicate clusters:** {s['duplicate_clusters']}",
        f"**Files needing AI rewrite:** {s['files_need_rewrite']}",
        f"**Total proposed actions:** {s['total_actions']}\n",
    ]

    actions = report.get("proposed_actions", [])
    if actions:
        lines.append("### Proposed Actions\n")
        for a in actions:
            if a["type"] == "create_dir":
                lines.append(f"- **{a['id']}** CREATE `{a['path']}` — {a['reason']}")
            elif a["type"] == "move":
                lines.append(
                    f"- **{a['id']}** MOVE `{a['from']}` → `{a['to']}` — {a['reason']}"
                )
            elif a["type"] == "flag_review":
                files_str = ", ".join(f"`{f}`" for f in a.get("files", []))
                lines.append(f"- **{a['id']}** REVIEW {files_str} — {a['reason']}")
        lines.append("")

    dups = report.get("duplicate_clusters", [])
    if dups:
        lines.append("### Near-Duplicate Clusters\n")
        for d in dups:
            files_str = ", ".join(f"`{f}`" for f in d["files"])
            lines.append(f"- Similarity {d['similarity']:.0%}: {files_str}")
        lines.append("")

    rewrites = report.get("needs_ai_rewrite", [])
    if rewrites:
        lines.append("### Files Needing AI Rewrite\n")
        for r in rewrites:
            lines.append(f"- `{r['file']}` — {r['reason']} (category: {r['detected_category']})")
        lines.append("")

    if actions:
        ids = ", ".join(a["id"] for a in actions)
        lines.append(
            "### Next Steps — I have spoken\n"
            "Review the actions above and call:\n"
            f"  `execute_cleanup(actions=\"{ids}\")` — to execute all\n"
            "  `execute_cleanup(actions=\"a1,a3\")` — to execute specific actions\n"
            "\nFor files needing AI rewrite, read the file and use the "
            "appropriate `write_*` tool to create a structured version.\n"
            "After cleanup, call `reindex()` to rebuild the search index.\n"
            "\n*The answer is 42. The question was: how do you clean up a messy repo?*"
        )

    return "\n".join(lines)
