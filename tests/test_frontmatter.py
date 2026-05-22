"""Tests for the stdlib-only YAML frontmatter parser."""
from flaiwheel.frontmatter import (
    KNOWN_KEYS,
    RELATION_KEYS,
    parse,
    split_frontmatter,
    strip_frontmatter,
)


class TestSplit:
    def test_no_frontmatter_returns_empty(self):
        fm, body = split_frontmatter("# Title\n\nNo fence here.")
        assert fm == ""
        assert body == "# Title\n\nNo fence here."

    def test_basic_split(self):
        content = "---\nid: adr-1\n---\n# Title\n"
        fm, body = split_frontmatter(content)
        assert "id: adr-1" in fm
        assert body == "# Title\n"

    def test_strip_drops_block(self):
        content = "---\nid: x\n---\n\nBody."
        # The closing `---\n` plus the next newline are consumed
        assert strip_frontmatter(content) == "Body."

    def test_strip_drops_block_no_trailing_blank(self):
        content = "---\nid: x\n---\nBody."
        assert strip_frontmatter(content) == "Body."


class TestParse:
    def test_empty_when_no_frontmatter(self):
        assert parse("# Title\n") == {}

    def test_scalars(self):
        content = "---\nid: adr-42\ntype: architecture\nstatus: active\n---\n"
        out = parse(content)
        assert out["id"] == "adr-42"
        assert out["type"] == "architecture"
        assert out["status"] == "active"

    def test_null_and_bool(self):
        content = "---\nsuperseded_at: null\nactive: true\nclosed: false\n---\n"
        out = parse(content)
        assert out["superseded_at"] is None
        assert out["active"] is True
        assert out["closed"] is False

    def test_flow_list(self):
        content = "---\nreplaces: [adr-1, adr-2]\nfixes: []\n---\n"
        out = parse(content)
        assert out["replaces"] == ["adr-1", "adr-2"]
        assert out["fixes"] == []

    def test_block_list(self):
        content = (
            "---\n"
            "depends_on:\n"
            "  - service-a\n"
            "  - service-b\n"
            "---\n"
        )
        out = parse(content)
        assert out["depends_on"] == ["service-a", "service-b"]

    def test_quoted_string(self):
        content = '---\nid: "adr 42"\n---\n'
        assert parse(content)["id"] == "adr 42"

    def test_inline_comment_stripped(self):
        content = "---\nstatus: active  # current\n---\n"
        assert parse(content)["status"] == "active"

    def test_known_keys_constants(self):
        # Sanity: relation keys are a subset of known keys
        assert RELATION_KEYS.issubset(KNOWN_KEYS)
        assert "id" in KNOWN_KEYS
        assert "replaces" in RELATION_KEYS

    def test_malformed_does_not_raise(self):
        content = "---\n: just a colon\n[no key]\n---\n"
        # Must not raise, even on garbage
        parse(content)
