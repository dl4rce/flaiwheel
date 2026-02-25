# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# Non-commercial use only. Commercial licensing: info@4rce.com

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

EXPECTED_DIRS = [
    "architecture",
    "api",
    "bugfix-log",
    "best-practices",
    "setup",
    "changelog",
]

BUGFIX_REQUIRED_SECTIONS = ["Root Cause", "Solution", "Lesson Learned"]

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
            elif not any(dirpath.rglob("*.md")):
                issues.append(_issue(
                    "info", dirname,
                    f"Directory '{dirname}/' exists but contains no .md files.",
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
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                text = re.sub(r"^#.*$", "", content, flags=re.MULTILINE).strip()
                rel = str(md_file.relative_to(docs))

                if len(text) < 30:
                    # Placeholder files (just a heading) are info, not warning
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

                sections = re.findall(r"^##\s+(.+)", content, re.MULTILINE)
                for section_name in sections:
                    clean_name = _strip_heading_decorators(section_name)
                    section_pattern = rf"^##\s+.*{re.escape(clean_name)}.*\s*\n(.*?)(?=^##|\Z)"
                    match = re.search(section_pattern, content, re.MULTILINE | re.DOTALL)
                    if match and len(match.group(1).strip()) < 20:
                        issues.append(_issue(
                            "warning", rel,
                            f"Section '## {section_name.strip()}' has very little content. "
                            f"Add meaningful detail for future reference.",
                        ))
            except Exception:
                pass
        return issues

    def _check_heading_structure(self, docs: Path) -> list[dict]:
        """Check for markdown structural issues."""
        issues = []
        for md_file in docs.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                rel = str(md_file.relative_to(docs))
                headings = re.findall(r"^(#{1,6})\s+", content, re.MULTILINE)

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

                for i in range(1, len(headings)):
                    prev_level = len(headings[i - 1])
                    curr_level = len(headings[i])
                    if curr_level > prev_level + 1:
                        issues.append(_issue(
                            "info", rel,
                            f"Heading level jumps from h{prev_level} to h{curr_level}. "
                            f"Don't skip heading levels.",
                        ))
                        break
            except Exception:
                pass
        return issues

    def _check_orphans(self, docs: Path) -> list[dict]:
        """Check for .md files outside the expected structure."""
        issues = []
        known_roots = set(EXPECTED_DIRS) | {"README.md"}

        for md_file in docs.rglob("*.md"):
            rel = md_file.relative_to(docs)
            parts = rel.parts

            if len(parts) == 1 and parts[0] != "README.md":
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


def _strip_heading_decorators(text: str) -> str:
    """Remove emojis, bold/italic markers, and extra whitespace from heading text."""
    text = re.sub(r"[\*_`~]+", "", text)
    text = re.sub(
        r"[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001FA00-\U0001FA6F"
        r"\U0001FA70-\U0001FAFF\U00002702-\U000027B0]+",
        "", text,
    )
    return text.strip()


def _issue(severity: str, file: str, message: str) -> dict:
    return {"severity": severity, "file": file, "message": message}
