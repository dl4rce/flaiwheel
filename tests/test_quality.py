"""Tests for the KnowledgeQualityChecker."""
from pathlib import Path


class TestCheckAll:
    def test_clean_repo_no_critical_or_warnings(self, quality_checker, tmp_docs):
        result = quality_checker.check_all()
        assert result["critical"] == 0
        assert result["warnings"] == 0
        assert result["score"] >= 95

    def test_missing_root_readme_warns(self, quality_checker, tmp_docs):
        (tmp_docs / "README.md").unlink()
        result = quality_checker.check_all()
        assert any(i["file"] == "README.md" for i in result["issues"])

    def test_placeholder_readmes_skipped(self, quality_checker, tmp_docs):
        """Placeholder READMEs in subdirs should never trigger quality issues."""
        result = quality_checker.check_all()
        subdir_readme_issues = [
            i for i in result["issues"]
            if "README.md" in i["file"] and "/" in i["file"]
        ]
        assert subdir_readme_issues == []

    def test_bugfix_readme_not_flagged(self, quality_checker, tmp_docs):
        """bugfix-log/README.md must NOT be flagged for missing bugfix sections."""
        result = quality_checker.check_all()
        bugfix_readme_issues = [
            i for i in result["issues"]
            if i["file"] == "bugfix-log/README.md"
        ]
        assert bugfix_readme_issues == []

    def test_tests_readme_not_flagged(self, quality_checker, tmp_docs):
        """tests/README.md must NOT be flagged for missing test sections."""
        result = quality_checker.check_all()
        test_readme_issues = [
            i for i in result["issues"]
            if i["file"] == "tests/README.md"
        ]
        assert test_readme_issues == []


class TestCheckFile:
    def test_valid_doc_no_issues(self, quality_checker, tmp_docs):
        f = tmp_docs / "architecture" / "design.md"
        f.write_text(
            "# System Design\n\n"
            "## Overview\n"
            "This document describes the high-level system architecture for the application, "
            "including the key components, their interactions, and the rationale behind major "
            "design decisions that were made during development.\n\n"
            "## Decisions\n"
            "We chose a microservices architecture because it allows independent deployment "
            "and scaling of individual services. Each service owns its data and communicates "
            "via REST APIs with JWT-based authentication.\n"
        )
        issues = quality_checker.check_file(f, "architecture/design.md")
        assert issues == []

    def test_empty_file_flagged(self, quality_checker, tmp_docs):
        f = tmp_docs / "architecture" / "empty.md"
        f.write_text("")
        issues = quality_checker.check_file(f, "architecture/empty.md")
        assert len(issues) > 0

    def test_placeholder_readme_skipped_in_check_file(self, quality_checker, tmp_docs):
        f = tmp_docs / "bugfix-log" / "README.md"
        issues = quality_checker.check_file(f, "bugfix-log/README.md")
        assert issues == []


class TestBugfixValidation:
    def test_valid_bugfix(self, quality_checker, tmp_docs):
        content = (
            "# Fix payment retry\n\n"
            "## Root Cause\nThe retry logic had an off-by-one error.\n\n"
            "## Solution\nFixed the loop boundary condition.\n\n"
            "## Lesson Learned\nAlways test retry logic with edge cases.\n"
        )
        f = tmp_docs / "bugfix-log" / "2026-01-01-fix-payment.md"
        f.write_text(content)
        issues = quality_checker.check_file(f, "bugfix-log/2026-01-01-fix-payment.md")
        assert issues == []

    def test_missing_root_cause_critical(self, quality_checker, tmp_docs):
        content = (
            "# Fix payment retry\n\n"
            "## Solution\nFixed the loop boundary condition.\n\n"
            "## Lesson Learned\nAlways test retry logic with edge cases.\n"
        )
        f = tmp_docs / "bugfix-log" / "2026-01-01-missing-rc.md"
        f.write_text(content)
        issues = quality_checker.check_file(f, "bugfix-log/2026-01-01-missing-rc.md")
        critical = [i for i in issues if i["severity"] == "critical"]
        assert any("Root Cause" in i["message"] for i in critical)

    def test_bugfix_check_all_flags_bad_entry(self, quality_checker, tmp_docs):
        content = "# Bad bugfix\n\nJust some text without required sections.\n"
        f = tmp_docs / "bugfix-log" / "2026-01-01-bad.md"
        f.write_text(content)
        result = quality_checker.check_all()
        critical = [i for i in result["issues"] if i["severity"] == "critical"]
        assert len(critical) >= 3


class TestTestValidation:
    def test_valid_test_case(self, quality_checker, tmp_docs):
        content = (
            "# Login with expired token\n\n"
            "## Scenario\nUser attempts login with an expired JWT token.\n\n"
            "## Steps\n1. Generate expired token\n2. Send login request\n3. Check response\n\n"
            "## Expected Result\nServer returns 401 with clear error message.\n"
        )
        f = tmp_docs / "tests" / "2026-01-01-expired-token.md"
        f.write_text(content)
        issues = quality_checker.check_file(f, "tests/2026-01-01-expired-token.md")
        assert issues == []

    def test_missing_scenario_critical(self, quality_checker, tmp_docs):
        content = (
            "# Login test\n\n"
            "## Steps\n1. Do something\n2. Check result\n\n"
            "## Expected Result\nIt works.\n"
        )
        f = tmp_docs / "tests" / "2026-01-01-no-scenario.md"
        f.write_text(content)
        issues = quality_checker.check_file(f, "tests/2026-01-01-no-scenario.md")
        critical = [i for i in issues if i["severity"] == "critical"]
        assert any("Scenario" in i["message"] for i in critical)

    def test_missing_steps_critical(self, quality_checker, tmp_docs):
        content = (
            "# Login test\n\n"
            "## Scenario\nTesting login flow.\n\n"
            "## Expected Result\nIt works.\n"
        )
        f = tmp_docs / "tests" / "2026-01-01-no-steps.md"
        f.write_text(content)
        issues = quality_checker.check_file(f, "tests/2026-01-01-no-steps.md")
        critical = [i for i in issues if i["severity"] == "critical"]
        assert any("Steps" in i["message"] for i in critical)


class TestCheckContent:
    def test_valid_bugfix_content(self, quality_checker):
        content = (
            "# Fix payment retry logic for concurrent requests\n\n"
            "## Root Cause\n"
            "The payment retry logic used a shared counter without proper synchronization, "
            "causing race conditions when multiple payment attempts arrived simultaneously. "
            "This resulted in duplicate charges for approximately 0.3% of transactions.\n\n"
            "## Solution\n"
            "Replaced the shared counter with an atomic compare-and-swap operation and added "
            "a distributed lock using Redis to ensure only one retry attempt proceeds per "
            "transaction ID. Added idempotency keys to prevent duplicate processing.\n\n"
            "## Lesson Learned\n"
            "Always use atomic operations or distributed locks for shared state in concurrent "
            "payment processing paths. Added a concurrency stress test to the CI pipeline to "
            "catch similar issues early.\n"
        )
        issues = quality_checker.check_content(content, "bugfix")
        assert issues == []

    def test_valid_test_content(self, quality_checker):
        content = (
            "# Test login flow with expired JWT token\n\n"
            "## Scenario\n"
            "A user attempts to access a protected resource using an expired JWT token. "
            "The system should reject the request gracefully and return an appropriate "
            "error response that the client can use to trigger a token refresh.\n\n"
            "## Steps\n"
            "1. Generate a JWT token with an expiry time set to 1 second ago.\n"
            "2. Send a GET request to /api/profile with the expired token in the Authorization header.\n"
            "3. Verify the HTTP response status code and body.\n\n"
            "## Expected Result\n"
            "The server returns HTTP 401 Unauthorized with a JSON body containing "
            "error code 'TOKEN_EXPIRED' and a human-readable message. The response "
            "should include a WWW-Authenticate header with error='invalid_token'.\n"
        )
        issues = quality_checker.check_content(content, "test")
        assert issues == []

    def test_invalid_test_content_flags(self, quality_checker):
        content = "# Test\n\nJust some text.\n"
        issues = quality_checker.check_content(content, "test")
        critical = [i for i in issues if i["severity"] == "critical"]
        assert len(critical) >= 3


class TestDetectCategory:
    def test_bugfix(self):
        from flaiwheel.quality import _detect_category
        assert _detect_category("bugfix-log/fix.md") == "bugfix"
        assert _detect_category("bug-fix/fix.md") == "bugfix"

    def test_test(self):
        from flaiwheel.quality import _detect_category
        assert _detect_category("tests/login-test.md") == "test"

    def test_architecture(self):
        from flaiwheel.quality import _detect_category
        assert _detect_category("architecture/design.md") == "architecture"

    def test_api(self):
        from flaiwheel.quality import _detect_category
        assert _detect_category("api/endpoints.md") == "api"

    def test_changelog(self):
        from flaiwheel.quality import _detect_category
        assert _detect_category("changelog/1-0-0.md") == "changelog"

    def test_setup(self):
        from flaiwheel.quality import _detect_category
        assert _detect_category("setup/local-dev.md") == "setup"

    def test_default_docs(self):
        from flaiwheel.quality import _detect_category
        assert _detect_category("random/file.md") == "docs"


class TestOrphanDetection:
    def test_flaiwheel_tools_not_orphan(self, quality_checker, tmp_docs):
        (tmp_docs / "FLAIWHEEL_TOOLS.md").write_text(
            "# Flaiwheel MCP Tools Reference\n\n"
            "This file is auto-generated by install.sh and provides a quick reference "
            "for all available MCP tools in the Flaiwheel knowledge base system.\n\n"
            "| Tool | Purpose | Category |\n"
            "|------|---------|----------|\n"
            "| search_docs | Semantic search across all knowledge | Search |\n"
            "| search_bugfixes | Find bugfix entries | Search |\n"
            "| search_tests | Find test cases | Search |\n"
        )
        result = quality_checker.check_all()
        orphan_issues = [
            i for i in result["issues"]
            if "FLAIWHEEL_TOOLS.md" in i["file"] and "root" in i["message"].lower()
        ]
        assert orphan_issues == []

    def test_random_root_file_flagged(self, quality_checker, tmp_docs):
        (tmp_docs / "random-notes.md").write_text("# Random Notes\n\nSome random notes here.\n")
        result = quality_checker.check_all()
        orphan_issues = [i for i in result["issues"] if "random-notes.md" in i["file"]]
        assert len(orphan_issues) > 0
