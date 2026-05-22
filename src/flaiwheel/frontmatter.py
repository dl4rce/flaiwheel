# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.

"""
YAML frontmatter parsing for structured relations.

Stdlib-only — supports the small subset of YAML used by Flaiwheel doc
frontmatter (scalars: str/int/bool/null; flow lists: ``[a, b, c]``;
block lists with ``- item``). Intentionally NOT a full YAML parser:
keeps Flaiwheel install footprint unchanged.

Frontmatter convention (v1):

    ---
    id: adr-0042
    type: architecture
    replaces: [adr-0017]
    depends_on: [service-summarizer, supabase-edge]
    fixes: []
    implements: []
    status: active        # active | superseded | deprecated
    superseded_at: null
    ---

Relation keys recognized by ``KNOWN_RELATIONS``. ``validate_doc()`` warns
on unknown keys; ``relations()`` MCP tool resolves the graph from them.
"""
from __future__ import annotations

import re
from pathlib import Path

# Frontmatter keys that may be referenced from `relations()` / `timeline()`.
# Scalar keys identify the entity; list keys are edges.
SCALAR_KEYS: set[str] = {"id", "type", "status", "superseded_at"}
RELATION_KEYS: set[str] = {"replaces", "depends_on", "fixes", "implements"}
KNOWN_KEYS: set[str] = SCALAR_KEYS | RELATION_KEYS

VALID_STATUS: set[str] = {"active", "superseded", "deprecated"}

_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<body>.*?)\n---\s*(?:\n|\Z)",
    re.DOTALL,
)


def split_frontmatter(content: str) -> tuple[str, str]:
    """Return ``(frontmatter_yaml, body)``.

    If no leading ``---``-fenced block is present returns ``("", content)``
    unchanged. The frontmatter is **always** stripped from ``body``, which
    lets quality checks and chunkers ignore it without re-parsing.
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return "", content
    return m.group("body"), content[m.end():]


def strip_frontmatter(content: str) -> str:
    """Drop the leading ``---`` block, return the body only."""
    _, body = split_frontmatter(content)
    return body


def parse(content: str) -> dict:
    """Parse the leading frontmatter block of ``content``.

    Returns ``{}`` when no frontmatter is present or parsing fails.
    Lists are returned as ``list[str]``; scalars are kept as their
    inferred Python type (``str``/``int``/``bool``/``None``).
    """
    fm, _ = split_frontmatter(content)
    if not fm:
        return {}
    return _parse_yaml_subset(fm)


def parse_file(path: Path) -> dict:
    """Read ``path`` and return parsed frontmatter (or ``{}``)."""
    try:
        return parse(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return {}


# ── Internal: minimal YAML subset ────────────────────────


def _coerce_scalar(raw: str):
    s = raw.strip()
    if s == "" or s.lower() in {"null", "~"}:
        return None
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    # Quoted strings
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    # Integer
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except ValueError:
            pass
    return s


def _parse_flow_list(raw: str) -> list[str]:
    """Parse ``[a, b, c]`` → ``["a", "b", "c"]``. Empty ``[]`` → ``[]``."""
    inner = raw.strip()[1:-1].strip()
    if not inner:
        return []
    items = []
    for piece in inner.split(","):
        v = _coerce_scalar(piece)
        if v is None:
            continue
        items.append(str(v))
    return items


def _parse_yaml_subset(text: str) -> dict:
    """Tolerant single-level YAML parser.

    Supports:
      key: scalar
      key: [a, b]
      key:
        - a
        - b
    Lines starting with ``#`` and blank lines are ignored. Indented
    continuations beyond block lists are ignored. Unknown / malformed
    constructs return ``None`` for that key rather than raising.
    """
    out: dict = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        # Only consider top-level keys (no leading whitespace)
        if line != line.lstrip():
            i += 1
            continue

        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.split("#", 1)[0].rstrip()  # strip inline comments
        value_raw = rest.lstrip()

        if value_raw == "":
            # Possible block list: collect following "  - item" lines
            items: list[str] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                nxt_stripped = nxt.strip()
                if not nxt_stripped:
                    j += 1
                    continue
                if not nxt.startswith((" ", "\t")):
                    break
                if nxt_stripped.startswith("- "):
                    items.append(str(_coerce_scalar(nxt_stripped[2:])))
                elif nxt_stripped == "-":
                    items.append("")
                else:
                    break
                j += 1
            out[key] = items if items else None
            i = j
            continue

        if value_raw.startswith("[") and value_raw.endswith("]"):
            out[key] = _parse_flow_list(value_raw)
            i += 1
            continue

        out[key] = _coerce_scalar(value_raw)
        i += 1
    return out
