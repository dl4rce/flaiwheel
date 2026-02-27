# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.md.

"""
Knowledge quality checker – validates the docs repo for
consistency, completeness, and structural correctness.

Designed to be called by AI agents via MCP or from the Web UI.
Issues have severity levels: critical, warning, info.
Quality score starts at 100 and decreases per issue.
"""
import re
from pathlib import Path
from .config import Config
from .readers import SUPPORTED_EXTENSIONS

EXPECTED_DIRS = [
    "architecture",
    "api",
    "bugfix-log",
    "best-practices",
    "setup",
    "changelog",
    "tests",
]

BUGFIX_REQUIRED_SECTIONS = ["Root Cause", "Solution", "Lesson Learned"]
TEST_REQUIRED_SECTIONS = ["Scenario", "Steps", "Expected Result"]

SEVERITY_PENALTY = {"critical": 10, "warning": 2, "info": 0}
MAX_DEDUCTION = {"critical": 60, "warning": 30, "info": 0}


class KnowledgeQualityChecker:
    def __init__(self, config: Config):
        self.config = config

    def check_all(self) -> dict:
        docs = Path(self.config.docs_path)
        if not docs.exists():
            return {
                "score": 0,
                "total_issues": 1,
                "issues": [_issue("critical", str(docs), "Docs path does not exist")],
            }

        issues: list[dict] = []
        issues.extend(self._check_structure(docs))
        issues.extend(self._check_completeness(docs))
        issues.extend(self._check_bugfix_format(docs))
        issues.extend(self._check_heading_structure(docs))
        issues.extend(self._check_orphans(docs))

        deductions: dict[str, int] = {}
        for issue in issues:
            sev = issue["severity"]
            penalty = SEVERITY_PENALTY.get(sev, 0)
            deductions[sev] = deductions.get(sev, 0) + penalty

        score = 100
        for sev, total in deductions.items():
            cap = MAX_DEDUCTION.get(sev, 100)
            score -= min(total, cap)
        score = max(0, score)

        return {
            "score": score,
            "total_issues": len(issues),
            "critical": sum(1 for i in issues if i["severity"] == "critical"),
            "warnings": sum(1 for i in issues if i["severity"] == "warning"),
            "info": sum(1 for i in issues if i["severity"] == "info"),
            "issues": issues,
        }

    def check_file(self, filepath: Path, rel_path: str) -> list[dict]:
        """Check a single file for quality issues. Returns list of issues.
        IMPORTANT: This method NEVER modifies or deletes the file."""
        issues: list[dict] = []
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return issues

        # Skip directory placeholder READMEs from quality checks
        if Path(rel_path).name == "README.md" and len(Path(rel_path).parts) == 2:
            return issues

        category = _detect_category(rel_path)
        issues.extend(self._check_single_completeness(content, rel_path))
        issues.extend(self._check_single_headings(content, rel_path))
        if category == "bugfix":
            issues.extend(self._check_single_bugfix(content, rel_path))
        if category == "test":
            issues.extend(self._check_single_test(content, rel_path))
        return issues

    def check_content(self, content: str, category: str = "docs") -> list[dict]:
        """Validate raw markdown content against quality rules.
        Used by validate_doc() MCP tool for pre-commit checks.
        IMPORTANT: This method NEVER modifies or deletes any files."""
        issues: list[dict] = []
        fake_path = f"{category}/validate-preview.md"
        issues.extend(self._check_single_completeness(content, fake_path))
        issues.extend(self._check_single_headings(content, fake_path))
        if category == "bugfix":
            issues.extend(self._check_single_bugfix(content, fake_path))
        if category == "test":
            issues.extend(self._check_single_test(content, fake_path))
        return issues

    def _check_single_completeness(self, content: str, rel: str) -> list[dict]:
        issues = []
        text = _strip_markdown_overhead(content)
        if len(text) < 30:
            issues.append(_issue(
                "warning", rel,
                "File is nearly empty (< 30 chars of content).",
            ))
        elif len(text) < 100:
            issues.append(_issue(
                "info", rel,
                "File is very short (< 100 chars). Consider adding more detail.",
            ))
        return issues

    def _check_single_headings(self, content: str, rel: str) -> list[dict]:
        issues = []
        cleaned = _strip_code_blocks(content)
        headings = re.findall(r"^(#{1,6})\s+", cleaned, re.MULTILINE)
        if not headings:
            issues.append(_issue(
                "info", rel, "File has no headings. Add at least a # title.",
            ))
            return issues
        if len(headings[0]) > 1:
            issues.append(_issue(
                "info", rel,
                f"First heading is level {len(headings[0])}. Start with a # (h1) title.",
            ))
        seen_levels = {len(headings[0])}
        for i in range(1, len(headings)):
            curr_level = len(headings[i])
            if curr_level not in seen_levels and all(
                lvl < curr_level - 1 or lvl >= curr_level
                for lvl in seen_levels
            ):
                prev_max = max(l for l in seen_levels if l < curr_level)
                issues.append(_issue(
                    "info", rel,
                    f"Heading level jumps from h{prev_max} to h{curr_level}.",
                ))
                break
            seen_levels.add(curr_level)
        return issues

    def _check_single_bugfix(self, content: str, rel: str) -> list[dict]:
        issues = []
        for section in BUGFIX_REQUIRED_SECTIONS:
            pattern = rf"^##\s+[\*_\s]*(?:\S+\s+)?{re.escape(section)}"
            if not re.search(pattern, content, re.MULTILINE | re.IGNORECASE):
                issues.append(_issue(
                    "critical", rel,
                    f"Bugfix entry missing required section: '## {section}'.",
                ))
        h2_sections = _split_h2_sections(content)
        for heading, body in h2_sections:
            measured = _strip_markdown_overhead(body)
            if len(measured) < 20:
                issues.append(_issue(
                    "warning", rel,
                    f"Section '## {heading}' has very little content.",
                ))
        return issues

    def _check_single_test(self, content: str, rel: str) -> list[dict]:
        issues = []
        for section in TEST_REQUIRED_SECTIONS:
            pattern = rf"^##\s+[\*_\s]*(?:\S+\s+)?{re.escape(section)}"
            if not re.search(pattern, content, re.MULTILINE | re.IGNORECASE):
                issues.append(_issue(
                    "critical", rel,
                    f"Test case missing required section: '## {section}'.",
                ))
        h2_sections = _split_h2_sections(content)
        for heading, body in h2_sections:
            measured = _strip_markdown_overhead(body)
            if len(measured) < 20:
                issues.append(_issue(
                    "warning", rel,
                    f"Section '## {heading}' has very little content.",
                ))
        return issues

    def _check_structure(self, docs: Path) -> list[dict]:
        """Check that expected directory structure exists."""
        issues = []
        for dirname in EXPECTED_DIRS:
            dirpath = docs / dirname
            if not dirpath.exists():
                issues.append(_issue(
                    "info", dirname,
                    f"Expected directory '{dirname}/' not found. "
                    f"Create it to keep the knowledge base organized.",
                ))
            elif not any(
                f for ext in SUPPORTED_EXTENSIONS for f in dirpath.rglob(f"*{ext}")
            ):
                issues.append(_issue(
                    "info", dirname,
                    f"Directory '{dirname}/' exists but contains no supported files.",
                ))
        if not (docs / "README.md").exists():
            issues.append(_issue(
                "warning", "README.md",
                "No README.md in docs root. Add one as an index/overview.",
            ))
        return issues

    def _check_completeness(self, docs: Path) -> list[dict]:
        """Check for near-empty or suspiciously short files."""
        issues = []
        for md_file in docs.rglob("*.md"):
            if md_file.name == "README.md" and md_file.parent != docs:
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                text = _strip_markdown_overhead(content)
                rel = str(md_file.relative_to(docs))

                if len(text) < 30:
                    is_placeholder = (
                        md_file.name == "README.md"
                        and md_file.parent != docs
                        and len(text) == 0
                    )
                    severity = "info" if is_placeholder else "warning"
                    issues.append(_issue(
                        severity, rel,
                        "File is nearly empty (< 30 chars of content). "
                        "Add content or remove it.",
                    ))
                elif len(text) < 100:
                    issues.append(_issue(
                        "info", rel,
                        "File is very short (< 100 chars). "
                        "Consider adding more detail.",
                    ))
            except Exception:
                pass
        return issues

    def _check_bugfix_format(self, docs: Path) -> list[dict]:
        """Check that bugfix entries have all required sections."""
        issues = []
        bugfix_dir = docs / "bugfix-log"
        if not bugfix_dir.exists():
            return issues

        for md_file in bugfix_dir.rglob("*.md"):
            if md_file.name == "README.md":
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                rel = str(md_file.relative_to(docs))

                for section in BUGFIX_REQUIRED_SECTIONS:
                    pattern = rf"^##\s+[\*_\s]*(?:\S+\s+)?{re.escape(section)}"
                    if not re.search(pattern, content, re.MULTILINE | re.IGNORECASE):
                        issues.append(_issue(
                            "critical", rel,
                            f"Bugfix entry missing required section: '## {section}'. "
                            f"This reduces the learning value of the entry.",
                        ))

                h2_sections = _split_h2_sections(content)
                for heading, body in h2_sections:
                    measured = _strip_markdown_overhead(body)
                    if len(measured) < 20:
                        issues.append(_issue(
                            "warning", rel,
                            f"Section '## {heading}' has very little content. "
                            f"Add meaningful detail for future reference.",
                        ))
            except Exception:
                pass
        return issues

    def _check_heading_structure(self, docs: Path) -> list[dict]:
        """Check for markdown structural issues."""
        issues = []
        for md_file in docs.rglob("*.md"):
            if md_file.name == "README.md" and md_file.parent != docs:
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                rel = str(md_file.relative_to(docs))
                cleaned = _strip_code_blocks(content)
                headings = re.findall(r"^(#{1,6})\s+", cleaned, re.MULTILINE)

                if not headings:
                    issues.append(_issue(
                        "info", rel,
                        "File has no headings. Add at least a # title.",
                    ))
                    continue

                if len(headings[0]) > 1:
                    issues.append(_issue(
                        "info", rel,
                        f"First heading is level {len(headings[0])}. "
                        f"Start with a # (h1) title.",
                    ))

                seen_levels = {len(headings[0])}
                for i in range(1, len(headings)):
                    curr_level = len(headings[i])
                    if curr_level not in seen_levels and all(
                        lvl < curr_level - 1 or lvl >= curr_level
                        for lvl in seen_levels
                    ):
                        prev_max = max(l for l in seen_levels if l < curr_level)
                        issues.append(_issue(
                            "info", rel,
                            f"Heading level jumps from h{prev_max} to h{curr_level}. "
                            f"Don't skip heading levels.",
                        ))
                        break
                    seen_levels.add(curr_level)
            except Exception:
                pass
        return issues

    def _check_orphans(self, docs: Path) -> list[dict]:
        """Check for supported files outside the expected structure."""
        issues = []
        known_roots = set(EXPECTED_DIRS) | {"README.md", "FLAIWHEEL_TOOLS.md"}
        root_whitelist = {"README.md", "FLAIWHEEL_TOOLS.md"}

        for ext in SUPPORTED_EXTENSIONS:
            for doc_file in docs.rglob(f"*{ext}"):
                rel = doc_file.relative_to(docs)
                parts = rel.parts

                if len(parts) == 1 and parts[0] not in root_whitelist:
                    issues.append(_issue(
                        "info", str(rel),
                        f"File is in docs root instead of a category folder. "
                        f"Move to an appropriate directory ({', '.join(EXPECTED_DIRS)}).",
                    ))
                elif len(parts) > 1 and parts[0] not in known_roots:
                    issues.append(_issue(
                        "info", str(rel),
                        f"File is in non-standard directory '{parts[0]}/'. "
                        f"Expected: {', '.join(EXPECTED_DIRS)}.",
                    ))
        return issues


def _strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks so headings/content inside them aren't counted."""
    return re.sub(r"^```.*?^```", "", text, flags=re.MULTILINE | re.DOTALL)


def _strip_markdown_overhead(text: str) -> str:
    """Measure meaningful content: remove headings but keep code, tables, lists."""
    cleaned = _strip_code_blocks(text)
    lines = []
    for line in cleaned.splitlines():
        if re.match(r"^#{1,6}\s+", line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _split_h2_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) tuples per ## section.

    Captures everything between one ## and the next ##, including
    subsections (###, ####), code blocks, tables, and lists.
    """
    cleaned = _strip_code_blocks(text)
    parts = re.split(r"^(##\s+.+)$", cleaned, flags=re.MULTILINE)
    sections = []
    for i in range(1, len(parts), 2):
        heading = parts[i].lstrip("#").strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        sections.append((heading, body))
    return sections


def _strip_heading_decorators(text: str) -> str:
    """Remove emojis, bold/italic markers, and extra whitespace from heading text."""
    text = re.sub(r"[\*_`~]+", "", text)
    text = re.sub(
        r"[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001FA00-\U0001FA6F"
        r"\U0001FA70-\U0001FAFF\U00002702-\U000027B0]+",
        "", text,
    )
    return text.strip()


def _detect_category(path: str) -> str:
    p = path.lower()
    if "bugfix" in p or "bug-fix" in p:
        return "bugfix"
    if "best-practice" in p:
        return "best-practice"
    if "api" in p:
        return "api"
    if "architect" in p:
        return "architecture"
    if "changelog" in p or "release" in p:
        return "changelog"
    if "setup" in p or "install" in p:
        return "setup"
    if "test" in p:
        return "test"
    return "docs"


def _issue(severity: str, file: str, message: str) -> dict:
    return {"severity": severity, "file": file, "message": message}
