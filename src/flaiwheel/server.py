# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.md.

"""
MCP Server factory – creates a FastMCP instance with tools
that share the ProjectRegistry from the main process.

All tools accept an optional ``project`` parameter.
When omitted the default (first) project is used.
"""
import re
import threading
from datetime import date
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from . import __version__
from .config import Config
from .project import ProjectRegistry, ProjectContext

GITHUB_REPO = "dl4rce/flaiwheel"


def create_mcp_server(
    config: Config,
    registry: ProjectRegistry,
) -> FastMCP:
    """Factory: returns a configured FastMCP server backed by a ProjectRegistry."""

    mcp = FastMCP(
        "flaiwheel",
        instructions=(
            "Semantic search over project documentation.\n\n"
            "WORKFLOW for the agent:\n"
            "1. ALWAYS search_docs() before changing code\n"
            "2. search_bugfixes() to learn from past bugs\n"
            "3. Prefer 2-3 targeted searches over one vague query\n"
            "4. AFTER every bugfix: call write_bugfix_summary()\n"
            "5. If one chunk isn't enough, search more specifically\n"
            "6. Periodically call check_knowledge_quality() to maintain docs\n"
            "7. Use list_projects() to see available projects\n"
            "8. Pass project='name' to target a specific project"
        ),
    )

    def _ctx(project: str | None) -> tuple[ProjectContext | None, str]:
        ctx = registry.resolve(project)
        if ctx is None:
            names = registry.names()
            if not names:
                return None, "No projects registered. Add a project via the Web UI first."
            return None, f"Project '{project}' not found. Available: {', '.join(names)}"
        return ctx, ""

    # ── Search tools ──────────────────────────────────

    @mcp.tool()
    def search_docs(query: str, top_k: int = 5, project: str = "") -> str:
        """Semantic search over the ENTIRE project documentation.
        Returns only the most relevant chunks (token-efficient!).

        Use this ALWAYS before writing or changing code.

        Args:
            query: What you want to know (natural language, be specific)
            top_k: Number of results (default: 5, increase for broad questions)
            project: Target project name (optional, defaults to first project)

        Returns:
            Relevant doc chunks with source reference and relevance score
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        results = ctx.indexer.search(query, top_k=top_k)
        ctx.health.record_search("search_docs", bool(results))

        if not results:
            return (
                "No relevant documents found. "
                "Try a different or more specific query."
            )

        output = []
        for r in results:
            loc = f"{r['source']}:{r['line_start']}-{r['line_end']}" if r.get("line_start") else r["source"]
            output.append(
                f"**{loc}** > _{r['heading']}_ "
                f"(Relevance: {r['relevance']}%, Type: {r['type']})\n\n"
                f"{r['text']}\n\n---"
            )
        return "\n".join(output)

    @mcp.tool()
    def search_bugfixes(query: str, top_k: int = 5, project: str = "") -> str:
        """Search ONLY bugfix summaries for similar past problems.
        Use this to learn from earlier bugs and avoid repetition.

        Args:
            query: Description of the current problem/bug
            top_k: Number of results (default: 5)
            project: Target project name (optional)

        Returns:
            Similar bugfix summaries with root cause, solution and lessons learned
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        results = ctx.indexer.search(query, top_k=top_k, type_filter="bugfix")
        ctx.health.record_search("search_bugfixes", bool(results))

        if not results:
            return (
                "No similar bugfixes found - this might be a new problem. "
                "Don't forget to call write_bugfix_summary() after fixing!"
            )

        output = [f"Found {len(results)} similar bugfixes\n"]
        for r in results:
            loc = f"{r['source']}:{r['line_start']}-{r['line_end']}" if r.get("line_start") else r["source"]
            output.append(
                f"### {loc} (Relevance: {r['relevance']}%)\n\n"
                f"{r['text']}\n\n---"
            )
        return "\n".join(output)

    @mcp.tool()
    def search_by_type(query: str, doc_type: str, top_k: int = 5, project: str = "") -> str:
        """Search filtered by document type.

        Args:
            query: Search query
            doc_type: One of: "docs", "bugfix", "best-practice", "api",
                      "architecture", "changelog", "setup", "readme", "test"
            top_k: Number of results
            project: Target project name (optional)
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        results = ctx.indexer.search(query, top_k=top_k, type_filter=doc_type)
        ctx.health.record_search("search_by_type", bool(results))

        if not results:
            return f"No results of type '{doc_type}' found."

        output = []
        for r in results:
            loc = f"{r['source']}:{r['line_start']}-{r['line_end']}" if r.get("line_start") else r["source"]
            output.append(
                f"**{loc}** > _{r['heading']}_ ({r['relevance']}%)\n\n"
                f"{r['text']}\n\n---"
            )
        return "\n".join(output)

    @mcp.tool()
    def search_tests(query: str, top_k: int = 5, project: str = "") -> str:
        """Search test cases in the knowledge base.

        Find existing test scenarios, regression patterns, and test strategies.
        Useful before writing new tests to check what's already covered.

        Args:
            query: What to search for (e.g. "authentication edge cases")
            top_k: Number of results to return
            project: Target project name (optional)
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        results = ctx.indexer.search(query, top_k=top_k, type_filter="test")
        ctx.health.record_search("search_tests", bool(results))

        if not results:
            return "No test cases found. Use write_test_case to document tests."

        output = []
        for r in results:
            loc = (
                f"{r['source']}:{r['line_start']}-{r['line_end']}"
                if r.get("line_start")
                else r["source"]
            )
            output.append(
                f"**{loc}** > _{r['heading']}_ ({r['relevance']}%)\n\n"
                f"{r['text']}\n\n---"
            )
        return "\n".join(output)

    # ── Write helpers ─────────────────────────────────

    def _write_knowledge_doc(ctx: ProjectContext, filename: str, content: str) -> str:
        cfg = ctx.merged_config
        filepath = Path(cfg.docs_path) / filename
        safe_base = Path(cfg.docs_path).resolve()
        if not filepath.resolve().is_relative_to(safe_base):
            return "Error: path traversal detected."
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        chunk_count = ctx.indexer.index_single(filename, content)
        ctx.watcher.push_pending()
        return (
            f"Saved and indexed: {filename} ({chunk_count} chunks)\n"
            f"Auto-pushed to remote: {cfg.git_auto_push and bool(cfg.git_repo_url)}"
        )

    def _make_slug(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]

    # ── Write tools ───────────────────────────────────

    @mcp.tool()
    def write_bugfix_summary(
        title: str,
        root_cause: str,
        solution: str,
        lesson_learned: str,
        affected_files: str = "",
        tags: str = "",
        project: str = "",
    ) -> str:
        """Write a bugfix summary as .md file and index it IMMEDIATELY.

        MUST be called after every bugfix! These summaries are found during
        future bugs and help avoid repeating mistakes.

        Args:
            title: Short, descriptive title of the bug
            root_cause: What was the actual cause? (technical)
            solution: How was it fixed? (describe code changes)
            lesson_learned: What should be done differently next time?
            affected_files: Affected files (comma-separated)
            tags: Categories (e.g. "payment,race-condition,critical")
            project: Target project name (optional)
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        content = (
            f"# {title}\n\n"
            f"**Date:** {date.today().isoformat()}  \n"
            f"**Tags:** {tags}  \n"
            f"**Affected files:** {affected_files}\n\n"
            f"## Root Cause\n{root_cause}\n\n"
            f"## Solution\n{solution}\n\n"
            f"## Lesson Learned\n{lesson_learned}\n"
        )
        filename = f"bugfix-log/{date.today().isoformat()}-{_make_slug(title)}.md"
        return _write_knowledge_doc(ctx, filename, content)

    @mcp.tool()
    def write_architecture_doc(
        title: str,
        overview: str,
        decisions: str,
        trade_offs: str,
        components: str = "",
        diagrams: str = "",
        project: str = "",
    ) -> str:
        """Write an architecture decision/design document.

        Args:
            title: Short title (e.g. "Payment Service Architecture")
            overview: High-level description of the system/component
            decisions: Key architectural decisions made and why
            trade_offs: What was considered and rejected, pros/cons
            components: Optional component breakdown
            diagrams: Optional ASCII/mermaid diagrams
            project: Target project name (optional)
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        sections = [
            f"# {title}\n",
            f"**Date:** {date.today().isoformat()}\n",
            f"## Overview\n{overview}\n",
            f"## Decisions\n{decisions}\n",
            f"## Trade-offs\n{trade_offs}\n",
        ]
        if components:
            sections.append(f"## Components\n{components}\n")
        if diagrams:
            sections.append(f"## Diagrams\n{diagrams}\n")
        content = "\n".join(sections)
        filename = f"architecture/{date.today().isoformat()}-{_make_slug(title)}.md"
        return _write_knowledge_doc(ctx, filename, content)

    @mcp.tool()
    def write_api_doc(
        title: str,
        endpoint: str,
        method: str,
        request_schema: str,
        response_schema: str,
        auth: str = "",
        examples: str = "",
        project: str = "",
    ) -> str:
        """Write an API endpoint document.

        Args:
            title: Short title (e.g. "Create User Endpoint")
            endpoint: URL path (e.g. "/api/v1/users")
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            request_schema: Request body/params schema description
            response_schema: Response body schema description
            auth: Optional authentication requirements
            examples: Optional request/response examples
            project: Target project name (optional)
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        sections = [
            f"# {title}\n",
            f"**Endpoint:** `{method} {endpoint}`\n",
            f"## Request\n{request_schema}\n",
            f"## Response\n{response_schema}\n",
        ]
        if auth:
            sections.append(f"## Authentication\n{auth}\n")
        if examples:
            sections.append(f"## Examples\n{examples}\n")
        content = "\n".join(sections)
        filename = f"api/{_make_slug(title)}.md"
        return _write_knowledge_doc(ctx, filename, content)

    @mcp.tool()
    def write_best_practice(
        title: str,
        context: str,
        rule: str,
        rationale: str,
        examples: str = "",
        project: str = "",
    ) -> str:
        """Write a best practice / coding standard document.

        Args:
            title: Short title (e.g. "Error Handling in API Routes")
            context: When/where does this practice apply?
            rule: The actual rule or pattern to follow
            rationale: Why this rule exists, what problems it prevents
            examples: Optional code examples showing correct usage
            project: Target project name (optional)
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        sections = [
            f"# {title}\n",
            f"## Context\n{context}\n",
            f"## Rule\n{rule}\n",
            f"## Rationale\n{rationale}\n",
        ]
        if examples:
            sections.append(f"## Examples\n{examples}\n")
        content = "\n".join(sections)
        filename = f"best-practices/{_make_slug(title)}.md"
        return _write_knowledge_doc(ctx, filename, content)

    @mcp.tool()
    def write_setup_doc(
        title: str,
        prerequisites: str,
        steps: str,
        verification: str,
        troubleshooting: str = "",
        project: str = "",
    ) -> str:
        """Write a setup/deployment/infrastructure document.

        Args:
            title: Short title (e.g. "Local Development Setup")
            prerequisites: What needs to be installed/configured first
            steps: Step-by-step instructions
            verification: How to verify the setup works
            troubleshooting: Optional common issues and solutions
            project: Target project name (optional)
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        sections = [
            f"# {title}\n",
            f"## Prerequisites\n{prerequisites}\n",
            f"## Steps\n{steps}\n",
            f"## Verification\n{verification}\n",
        ]
        if troubleshooting:
            sections.append(f"## Troubleshooting\n{troubleshooting}\n")
        content = "\n".join(sections)
        filename = f"setup/{_make_slug(title)}.md"
        return _write_knowledge_doc(ctx, filename, content)

    @mcp.tool()
    def write_changelog_entry(
        version: str,
        release_date: str,
        added: str = "",
        changed: str = "",
        fixed: str = "",
        breaking: str = "",
        project: str = "",
    ) -> str:
        """Write a changelog / release notes entry.

        Args:
            version: Version string (e.g. "2.1.0")
            release_date: Release date (e.g. "2026-02-25")
            added: New features (optional)
            changed: Changes to existing features (optional)
            fixed: Bug fixes (optional)
            breaking: Breaking changes (optional)
            project: Target project name (optional)
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        sections = [f"# {version}\n", f"**Date:** {release_date}\n"]
        if added:
            sections.append(f"## Added\n{added}\n")
        if changed:
            sections.append(f"## Changed\n{changed}\n")
        if fixed:
            sections.append(f"## Fixed\n{fixed}\n")
        if breaking:
            sections.append(f"## Breaking Changes\n{breaking}\n")
        if not any([added, changed, fixed, breaking]):
            return "Error: At least one of added/changed/fixed/breaking is required."
        content = "\n".join(sections)
        slug = re.sub(r"[^a-z0-9]+", "-", version).strip("-")
        filename = f"changelog/{slug}.md"
        return _write_knowledge_doc(ctx, filename, content)

    @mcp.tool()
    def write_test_case(
        title: str,
        scenario: str,
        steps: str,
        expected_result: str,
        preconditions: str = "",
        actual_result: str = "",
        status: str = "",
        tags: str = "",
        project: str = "",
    ) -> str:
        """Write a test case document and index it IMMEDIATELY.

        Args:
            title: Short test case title (e.g. "User login with expired token")
            scenario: What is being tested and why
            steps: Step-by-step test procedure
            expected_result: What should happen if the test passes
            preconditions: Optional setup/prerequisites before running the test
            actual_result: Optional actual result if already executed
            status: Optional test status (e.g. "pass", "fail", "blocked", "pending")
            tags: Optional categories (e.g. "auth,regression,critical")
            project: Target project name (optional)
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        sections = [
            f"# {title}\n",
            f"**Date:** {date.today().isoformat()}  \n"
            f"**Status:** {status or 'pending'}  \n"
            f"**Tags:** {tags}\n",
        ]
        if preconditions:
            sections.append(f"## Preconditions\n{preconditions}\n")
        sections.extend([
            f"## Scenario\n{scenario}\n",
            f"## Steps\n{steps}\n",
            f"## Expected Result\n{expected_result}\n",
        ])
        if actual_result:
            sections.append(f"## Actual Result\n{actual_result}\n")
        content = "\n".join(sections)
        filename = f"tests/{date.today().isoformat()}-{_make_slug(title)}.md"
        return _write_knowledge_doc(ctx, filename, content)

    # ── Admin / utility tools ─────────────────────────

    @mcp.tool()
    def validate_doc(content: str, category: str = "docs", project: str = "") -> str:
        """Validate a markdown document BEFORE committing it to the knowledge repo.

        Args:
            content: The full markdown content to validate
            category: Target category — one of: "architecture", "api",
                      "bugfix", "best-practice", "setup", "changelog", "test", "docs"
            project: Target project name (optional)

        Returns:
            "OK" if valid, or a list of issues to fix
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        issues = ctx.quality_checker.check_content(content, category)
        if not issues:
            return "OK — document passes all quality checks."
        lines = [f"Found {len(issues)} issue(s) to fix before committing:\n"]
        for issue in issues:
            icon = {"critical": "[!]", "warning": "[~]", "info": "[i]"}
            lines.append(f"{icon.get(issue['severity'], '[-]')} {issue['message']}")
        return "\n".join(lines)

    @mcp.tool()
    def get_index_stats(project: str = "") -> str:
        """Show statistics about the current vector index.

        Args:
            project: Target project name (optional)
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        stats = ctx.indexer.stats
        type_dist = "\n".join(
            f"  - {t}: {c} chunks" for t, c in stats["type_distribution"].items()
        ) or "  (empty)"

        return (
            f"**Index Statistics** (project: {ctx.name})\n\n"
            f"- **Chunks total:** {stats['total_chunks']}\n"
            f"- **Docs path:** {stats['docs_path']}\n"
            f"- **Embedding:** {stats['embedding_provider']} ({stats['embedding_model']})\n"
            f"- **Chunking:** {stats['chunk_strategy']}\n\n"
            f"**Type distribution:**\n{type_dist}"
        )

    @mcp.tool()
    def reindex(force: bool = False, project: str = "") -> str:
        """Re-index documentation. Diff-aware by default (only changed files).
        Set force=True to rebuild all embeddings from scratch.

        Args:
            force: If True, re-embed all files regardless of changes (default: False)
            project: Target project name (optional)
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        with ctx.index_lock:
            result = ctx.indexer.index_all(force=force, quality_checker=ctx.quality_checker)
        return (
            f"Re-index complete! (project: {ctx.name})\n"
            f"  Files: {result['files_indexed']} ({result.get('files_changed', '?')} changed, "
            f"{result.get('files_skipped', '?')} skipped)\n"
            f"  Chunks upserted: {result.get('chunks_upserted', result.get('chunks_created', '?'))}\n"
            f"  Stale removed: {result['chunks_removed']}"
        )

    @mcp.tool()
    def git_pull_reindex(project: str = "") -> str:
        """Pull latest changes from the knowledge repo and re-index.

        Call this AFTER you have committed and pushed new or updated .md files
        to the knowledge repo.

        Args:
            project: Target project name (optional)

        Returns:
            Summary of pull result and reindex statistics
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        cfg = ctx.merged_config
        if not cfg.git_repo_url:
            return "No git repo configured for this project."

        changed = ctx.watcher.pull_and_check()
        if not changed:
            return "No new changes in knowledge repo. Already up to date."

        with ctx.index_lock:
            result = ctx.indexer.index_all(quality_checker=ctx.quality_checker)
        ctx.health.record_index(
            ok=result.get("status") == "success",
            chunks=result.get("chunks_upserted", 0),
            files=result.get("files_indexed", 0),
        )
        return (
            f"Pulled new changes and re-indexed! (project: {ctx.name})\n"
            f"  Files: {result['files_indexed']} ({result.get('files_changed', '?')} changed, "
            f"{result.get('files_skipped', '?')} skipped)\n"
            f"  Chunks upserted: {result.get('chunks_upserted', result.get('chunks_created', '?'))}\n"
            f"  Stale removed: {result['chunks_removed']}"
        )

    @mcp.tool()
    def check_knowledge_quality(project: str = "") -> str:
        """Validate the knowledge base for consistency, completeness
        and structural correctness.

        Args:
            project: Target project name (optional)

        Returns:
            Quality score (0-100) and list of issues
        """
        ctx, err = _ctx(project or None)
        if not ctx:
            return err

        report = ctx.quality_checker.check_all()

        lines = [
            f"**Knowledge Quality Score: {report['score']}/100** (project: {ctx.name})\n",
            f"Issues: {report['critical']} critical, "
            f"{report['warnings']} warnings, {report['info']} info\n",
        ]

        if not report["issues"]:
            lines.append("No issues found – knowledge base is clean!")
            return "\n".join(lines)

        for issue in report["issues"]:
            icon = {"critical": "[!]", "warning": "[~]", "info": "[i]"}
            lines.append(
                f"{icon.get(issue['severity'], '[-]')} "
                f"**{issue['file']}**: {issue['message']}"
            )

        return "\n".join(lines)

    @mcp.tool()
    def list_projects() -> str:
        """List all registered projects with basic statistics.

        Returns:
            Table of projects with name, chunks, docs path, and git repo
        """
        projects = registry.all()
        if not projects:
            return "No projects registered. Add a project via the Web UI."

        lines = [f"**{len(projects)} project(s) registered:**\n"]
        for ctx in projects:
            stats = ctx.indexer.stats
            health = ctx.health.status
            qs = health.get("quality_score")
            qs_str = f"{qs}/100" if qs is not None else "–"
            lines.append(
                f"- **{ctx.name}** — {stats['total_chunks']} chunks, "
                f"quality {qs_str}, "
                f"path: `{stats['docs_path']}`"
            )
            if ctx.merged_config.git_repo_url:
                lines.append(f"  git: `{ctx.merged_config.git_repo_url}`")
        return "\n".join(lines)

    @mcp.tool()
    def check_update() -> str:
        """Check if a newer version of Flaiwheel is available on GitHub.

        Returns:
            Version status and update instructions if needed
        """
        import subprocess
        from packaging.version import Version

        current = __version__
        repo_url = f"https://github.com/{GITHUB_REPO}.git"

        try:
            result = subprocess.run(
                ["git", "ls-remote", "--tags", "--sort=-v:refname", repo_url],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return (
                    f"Could not check remote versions (repo may be private).\n"
                    f"Current version: v{current}\n\n"
                    f"To update manually, tell the user to run:\n\n"
                    f"```bash\n"
                    f"curl -sSL https://raw.githubusercontent.com/{GITHUB_REPO}/main/scripts/install.sh | bash\n"
                    f"```"
                )

            versions = []
            for line in result.stdout.strip().splitlines():
                ref = line.split("refs/tags/")[-1] if "refs/tags/" in line else ""
                if ref and not ref.endswith("^{}"):
                    ver_str = ref.lstrip("v")
                    try:
                        versions.append(Version(ver_str))
                    except Exception:
                        continue

            if not versions:
                return f"No version tags found on remote.\nCurrent version: v{current}"

            latest = max(versions)
        except Exception as e:
            return (
                f"Could not check for updates: {e}\n"
                f"Current version: v{current}\n\n"
                f"To update manually, tell the user to run:\n\n"
                f"```bash\n"
                f"curl -sSL https://raw.githubusercontent.com/{GITHUB_REPO}/main/scripts/install.sh | bash\n"
                f"```"
            )

        if Version(current) >= latest:
            return f"Flaiwheel is up to date! (v{current})"

        return (
            f"**Update available!** v{current} → v{latest}\n\n"
            f"Tell the user to run this command in their project directory:\n\n"
            f"```bash\n"
            f"curl -sSL https://raw.githubusercontent.com/{GITHUB_REPO}/main/scripts/install.sh | bash\n"
            f"```\n\n"
            f"This will rebuild the Docker image and recreate the container with the latest code. "
            f"Data and configuration are preserved."
        )

    return mcp
