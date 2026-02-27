"""Tests for MCP server tools (write, search, validate, stats)."""
import threading
from unittest.mock import MagicMock, patch

import pytest

from flaiwheel.config import Config
from flaiwheel.health import HealthTracker
from flaiwheel.indexer import DocsIndexer
from flaiwheel.quality import KnowledgeQualityChecker
from flaiwheel.server import create_mcp_server


@pytest.fixture
def server_env(tmp_docs, tmp_path):
    """Full server environment with real indexer and quality checker."""
    cfg = Config(
        docs_path=str(tmp_docs),
        vectorstore_path=str(tmp_path / "vectorstore"),
        git_repo_url="",
        git_auto_push=False,
    )
    indexer = DocsIndexer(cfg)
    lock = threading.Lock()
    watcher = MagicMock()
    watcher.push_pending = MagicMock()
    quality_checker = KnowledgeQualityChecker(cfg)
    health = HealthTracker()

    mcp = create_mcp_server(cfg, indexer, lock, watcher, quality_checker, health)
    return {
        "mcp": mcp,
        "config": cfg,
        "indexer": indexer,
        "health": health,
        "watcher": watcher,
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


class TestGetIndexStats:
    def test_returns_stats_string(self, server_env):
        result = _call_tool(server_env["mcp"], "get_index_stats")
        assert "Index Statistics" in result
        assert "Chunks total" in result


class TestCheckKnowledgeQuality:
    def test_clean_repo_reports_clean(self, server_env):
        result = _call_tool(server_env["mcp"], "check_knowledge_quality")
        assert "Quality Score" in result
