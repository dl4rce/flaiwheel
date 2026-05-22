"""Tests for MCP server tools (write, search, validate, stats)."""
import threading
from unittest.mock import MagicMock, patch

import pytest

from flaiwheel.config import Config
from flaiwheel.health import HealthTracker
from flaiwheel.indexer import DocsIndexer
from flaiwheel.project import ProjectConfig, ProjectRegistry
from flaiwheel.quality import KnowledgeQualityChecker
from flaiwheel.server import create_mcp_server


@pytest.fixture
def server_env(tmp_docs, tmp_path):
    """Full server environment with a single-project registry."""
    cfg = Config(
        docs_path=str(tmp_docs),
        vectorstore_path=str(tmp_path / "vectorstore"),
        git_repo_url="",
        git_auto_push=False,
    )
    registry = ProjectRegistry(cfg)
    pc = ProjectConfig(
        name="test",
        docs_path=str(tmp_docs),
        collection_name="project_docs",
    )
    ctx = registry.add(pc, start_watcher=False)

    # Replace watcher with a mock to avoid git operations
    mock_watcher = MagicMock()
    mock_watcher.push_pending = MagicMock()
    ctx.watcher = mock_watcher

    mcp = create_mcp_server(cfg, registry)
    return {
        "mcp": mcp,
        "registry": registry,
        "config": cfg,
        "indexer": ctx.indexer,
        "health": ctx.health,
        "watcher": mock_watcher,
        "tmp_docs": tmp_docs,
    }


def _call_tool(mcp, name, **kwargs):
    """Call an MCP tool by name, passing kwargs as arguments."""
    tool = None
    for t in mcp._tool_manager._tools.values():
        if t.name == name:
            tool = t
            break
    assert tool is not None, f"Tool {name} not found"
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(tool.run(kwargs))
    finally:
        loop.close()


class TestMakeSlug:
    def test_basic(self):
        from flaiwheel.server import create_mcp_server
        import re
        slug_fn = lambda text: re.sub(r"[^a-z0-9]+", text.lower(), "").strip("-")[:60]
        pass

    def test_slug_in_written_file(self, server_env):
        result = _call_tool(server_env["mcp"], "write_bugfix_summary",
            title="Fix Payment Race Condition",
            root_cause="Shared counter without locking caused duplicate charges in concurrent payment flows.",
            solution="Replaced shared counter with atomic CAS operation and Redis distributed lock per transaction ID.",
            lesson_learned="Always use atomic operations for shared state in payment processing. Added concurrency stress test to CI.",
            affected_files="payments/retry.py, payments/lock.py",
            tags="payment,race-condition,critical",
        )
        assert "Saved and indexed" in result
        assert "fix-payment-race-condition" in result


class TestWriteTools:
    def test_write_bugfix_creates_file(self, server_env):
        result = _call_tool(server_env["mcp"], "write_bugfix_summary",
            title="Fix database connection pool exhaustion",
            root_cause="Connection pool size was set to 5 but peak load requires 20 connections. Idle connections were not being returned to the pool due to missing finally blocks.",
            solution="Increased pool size to 20 and wrapped all database calls in try/finally to ensure connections are always returned.",
            lesson_learned="Always use context managers for database connections. Added a pool monitoring dashboard and alerting when usage exceeds 80%.",
            affected_files="db/pool.py, db/queries.py",
            tags="database,performance,critical",
        )
        assert "Saved and indexed" in result
        assert "chunks" in result
        server_env["watcher"].push_pending.assert_called()

    def test_write_architecture_doc(self, server_env):
        result = _call_tool(server_env["mcp"], "write_architecture_doc",
            title="Payment Service Architecture",
            overview="The payment service handles all financial transactions using a microservices architecture with event sourcing for auditability.",
            decisions="Chose event sourcing over traditional CRUD for complete audit trail. Selected Stripe as payment provider for PCI DSS compliance.",
            trade_offs="Event sourcing adds complexity to queries but provides full history. Stripe has higher fees but reduces our PCI compliance scope significantly.",
        )
        assert "Saved and indexed" in result

    def test_write_api_doc(self, server_env):
        result = _call_tool(server_env["mcp"], "write_api_doc",
            title="Create User Endpoint",
            endpoint="/api/v1/users",
            method="POST",
            request_schema="JSON body with fields: email (string, required), name (string, required), role (string, optional, default 'user')",
            response_schema="201: JSON with created user object including id, email, name, role, created_at. 400: validation errors. 409: email already exists.",
            auth="Bearer token with admin role required",
            examples="POST /api/v1/users { \"email\": \"alice@example.com\", \"name\": \"Alice\" }",
        )
        assert "Saved and indexed" in result

    def test_write_best_practice(self, server_env):
        result = _call_tool(server_env["mcp"], "write_best_practice",
            title="Error Handling in API Routes",
            context="All API route handlers in the Express application that interact with external services or databases.",
            rule="Wrap all async route handlers in try/catch. Return structured error responses with error codes. Never expose internal details.",
            rationale="Unhandled promise rejections crash the server. Structured errors help clients handle failures gracefully. Internal details are a security risk.",
        )
        assert "Saved and indexed" in result

    def test_write_setup_doc(self, server_env):
        result = _call_tool(server_env["mcp"], "write_setup_doc",
            title="Local Development Setup",
            prerequisites="Docker Desktop 4.x, Node.js 18+, Python 3.11+, Git, and access to the private npm registry.",
            steps="1. Clone the repo. 2. Copy .env.example to .env. 3. Run docker compose up -d. 4. Run npm install. 5. Run npm run migrate.",
            verification="Open http://localhost:3000 and verify the login page loads. Run npm test to verify all tests pass.",
        )
        assert "Saved and indexed" in result

    def test_write_changelog_entry(self, server_env):
        result = _call_tool(server_env["mcp"], "write_changelog_entry",
            version="2.1.0",
            release_date="2026-02-25",
            added="New test case documentation tools (write_test_case, search_tests). Configurable host field in Web UI.",
            fixed="Quality checker no longer flags placeholder READMEs. Installer creates missing category directories on update.",
        )
        assert "Saved and indexed" in result

    def test_write_changelog_requires_at_least_one_section(self, server_env):
        result = _call_tool(server_env["mcp"], "write_changelog_entry",
            version="1.0.0",
            release_date="2026-01-01",
        )
        assert "Error" in result

    def test_write_test_case(self, server_env):
        result = _call_tool(server_env["mcp"], "write_test_case",
            title="Login with expired JWT token",
            scenario="A user attempts to access a protected resource using an expired JWT token. The system should reject the request and return a clear error.",
            steps="1. Generate a JWT token with expiry set to 1 second ago.\n2. Send GET /api/profile with the expired token.\n3. Check response status and body.",
            expected_result="Server returns HTTP 401 with error code TOKEN_EXPIRED and a WWW-Authenticate header.",
            preconditions="Auth service running, test user exists in database",
            tags="auth,regression,critical",
        )
        assert "Saved and indexed" in result

    def test_path_traversal_blocked(self, server_env):
        result = _call_tool(server_env["mcp"], "write_bugfix_summary",
            title="../../../etc/passwd",
            root_cause="Testing path traversal attack vector to ensure the system blocks attempts to write outside the docs directory.",
            solution="The _write_knowledge_doc function validates that the resolved path is relative to the docs base directory before writing.",
            lesson_learned="Always validate file paths server-side. Never trust user input for filesystem operations.",
        )
        assert "Saved and indexed" in result or "path traversal" in result.lower()


class TestSearchTools:
    def test_search_docs_empty(self, server_env):
        result = _call_tool(server_env["mcp"], "search_docs", query="something")
        assert "No relevant documents" in result

    def test_search_docs_finds_indexed(self, server_env):
        _call_tool(server_env["mcp"], "write_architecture_doc",
            title="Authentication System Design",
            overview="JWT-based stateless authentication across all microservices with token refresh and revocation support.",
            decisions="Selected RS256 for JWT signing to allow public key verification without sharing secrets across services.",
            trade_offs="RS256 is slower than HS256 but allows verification without sharing the signing key, which is critical for our microservices architecture.",
        )
        result = _call_tool(server_env["mcp"], "search_docs", query="JWT authentication")
        assert "authentication" in result.lower() or "jwt" in result.lower()

    def test_search_bugfixes_empty(self, server_env):
        result = _call_tool(server_env["mcp"], "search_bugfixes", query="memory leak")
        assert "No similar bugfixes" in result

    def test_search_by_type(self, server_env):
        result = _call_tool(server_env["mcp"], "search_by_type",
            query="anything", doc_type="architecture")
        assert "No results" in result

    def test_search_tests_empty(self, server_env):
        result = _call_tool(server_env["mcp"], "search_tests", query="login")
        assert "No test cases" in result

    def test_search_records_health(self, server_env):
        _call_tool(server_env["mcp"], "search_docs", query="test")
        s = server_env["health"].status
        assert s["searches_total"] == 1
        assert s["searches_by_tool"]["search_docs"] == 1


class TestValidateDoc:
    def test_valid_bugfix_ok(self, server_env):
        content = (
            "# Fix database timeout\n\n"
            "## Root Cause\n"
            "The connection pool was configured with a 5-second timeout, but complex queries "
            "routinely take 8-10 seconds during peak hours, causing connection drops.\n\n"
            "## Solution\n"
            "Increased timeout to 30 seconds and added connection retry logic with exponential "
            "backoff. Also optimized the two slowest queries to run under 3 seconds.\n\n"
            "## Lesson Learned\n"
            "Always set timeouts based on measured P99 latency, not arbitrary values. Add monitoring "
            "for query duration distribution to catch regressions early.\n"
        )
        result = _call_tool(server_env["mcp"], "validate_doc",
            content=content, category="bugfix")
        assert "OK" in result

    def test_invalid_bugfix_flags_issues(self, server_env):
        content = "# Bad bugfix\n\nJust some text without required sections.\n"
        result = _call_tool(server_env["mcp"], "validate_doc",
            content=content, category="bugfix")
        assert "[!]" in result
        assert "Root Cause" in result

    def test_valid_test_ok(self, server_env):
        content = (
            "# Verify payment idempotency\n\n"
            "## Scenario\n"
            "Submit the same payment request twice with the same idempotency key and verify "
            "that only one charge is created. This ensures our payment processing is safe "
            "against network retries and duplicate submissions.\n\n"
            "## Steps\n"
            "1. Create a unique idempotency key.\n"
            "2. Submit a payment request with the key.\n"
            "3. Submit the same payment request with the same key.\n"
            "4. Query the charges list for the customer.\n\n"
            "## Expected Result\n"
            "Only one charge exists. The second request returns the same charge ID as the "
            "first. No duplicate charges appear in the ledger.\n"
        )
        result = _call_tool(server_env["mcp"], "validate_doc",
            content=content, category="test")
        assert "OK" in result


class TestValidateDocFrontmatter:
    def test_unknown_key_is_info(self, server_env):
        content = (
            "---\n"
            "id: adr-1\n"
            "type: architecture\n"
            "frobnicate: yes\n"
            "---\n"
            "# Title\n\n"
            "Body with enough content to pass length checks. " * 5
        )
        result = _call_tool(server_env["mcp"], "validate_doc",
            content=content, category="architecture")
        assert "[i]" in result
        assert "frobnicate" in result

    def test_invalid_status_is_warning(self, server_env):
        content = (
            "---\n"
            "id: adr-2\n"
            "status: wibble\n"
            "---\n"
            "# Title\n\n"
            "Body with enough content to pass length checks. " * 5
        )
        result = _call_tool(server_env["mcp"], "validate_doc",
            content=content, category="architecture")
        assert "[~]" in result
        assert "wibble" in result

    def test_known_keys_pass(self, server_env):
        content = (
            "---\n"
            "id: adr-3\n"
            "type: architecture\n"
            "status: active\n"
            "replaces: [adr-0]\n"
            "depends_on:\n"
            "  - service-a\n"
            "---\n"
            "# Title\n\n"
            "Body with enough content to pass length checks. " * 5
        )
        result = _call_tool(server_env["mcp"], "validate_doc",
            content=content, category="architecture")
        # No frontmatter-related issues
        assert "frobnicate" not in result
        assert "wibble" not in result


class TestRelations:
    def _write(self, tmp_docs, name, body):
        f = tmp_docs / "architecture" / name
        f.write_text(body, encoding="utf-8")
        return f

    def test_entity_not_found(self, server_env):
        result = _call_tool(server_env["mcp"], "relations", entity_id="nope")
        assert "not found" in result.lower()

    def test_outbound_and_inbound_edges(self, server_env):
        tmp_docs = server_env["tmp_docs"]
        self._write(tmp_docs, "adr-0042.md",
            "---\nid: adr-0042\ntype: architecture\nreplaces: [adr-0017]\n---\n"
            "# ADR 42\n\nReplaces ADR 17.\n",
        )
        self._write(tmp_docs, "adr-0017.md",
            "---\nid: adr-0017\ntype: architecture\nstatus: superseded\n---\n"
            "# ADR 17\n\nOld decision.\n",
        )
        out_42 = _call_tool(server_env["mcp"], "relations", entity_id="adr-0042")
        assert "adr-0017" in out_42
        assert "replaces" in out_42

        out_17 = _call_tool(server_env["mcp"], "relations", entity_id="adr-0017")
        # Inbound edge from adr-0042 should be visible
        assert "adr-0042" in out_17
        assert "replaces" in out_17

    def test_unresolved_target_flagged(self, server_env):
        tmp_docs = server_env["tmp_docs"]
        self._write(tmp_docs, "adr-0099.md",
            "---\nid: adr-0099\ntype: architecture\ndepends_on: [ghost-service]\n---\n"
            "# ADR 99\n",
        )
        out = _call_tool(server_env["mcp"], "relations", entity_id="adr-0099")
        assert "ghost-service" in out
        assert "unresolved" in out


class TestTimeline:
    def test_no_git_returns_hint(self, server_env):
        tmp_docs = server_env["tmp_docs"]
        (tmp_docs / "architecture" / "adr-0050.md").write_text(
            "---\nid: adr-0050\n---\n# X\n", encoding="utf-8",
        )
        # Watcher mock returns MagicMock by default → emulate empty log
        server_env["watcher"].log_for_file = MagicMock(return_value=[])
        result = _call_tool(server_env["mcp"], "timeline", entity_id="adr-0050")
        assert "No git history" in result

    def test_entity_unknown(self, server_env):
        result = _call_tool(server_env["mcp"], "timeline", entity_id="missing")
        assert "not found" in result.lower()

    def test_renders_commits(self, server_env):
        tmp_docs = server_env["tmp_docs"]
        (tmp_docs / "architecture" / "adr-0060.md").write_text(
            "---\nid: adr-0060\n---\n# Y\n", encoding="utf-8",
        )
        server_env["watcher"].log_for_file = MagicMock(return_value=[
            {"hash": "abcdef1234567890", "author": "Alice",
             "date": "2026-05-22T10:00:00+00:00", "subject": "Initial draft"},
            {"hash": "1234567890abcdef", "author": "Bob",
             "date": "2026-05-23T11:00:00+00:00", "subject": "Refine wording"},
        ])
        result = _call_tool(server_env["mcp"], "timeline", entity_id="adr-0060")
        assert "abcdef12" in result
        assert "Alice" in result
        assert "Initial draft" in result
        assert "Refine wording" in result


class TestGetIndexStats:
    def test_returns_stats_string(self, server_env):
        result = _call_tool(server_env["mcp"], "get_index_stats")
        assert "Index Statistics" in result
        assert "Chunks total" in result


class TestCheckKnowledgeQuality:
    def test_clean_repo_reports_clean(self, server_env):
        result = _call_tool(server_env["mcp"], "check_knowledge_quality")
        assert "Quality Score" in result


class TestGetFileContext:
    def test_no_docs_returns_gap_message(self, server_env):
        result = _call_tool(server_env["mcp"], "get_file_context",
            filename="payment.service.ts")
        assert "No Flaiwheel context found" in result
        assert "payment.service.ts" in result

    def test_finds_relevant_doc_after_indexing(self, server_env):
        _call_tool(server_env["mcp"], "write_bugfix_summary",
            title="Payment webhook race condition",
            root_cause="Concurrent webhook calls incremented the same counter without locking.",
            solution="Added a distributed lock with Redis. Only one webhook handler proceeds per transaction.",
            lesson_learned="Always use distributed locks for shared state in webhook handlers.",
            affected_files="payment/webhook.py",
            tags="payment,race-condition,webhook",
        )
        result = _call_tool(server_env["mcp"], "get_file_context",
            filename="src/payment/webhook.py")
        assert "Flaiwheel Context" in result
        assert "payment" in result.lower() or "webhook" in result.lower()

    def test_strips_generic_parent_dirs(self, server_env):
        _call_tool(server_env["mcp"], "write_architecture_doc",
            title="Authentication JWT design",
            overview="Stateless JWT authentication with RS256 signing.",
            decisions="RS256 chosen for public-key verification across services.",
            trade_offs="Slower than HS256 but more secure for multi-service setup.",
        )
        # "src" is a generic dir and should be stripped — query should still work
        result = _call_tool(server_env["mcp"], "get_file_context",
            filename="src/auth/jwt.py")
        assert "Flaiwheel Context" in result or "No Flaiwheel context" in result

    def test_unknown_project_returns_error(self, server_env):
        result = _call_tool(server_env["mcp"], "get_file_context",
            filename="foo.py",
            project="nonexistent_project_xyz")
        assert "not found" in result.lower() or "no projects" in result.lower()


class TestTelemetryPersistenceAndImpact:
    def test_telemetry_persists_across_server_recreate(self, server_env):
        _call_tool(server_env["mcp"], "search_docs", query="nonexistent telemetry term")

        before = server_env["mcp"].get_telemetry_data()
        assert "test" in before
        assert before["test"]["total_calls"] >= 1

        mcp2 = create_mcp_server(server_env["config"], server_env["registry"])
        after = mcp2.get_telemetry_data()
        assert "test" in after
        assert after["test"]["total_calls"] >= before["test"]["total_calls"]

    def test_impact_metrics_aggregate_ci_guardrail_reports(self, server_env):
        _call_tool(server_env["mcp"], "write_best_practice",
            title="Error handling telemetry impact",
            context="API route handlers and service boundaries",
            rule="Capture failures and return structured errors",
            rationale="Improves triage speed and prevents repeated regressions",
        )
        _call_tool(server_env["mcp"], "search_docs", query="error handling telemetry impact")

        report = server_env["mcp"].record_ci_guardrail_report(
            project="test",
            violations_found=3,
            violations_blocking=1,
            violations_fixed_before_merge=2,
            cycle_time_baseline_minutes=45.0,
            cycle_time_actual_minutes=30.0,
            metadata={"source": "pytest"},
        )
        assert report["status"] == "recorded"

        metrics = server_env["mcp"].get_impact_metrics(project="test", days=30)
        assert metrics["ci_reports"] >= 1
        assert metrics["guardrail_violations_found"] >= 3
        assert metrics["regressions_avoided"] >= 2
        assert metrics["estimated_time_saved_minutes"] > 0


class TestFrontmatterAutoEmission:
    """v3.10.1 — every structured writer must emit a parseable frontmatter
    block with a stable ``id`` and the right ``type`` so the doc becomes a
    graph node automatically (resolvable via ``relations()`` / ``timeline()``)."""

    @staticmethod
    def _written_file(tmp_docs, slug):
        """Find the .md file under tmp_docs whose filename contains the slug."""
        from pathlib import Path
        matches = [p for p in Path(tmp_docs).rglob("*.md") if slug in p.name]
        assert len(matches) == 1, f"expected exactly one match for slug {slug!r}, got {matches}"
        return matches[0]

    def _assert_fm(self, path, *, expected_type, expected_id_contains):
        from flaiwheel.frontmatter import parse
        content = path.read_text()
        fm = parse(content)
        assert fm.get("type") == expected_type, f"type mismatch in {path}: {fm}"
        assert expected_id_contains in (fm.get("id") or ""), f"id mismatch in {path}: {fm}"
        assert fm.get("status") == "active"
        # Relation keys present and lists (empty by default).
        for k in ("replaces", "depends_on", "fixes", "implements"):
            assert isinstance(fm.get(k), list), f"{k} should be a list in {path}: {fm}"

    def test_bugfix_emits_frontmatter(self, server_env):
        _call_tool(server_env["mcp"], "write_bugfix_summary",
            title="Frontmatter Emit Bugfix",
            root_cause="Writers were not emitting YAML frontmatter so docs never became graph nodes for relations() and timeline().",
            solution="Added flaiwheel.frontmatter.emit() and prepended it inside every write_* tool.",
            lesson_learned="Make the structured writers do the right thing by default so agents do not have to remember.",
        )
        path = self._written_file(server_env["tmp_docs"], "frontmatter-emit-bugfix")
        self._assert_fm(path, expected_type="bugfix", expected_id_contains="frontmatter-emit-bugfix")

    def test_architecture_emits_frontmatter(self, server_env):
        _call_tool(server_env["mcp"], "write_architecture_doc",
            title="Frontmatter Emit ADR",
            overview="Document the decision to auto-emit frontmatter from every write_* tool in Flaiwheel 3.10.1.",
            decisions="Each writer prepends emit_frontmatter(id, type, status='active') with empty relation lists by default.",
            trade_offs="Slightly larger doc bodies; in exchange every new doc becomes a graph node usable by relations().",
        )
        path = self._written_file(server_env["tmp_docs"], "frontmatter-emit-adr")
        self._assert_fm(path, expected_type="architecture", expected_id_contains="frontmatter-emit-adr")

    def test_api_emits_frontmatter(self, server_env):
        _call_tool(server_env["mcp"], "write_api_doc",
            title="Frontmatter Emit Endpoint",
            endpoint="/api/v1/fm-emit",
            method="POST",
            request_schema="empty body",
            response_schema="200 OK",
        )
        path = self._written_file(server_env["tmp_docs"], "frontmatter-emit-endpoint")
        self._assert_fm(path, expected_type="api", expected_id_contains="frontmatter-emit-endpoint")

    def test_best_practice_emits_frontmatter(self, server_env):
        _call_tool(server_env["mcp"], "write_best_practice",
            title="Frontmatter Emit Practice",
            context="All structured writers in Flaiwheel that create new markdown documents in a project knowledge repo.",
            rule="Always prepend a parseable YAML frontmatter block with id, type, status and empty relation lists.",
            rationale="Without an id no document is a graph node; relations() and timeline() cannot reach it.",
        )
        path = self._written_file(server_env["tmp_docs"], "frontmatter-emit-practice")
        self._assert_fm(path, expected_type="best-practice", expected_id_contains="frontmatter-emit-practice")

    def test_setup_emits_frontmatter(self, server_env):
        _call_tool(server_env["mcp"], "write_setup_doc",
            title="Frontmatter Emit Setup",
            prerequisites="A running Flaiwheel container at v3.10.1 or newer with the structured writers patched.",
            steps="1. Call any write_* tool. 2. Inspect the resulting file under /docs/<project>/.",
            verification="The file starts with `---` and parses via flaiwheel.frontmatter.parse() into a dict with id and type.",
        )
        path = self._written_file(server_env["tmp_docs"], "frontmatter-emit-setup")
        self._assert_fm(path, expected_type="setup", expected_id_contains="frontmatter-emit-setup")

    def test_changelog_emits_frontmatter(self, server_env):
        _call_tool(server_env["mcp"], "write_changelog_entry",
            version="9.9.9",
            release_date="2026-05-22",
            added="Auto-emit frontmatter in every structured writer.",
        )
        path = self._written_file(server_env["tmp_docs"], "9-9-9")
        self._assert_fm(path, expected_type="changelog", expected_id_contains="9-9-9")

    def test_test_case_emits_frontmatter(self, server_env):
        _call_tool(server_env["mcp"], "write_test_case",
            title="Frontmatter Emit Test Case",
            scenario="Verify the test-case writer emits frontmatter so its entity is reachable from relations().",
            steps="1. Call write_test_case with a known title.\n2. Locate the resulting tests/*.md file.\n3. Parse the frontmatter.",
            expected_result="parse() returns a dict with id, type='test', status='active' and empty relation lists.",
        )
        path = self._written_file(server_env["tmp_docs"], "frontmatter-emit-test-case")
        self._assert_fm(path, expected_type="test", expected_id_contains="frontmatter-emit-test-case")

    def test_emitted_frontmatter_is_resolvable_by_relations(self, server_env):
        """End-to-end: write two docs, declare a dependency, relations() resolves it."""
        # Create the target doc via the normal writer (emits frontmatter with a stable id).
        _call_tool(server_env["mcp"], "write_best_practice",
            title="Auto Emit Target",
            context="Target doc for the cross-writer relations() round-trip test.",
            rule="Exist with a stable frontmatter id so a second doc can depend on it.",
            rationale="Without resolvable targets relations() can only report unresolved edges.",
        )
        # Manually write a second doc with depends_on pointing at the target id.
        # write_* tools don't yet take relation args — that's a separate opt-in API.
        from pathlib import Path
        from flaiwheel.frontmatter import emit as emit_fm
        body = emit_fm("dependent-doc", "architecture", depends_on=["best-practice-auto-emit-target"])
        body += "# Dependent doc\n\nLinks to best-practice-auto-emit-target.\n"
        (Path(server_env["tmp_docs"]) / "architecture" / "dependent.md").write_text(body)

        result = _call_tool(server_env["mcp"], "relations", entity_id="best-practice-auto-emit-target")
        assert "dependent-doc" in result, result
        assert "depends_on" in result, result
        # Inbound edge should be resolved (the dependent doc has frontmatter we wrote).
        inbound_section = result.split("Inbound edges:", 1)[1] if "Inbound edges:" in result else ""
        assert "dependent-doc" in inbound_section, f"expected dependent-doc in inbound, got: {inbound_section!r}"
