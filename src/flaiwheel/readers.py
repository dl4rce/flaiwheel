# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.md.

"""
Multi-format file readers — extract text from various document formats
and return markdown-like text for the existing chunker pipeline.

Supported: .md, .txt, .pdf, .html/.htm, .rst, .docx, .json, .yaml/.yml, .csv
"""
import csv
import io
import json
import re
from pathlib import Path

SUPPORTED_EXTENSIONS: set[str] = {
    ".md", ".txt", ".pdf", ".html", ".htm",
    ".rst", ".docx", ".json", ".yaml", ".yml", ".csv",
}


def extract_text(filepath: Path) -> str | None:
    """Read *filepath* and return markdown-like text, or None if unsupported."""
    suffix = filepath.suffix.lower()
    handler = _HANDLERS.get(suffix)
    if handler is None:
        return None
    try:
        return handler(filepath)
    except Exception as exc:
        print(f"Warning: could not extract text from {filepath}: {exc}")
        return None


# ── Per-format handlers ──────────────────────────────


def _read_md(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_txt(path: Path) -> str:
    content = path.read_text(encoding="utf-8", errors="ignore")
    return f"# {path.name}\n\n{content}"


def _read_pdf(path: Path) -> str | None:
    try:
        from pypdf import PdfReader  # type: ignore[import-untyped]
    except ImportError:
        print(f"Warning: pypdf not installed — skipping {path.name}")
        return None

    reader = PdfReader(path)
    pages: list[str] = []
    for i, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"## Page {i}\n\n{text.strip()}")
    if not pages:
        return None
    return f"# {path.name}\n\n" + "\n\n---\n\n".join(pages)


def _read_html(path: Path) -> str | None:
    try:
        from bs4 import BeautifulSoup  # type: ignore[import-untyped]
    except ImportError:
        print(f"Warning: beautifulsoup4 not installed — skipping {path.name}")
        return None

    raw = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(raw, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    lines: list[str] = []
    for el in soup.descendants:
        if el.name and el.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(el.name[1])
            lines.append(f"\n{'#' * level} {el.get_text(strip=True)}\n")
        elif el.name == "pre":
            code = el.get_text()
            lines.append(f"\n```\n{code}\n```\n")
        elif el.name == "code" and (not el.parent or el.parent.name != "pre"):
            lines.append(f"`{el.get_text()}`")
        elif el.name == "li":
            lines.append(f"- {el.get_text(strip=True)}")
        elif el.name == "p":
            text = el.get_text(strip=True)
            if text:
                lines.append(f"\n{text}\n")
        elif el.name == "tr":
            cells = [td.get_text(strip=True) for td in el.find_all(["td", "th"])]
            if cells:
                lines.append("| " + " | ".join(cells) + " |")

    body = "\n".join(lines).strip()
    if not body:
        return None
    return f"# {path.name}\n\n{body}"


def _read_rst(path: Path) -> str:
    """Convert reStructuredText to markdown using regex (no deps)."""
    content = path.read_text(encoding="utf-8", errors="ignore")
    result_lines: list[str] = []
    lines = content.splitlines()
    i = 0

    rst_chars = set("=-~^\"'+`:.#*_")

    while i < len(lines):
        line = lines[i]

        # Overline + title + underline pattern
        if (
            i + 2 < len(lines)
            and len(line) >= 2
            and line.strip()
            and set(line.strip()) <= rst_chars
            and lines[i + 2].strip()
            and set(lines[i + 2].strip()) <= rst_chars
        ):
            title = lines[i + 1].strip()
            result_lines.append(f"\n# {title}\n")
            i += 3
            continue

        # Title + underline pattern
        if (
            i + 1 < len(lines)
            and line.strip()
            and not set(line.strip()) <= rst_chars
            and len(lines[i + 1]) >= len(line.rstrip())
            and lines[i + 1].strip()
            and set(lines[i + 1].strip()) <= rst_chars
        ):
            char = lines[i + 1].strip()[0]
            level_map = {"=": "#", "-": "##", "~": "###", "^": "####", '"': "#####"}
            prefix = level_map.get(char, "##")
            result_lines.append(f"\n{prefix} {line.strip()}\n")
            i += 2
            continue

        # Code block directive
        if re.match(r"\.\.\s+code-block::", line) or line.strip() == "::":
            result_lines.append("\n```")
            i += 1
            while i < len(lines) and lines[i].strip() == "":
                i += 1
            while i < len(lines) and (lines[i].startswith("   ") or lines[i].strip() == ""):
                result_lines.append(lines[i].removeprefix("   "))
                i += 1
            result_lines.append("```\n")
            continue

        result_lines.append(line)
        i += 1

    return "\n".join(result_lines)


def _read_docx(path: Path) -> str | None:
    try:
        from docx import Document  # type: ignore[import-untyped]
    except ImportError:
        print(f"Warning: python-docx not installed — skipping {path.name}")
        return None

    doc = Document(path)
    lines: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            lines.append("")
            continue
        style_name = (para.style.name or "").lower()
        if "heading 1" in style_name:
            lines.append(f"\n# {text}\n")
        elif "heading 2" in style_name:
            lines.append(f"\n## {text}\n")
        elif "heading 3" in style_name:
            lines.append(f"\n### {text}\n")
        elif "heading 4" in style_name:
            lines.append(f"\n#### {text}\n")
        elif "heading 5" in style_name:
            lines.append(f"\n##### {text}\n")
        elif "heading 6" in style_name:
            lines.append(f"\n###### {text}\n")
        elif "list" in style_name or "bullet" in style_name:
            lines.append(f"- {text}")
        else:
            lines.append(text)

    body = "\n".join(lines).strip()
    if not body:
        return None
    return f"# {path.name}\n\n{body}"


def _read_json(path: Path) -> str:
    content = path.read_text(encoding="utf-8", errors="ignore")
    try:
        parsed = json.loads(content)
        formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        formatted = content
    return f"# {path.name}\n\n```json\n{formatted}\n```"


def _read_yaml(path: Path) -> str:
    content = path.read_text(encoding="utf-8", errors="ignore")
    return f"# {path.name}\n\n```yaml\n{content}\n```"


def _read_csv(path: Path) -> str:
    content = path.read_text(encoding="utf-8", errors="ignore")
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return f"# {path.name}\n\n(empty)"

    lines: list[str] = []
    header = rows[0]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in rows[1:]:
        while len(row) < len(header):
            row.append("")
        lines.append("| " + " | ".join(row[: len(header)]) + " |")

    return f"# {path.name}\n\n" + "\n".join(lines)


_HANDLERS: dict[str, callable] = {
    ".md": _read_md,
    ".txt": _read_txt,
    ".pdf": _read_pdf,
    ".html": _read_html,
    ".htm": _read_html,
    ".rst": _read_rst,
    ".docx": _read_docx,
    ".json": _read_json,
    ".yaml": _read_yaml,
    ".yml": _read_yaml,
    ".csv": _read_csv,
}
