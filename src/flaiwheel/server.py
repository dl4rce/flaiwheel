# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.

"""
MCP Server factory – creates a FastMCP instance with tools
that share the ProjectRegistry from the main process.

All tools accept an optional ``project`` parameter.
Resolution order: explicit project > per-session active project > first project.
"""
import json
import os
import re
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from mcp.server.fastmcp import FastMCP, Context
from . import __version__
from .bootstrap import (
    DocumentClassifier,
    KnowledgeBootstrap,
    format_classification_report,
    format_report,
)
from .code_analyzer import CodebaseAnalyzer, format_codebase_report
from .config import Config
from .project import ProjectConfig, ProjectRegistry, ProjectContext
from .telemetry import TelemetryStore

GITHUB_REPO = "dl4rce/flaiwheel"


def _sessions_dir() -> Path:
    return Path(os.environ.get("MCP_VECTORSTORE_PATH", "/data")) / "sessions"


def _sessions_path(project_name: str) -> Path:
    _sessions_dir().mkdir(parents=True, exist_ok=True)
    return _sessions_dir() / f"{project_name}.json"


def _load_sessions(project_name: str) -> list[dict]:
    p = _sessions_path(project_name)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save_sessions(project_name: str, sessions: list[dict], max_sessions: int = 50):
    sessions = sessions[-max_sessions:]
    _sessions_path(project_name).write_text(json.dumps(sessions, indent=2))


def create_mcp_server(
    config: Config,
    registry: ProjectRegistry,
) -> FastMCP:
    """Factory: returns a configured FastMCP server backed by a ProjectRegistry."""

    _active_projects: dict[int, str] = {}
    _active_lock = threading.Lock()

    # ── Session Telemetry (persistent) ───────────────
    _telemetry_store = TelemetryStore(config.vectorstore_path)
    _telemetry: dict[str, dict] = _telemetry_store.load_summary()
    _telemetry_lock = threading.Lock()

    def _ensure_telem(key: str) -> dict:
        if key not in _telemetry:
            _telemetry[key] = {
                "searches": 0,
                "search_misses": 0,
                "bugfix_searches": 0,
                "writes": 0,
                "bugfix_writes": 0,
                "session_saves": 0,
                "total_calls": 0,
                "last_tool": "",
                "nudges_sent": 0,
                "ci_reports": 0,
                "guardrail_violations_found": 0,
                "guardrail_violations_blocking": 0,
                "guardrail_violations_fixed": 0,
            }
        return _telemetry[key]

    def _persist_telemetry_locked() -> None:
        _telemetry_store.save_summary(_telemetry)

    def _telem(project: str | None, tool_name: str) -> None:
        """Record a tool call for a project."""
        key = project or "_default"
        with _telemetry_lock:
            t = _ensure_telem(key)
            t["total_calls"] += 1
            t["last_tool"] = tool_name
            if tool_name in ("search_docs", "search_by_type", "search_tests"):
                t["searches"] += 1
            elif tool_name == "search_bugfixes":
                t["bugfix_searches"] += 1
            elif tool_name == "write_bugfix_summary":
                t["bugfix_writes"] += 1
            elif tool_name.startswith("write_"):
                t["writes"] += 1
            elif tool_name == "save_session_summary":
                t["session_saves"] += 1
            _persist_telemetry_locked()
        _telemetry_store.append_event("tool_call", key, {"tool_name": tool_name})

    def _record_search_result(
        project: str | None,
        tool_name: str,
        hit: bool,
        result_count: int,
    ) -> None:
        key = project or "_default"
        with _telemetry_lock:
            t = _ensure_telem(key)
            if not hit:
                t["search_misses"] += 1
            _persist_telemetry_locked()
        _telemetry_store.append_event(
            "search_result",
            key,
            {
                "tool_name": tool_name,
                "hit": bool(hit),
                "result_count": max(0, int(result_count)),
            },
        )

    def record_ci_guardrail_report(
        project: str | None,
        violations_found: int = 0,
        violations_blocking: int = 0,
        violations_fixed_before_merge: int = 0,
        cycle_time_baseline_minutes: float | None = None,
        cycle_time_actual_minutes: float | None = None,
        metadata: dict | None = None,
    ) -> dict:
        key = project or "_default"
        found = max(0, int(violations_found))
        blocking = max(0, int(violations_blocking))
        fixed = max(0, int(violations_fixed_before_merge))

        with _telemetry_lock:
            t = _ensure_telem(key)
            t["ci_reports"] += 1
            t["guardrail_violations_found"] += found
            t["guardrail_violations_blocking"] += blocking
            t["guardrail_violations_fixed"] += fixed
            _persist_telemetry_locked()

        payload = {
            "violations_found": found,
            "violations_blocking": blocking,
            "violations_fixed_before_merge": fixed,
        }
        if cycle_time_baseline_minutes is not None:
            payload["cycle_time_baseline_minutes"] = float(cycle_time_baseline_minutes)
        if cycle_time_actual_minutes is not None:
            payload["cycle_time_actual_minutes"] = float(cycle_time_actual_minutes)
        if metadata:
            payload["metadata"] = metadata
        _telemetry_store.append_event("ci_guardrail_report", key, payload)
        return {
            "status": "recorded",
            "project": key,
            "violations_found": found,
            "violations_blocking": blocking,
            "violations_fixed_before_merge": fixed,
        }

    def get_impact_metrics(project: str | None = None, days: int = 30) -> dict:
        return _telemetry_store.compute_impact_metrics(project, days=days)

    def _nudge(project: str | None) -> str:
        """Return a nudge string if the telemetry pattern warrants it."""
        key = project or "_default"
        with _telemetry_lock:
            t = _ensure_telem(key)
            if not t:
                return ""
            nudges = []
            if t["bugfix_searches"] >= 1 and t["bugfix_writes"] == 0:
                nudges.append(
                    "Hint: You searched bugfixes but haven't documented a fix yet. "
                    "If you fixed a bug, call write_bugfix_summary()."
                )
            if t["searches"] >= 5 and t["writes"] == 0 and t["bugfix_writes"] == 0:
                nudges.append(
                    "Hint: You've searched " + str(t["searches"]) + " times without "
                    "capturing any knowledge. Consider write_architecture_doc() or write_best_practice()."
                )
            if t["search_misses"] >= 3:
                nudges.append(
                    "Hint: Multiple searches returned 0 results — "
                    "the knowledge base may have a gap here. Consider documenting this topic."
                )
            if not nudges:
                return ""
            t["nudges_sent"] += len(nudges)
            _persist_telemetry_locked()
        _telemetry_store.append_event(
            "nudge",
            key,
            {
                "count": len(nudges),
                "messages": nudges,
            },
        )
        return "\n\n---\n" + "\n".join(nudges)

    def get_telemetry_data() -> dict:
        """Return telemetry data for all projects (used by Web UI API)."""
        with _telemetry_lock:
            return {k: dict(v) for k, v in _telemetry.items()}

    def _session_key(ctx: Context | None) -> int:
        """Return a per-connection key from an MCP Context.

        Each SSE client gets its own ServerSession object, so id(session)
        is stable and unique for the lifetime of that connection.  When
        Context is unavailable (e.g. unit tests) we fall back to 0.
        """
        if ctx is None:
            return 0
        try:
            return id(ctx.request_context.session)
        except (ValueError, AttributeError):
            return 0

    def _get_active(ctx: Context | None) -> str:
        """Read the active project for this session."""
        key = _session_key(ctx)
        with _active_lock:
            return _active_projects.get(key, "")

    def _set_active(ctx: Context | None, name: str) -> None:
        """Set the active project for this session only."""
        key = _session_key(ctx)
        with _active_lock:
            _active_projects[key] = name

    mcp = FastMCP(
        "flaiwheel",
        instructions=(
            "Semantic search over project documentation.\n\n"
            "WORKFLOW for the agent:\n"
            "1. Call set_project('name') at the START of every session to bind\n"
            "   all subsequent calls to the correct project. If the project\n"
            "   is not registered yet, call setup_project() first.\n"
            "2. ALWAYS search_docs() before changing code\n"
            "3. search_bugfixes() to learn from past bugs\n"
            "4. Prefer 2-3 targeted searches over one vague query\n"
            "5. AFTER every bugfix: call write_bugfix_summary()\n"
            "6. If one chunk isn't enough, search more specifically\n"
            "7. Periodically call check_knowledge_quality() to maintain docs\n"
            "8. Every tool accepts project='name' as an explicit override\n"
            "9. 'This is the Way' (or '42'): user says this to bootstrap a messy repo.\n"
            "   Call analyze_knowledge_repo(), review the plan, execute_cleanup() with\n"
            "   approved IDs, rewrite flagged files with write_* tools, finalize with reindex()\n"
            "10. For NEW projects with messy docs in the project repo (not yet in knowledge):\n"
            "   a. Scan the project directory locally for .md/.txt/.pdf/.html/.rst/.docx files\n"
            "   b. Read first ~2000 chars of each file\n"
            "   c. Call classify_documents(files=JSON) to get Flaiwheel's classification\n"
            "   d. Present the migration plan to the user\n"
            "   e. For each approved file: read it, use the suggested write_* tool to push\n"
            "   f. Call reindex() when done\n\n"
            "DOCUMENTATION TRIGGERS — when to document:\n"
            "MANDATORY: After fixing ANY bug → write_bugfix_summary() (no exceptions)\n"
            "RECOMMENDED: Architecture decision → write_architecture_doc() | API change → write_api_doc() | "
            "New pattern → write_best_practice() | Deployment change → write_setup_doc() | Tests written → write_test_case()\n"
            "SESSION: At END of session → save_session_summary() | At START of session → get_recent_sessions()"
        ),
    )

    def _ctx(project: str | None, mcp_ctx: Context | None = None) -> tuple[ProjectContext | None, str]:
        effective = project or _get_active(mcp_ctx) or None
        ctx = registry.resolve(effective)
        if ctx is None:
            names = registry.names()
            if not names:
                return None, (
                    "No projects registered. "
                    "Call setup_project() to register this project first."
                )
            if effective:
                return None, (
                    f"Project '{effective}' not found. "
                    f"Available: {', '.join(names)}"
                )
            return None, (
                f"Multiple projects registered but none selected. "
                f"Call set_project('name') first. "
                f"Available: {', '.join(names)}"
            )
        return ctx, ""

    # ── Search tools ──────────────────────────────────

    @mcp.tool()
    def search_docs(query: str, top_k: int = 5, project: str = "", mcp_ctx: Context = None) -> str:
        """Semantic search over the ENTIRE project knowledge base. Read-only, no side effects.

        Use this ALWAYS before writing or changing code to retrieve architecture
        decisions, past bugs, best practices, and API contracts.

        Prefer search_bugfixes() when debugging a specific error (searches only
        bugfix summaries). Use search_by_type() when you know the category.
        Use search_tests() when looking for test coverage.

        Args:
            query: What you want to know (natural language, be specific)
            top_k: Number of results (default: 5, increase for broad questions)
            project: Target project name (optional, defaults to active project)

        Returns:
            Ranked doc chunks, each showing source file:line, section heading,
            relevance %, doc type, and text. Returns a "no results" message with
            a rephrasing suggestion when nothing matches.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err
        _telem(ctx.name, "search_docs")

        results = ctx.indexer.search(query, top_k=top_k)
        ctx.health.record_search("search_docs", bool(results))
        _record_search_result(ctx.name, "search_docs", bool(results), len(results))

        if not results:
            return (
                "No relevant documents found. "
                "Try a different or more specific query."
            ) + _nudge(ctx.name)

        output = []
        for r in results:
            loc = f"{r['source']}:{r['line_start']}-{r['line_end']}" if r.get("line_start") else r["source"]
            output.append(
                f"**{loc}** > _{r['heading']}_ "
                f"(Relevance: {r['relevance']}%, Type: {r['type']})\n\n"
                f"{r['text']}\n\n---"
            )
        return "\n".join(output) + _nudge(ctx.name)

    @mcp.tool()
    def search_bugfixes(query: str, top_k: int = 5, project: str = "", mcp_ctx: Context = None) -> str:
        """Search only bugfix summaries for similar past problems. Read-only, no side effects.

        Prefer this over search_docs() when debugging — it filters to bugfix
        documents only, surfacing root causes and solutions faster.
        Use search_docs() for broader queries that span all doc types.

        Args:
            query: Description of the current problem or error message
            top_k: Number of results (default: 5)
            project: Target project name (optional)

        Returns:
            Ranked bugfix chunks showing root cause, solution, and lessons
            learned, with source file and relevance %. Prompts to call
            write_bugfix_summary() when no matches are found.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err
        _telem(ctx.name, "search_bugfixes")

        results = ctx.indexer.search(query, top_k=top_k, type_filter="bugfix")
        ctx.health.record_search("search_bugfixes", bool(results))
        _record_search_result(ctx.name, "search_bugfixes", bool(results), len(results))

        if not results:
            return (
                "No similar bugfixes found - this might be a new problem. "
                "Don't forget to call write_bugfix_summary() after fixing!"
            ) + _nudge(ctx.name)

        output = [f"Found {len(results)} similar bugfixes\n"]
        for r in results:
            loc = f"{r['source']}:{r['line_start']}-{r['line_end']}" if r.get("line_start") else r["source"]
            output.append(
                f"### {loc} (Relevance: {r['relevance']}%)\n\n"
                f"{r['text']}\n\n---"
            )
        return "\n".join(output) + _nudge(ctx.name)

    @mcp.tool()
    def search_by_type(query: str, doc_type: str, top_k: int = 5, project: str = "", mcp_ctx: Context = None) -> str:
        """Search filtered by a specific document category. Read-only, no side effects.

        Use instead of search_docs() when you know the category — it improves
        precision by restricting results to that type only.
        Use search_bugfixes() or search_tests() as convenient shortcuts for
        those specific categories.

        Args:
            query: Search query (natural language)
            doc_type: Category filter — one of: "architecture", "api",
                      "bugfix", "best-practice", "setup", "changelog",
                      "test", "readme", "docs"
            top_k: Number of results (default: 5)
            project: Target project name (optional)

        Returns:
            Ranked chunks of the specified type with source, relevance %, and text.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err
        _telem(ctx.name, "search_by_type")

        results = ctx.indexer.search(query, top_k=top_k, type_filter=doc_type)
        ctx.health.record_search("search_by_type", bool(results))
        _record_search_result(ctx.name, "search_by_type", bool(results), len(results))

        if not results:
            return f"No results of type '{doc_type}' found." + _nudge(ctx.name)

        output = []
        for r in results:
            loc = f"{r['source']}:{r['line_start']}-{r['line_end']}" if r.get("line_start") else r["source"]
            output.append(
                f"**{loc}** > _{r['heading']}_ ({r['relevance']}%)\n\n"
                f"{r['text']}\n\n---"
            )
        return "\n".join(output) + _nudge(ctx.name)

    @mcp.tool()
    def search_tests(query: str, top_k: int = 5, project: str = "", mcp_ctx: Context = None) -> str:
        """Search test case documents in the knowledge base. Read-only, no side effects.

        Call BEFORE write_test_case() to check what is already covered and
        avoid duplicates. Equivalent to search_by_type(query, "test") but
        more intent-clear for test-coverage workflows.

        Args:
            query: What to search for (e.g. "authentication edge cases")
            top_k: Number of results to return (default: 5)
            project: Target project name (optional)

        Returns:
            Ranked test case chunks with scenario, steps, expected result,
            and status. Returns a prompt to call write_test_case() when empty.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err
        _telem(ctx.name, "search_tests")

        results = ctx.indexer.search(query, top_k=top_k, type_filter="test")
        ctx.health.record_search("search_tests", bool(results))
        _record_search_result(ctx.name, "search_tests", bool(results), len(results))

        if not results:
            return "No test cases found. Use write_test_case to document tests." + _nudge(ctx.name)

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
        return "\n".join(output) + _nudge(ctx.name)

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
        mcp_ctx: Context = None,
    ) -> str:
        """Create a bugfix summary .md file, index it immediately, and auto-push to git.

        MANDATORY after every bug fix — these summaries are retrieved during
        future debugging sessions to avoid repeating the same mistakes.

        Side effects: creates bugfix-log/YYYY-MM-DD-{slug}.md in the knowledge
        repo docs path, indexes it into the vector store, and pushes to the
        remote git repo if MCP_GIT_REPO_URL is configured. Overwrites an
        existing file if the same title is used on the same day.

        Use write_architecture_doc() for design decisions,
        write_best_practice() for recurring patterns.

        Args:
            title: Short, descriptive title of the bug (used in filename)
            root_cause: What was the actual cause? (be technical)
            solution: How was it fixed? (describe code changes made)
            lesson_learned: What should be done differently next time?
            affected_files: Comma-separated list of changed files (optional)
            tags: Comma-separated categories, e.g. "auth,race-condition,critical" (optional)
            project: Target project name (optional)

        Returns:
            Saved filename, chunk count, and whether auto-push succeeded.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err
        _telem(ctx.name, "write_bugfix_summary")

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
        mcp_ctx: Context = None,
    ) -> str:
        """Create an architecture decision or system design document, index it, and auto-push.

        Side effects: creates architecture/YYYY-MM-DD-{slug}.md in the docs path,
        indexes it into the vector store, and pushes to git if configured.
        Overwrites an existing file with the same title.

        Use for system design, ADRs, and component relationships.
        Use write_api_doc() for HTTP endpoint specs, write_best_practice()
        for coding patterns, write_bugfix_summary() after fixing bugs.
        Include a Mermaid diagram in the diagrams field for best results.

        Args:
            title: Short title (e.g. "Payment Service Architecture")
            overview: High-level description of the system/component
            decisions: Key architectural decisions made and why
            trade_offs: Alternatives considered and rejected, pros/cons
            components: Optional component breakdown (optional)
            diagrams: Optional Mermaid or ASCII diagrams (optional)
            project: Target project name (optional)

        Returns:
            Saved filename, chunk count, and whether auto-push succeeded.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err
        _telem(ctx.name, "write_architecture_doc")

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
        mcp_ctx: Context = None,
    ) -> str:
        """Create an API endpoint document, index it, and auto-push to git.

        Side effects: creates api/{slug}.md in the docs path, indexes it into
        the vector store, and pushes to git if configured. Overwrites an
        existing file with the same title.

        Use for HTTP endpoints, REST APIs, and RPC schemas.
        Use write_architecture_doc() for system-level design decisions.
        Use write_best_practice() for API coding conventions.

        Args:
            title: Short title (e.g. "Create User Endpoint")
            endpoint: URL path (e.g. "/api/v1/users")
            method: HTTP method: GET, POST, PUT, PATCH, DELETE, etc.
            request_schema: Request body or query params description
            response_schema: Response body schema and status codes
            auth: Authentication/authorization requirements (optional)
            examples: Curl or code examples (optional)
            project: Target project name (optional)

        Returns:
            Saved filename, chunk count, and whether auto-push succeeded.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err
        _telem(ctx.name, "write_api_doc")

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
        mcp_ctx: Context = None,
    ) -> str:
        """Create a coding standard or best practice document, index it, and auto-push.

        Side effects: creates best-practices/{slug}.md in the docs path,
        indexes it into the vector store, and pushes to git if configured.
        Overwrites an existing file with the same title.

        Use for recurring patterns, conventions, and rules the team should follow.
        Use write_architecture_doc() for system-level decisions,
        write_bugfix_summary() after fixing a specific bug.

        Args:
            title: Short title (e.g. "Error Handling in API Routes")
            context: When and where this practice applies
            rule: The actual rule or pattern to follow (be specific)
            rationale: Why this rule exists and what problems it prevents
            examples: Code examples showing correct vs incorrect usage (optional)
            project: Target project name (optional)

        Returns:
            Saved filename, chunk count, and whether auto-push succeeded.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err
        _telem(ctx.name, "write_best_practice")

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
        mcp_ctx: Context = None,
    ) -> str:
        """Create a setup, deployment, or infrastructure document, index it, and auto-push.

        Side effects: creates setup/{slug}.md in the docs path, indexes it
        into the vector store, and pushes to git if configured. Overwrites
        an existing file with the same title.

        Use for environment setup guides, CI/CD configuration, Docker or
        infrastructure docs, and deployment runbooks.
        Use write_architecture_doc() for system design rather than how-to guides.

        Args:
            title: Short title (e.g. "Local Development Setup")
            prerequisites: Tools, accounts, or config required before starting
            steps: Step-by-step instructions (numbered list recommended)
            verification: How to confirm the setup is working correctly
            troubleshooting: Common issues and their fixes (optional)
            project: Target project name (optional)

        Returns:
            Saved filename, chunk count, and whether auto-push succeeded.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err
        _telem(ctx.name, "write_setup_doc")

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
        mcp_ctx: Context = None,
    ) -> str:
        """Create a changelog entry for a release, index it, and auto-push to git.

        Side effects: creates changelog/{version-slug}.md in the docs path,
        indexes it into the vector store, and pushes to git if configured.
        Calling twice with the same version overwrites the existing entry.
        Returns an error if none of added/changed/fixed/breaking is provided.

        Use for release notes and version history. At least one of the
        content fields (added, changed, fixed, breaking) must be non-empty.

        Args:
            version: Version string (e.g. "2.1.0" or "v3.9.40")
            release_date: ISO date string (e.g. "2026-05-03")
            added: New features added in this release (optional)
            changed: Changes to existing functionality (optional)
            fixed: Bug fixes included (optional)
            breaking: Breaking changes requiring migration (optional)
            project: Target project name (optional)

        Returns:
            Saved filename, chunk count, and whether auto-push succeeded.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err
        _telem(ctx.name, "write_changelog_entry")

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
        mcp_ctx: Context = None,
    ) -> str:
        """Create a test case document, index it immediately, and auto-push to git.

        Call search_tests() first to check for existing coverage before adding
        a new test case.

        Side effects: creates tests/YYYY-MM-DD-{slug}.md in the docs path,
        indexes it into the vector store, and pushes to git if configured.

        Use after writing or modifying tests to make them discoverable.
        Status values: "pass", "fail", "blocked", "pending" (default: pending).

        Args:
            title: Short test case title (e.g. "User login with expired token")
            scenario: What is being tested and why (the test intent)
            steps: Step-by-step test procedure
            expected_result: What should happen when the test passes
            preconditions: Setup required before running the test (optional)
            actual_result: Observed result if already executed (optional)
            status: "pass", "fail", "blocked", or "pending" (optional)
            tags: Comma-separated tags, e.g. "auth,regression,critical" (optional)
            project: Target project name (optional)

        Returns:
            Saved filename, chunk count, and whether auto-push succeeded.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err
        _telem(ctx.name, "write_test_case")

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
    def validate_doc(content: str, category: str = "docs", project: str = "", mcp_ctx: Context = None) -> str:
        """Validate a markdown document before committing it to the knowledge repo. Read-only.

        Does not write any files or modify the index. Not needed when using
        the write_*() tools — they validate internally. Use this only when
        you are writing raw markdown and committing it manually via git.

        Args:
            content: Full markdown content to validate
            category: Target category — one of: "architecture", "api",
                      "bugfix", "best-practice", "setup", "changelog", "test", "docs"
            project: Target project name (optional)

        Returns:
            "OK" if the document passes all checks, or a list of issues
            tagged [!] critical (blocks indexing), [~] warning, [i] info.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
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
    def get_index_stats(project: str = "", mcp_ctx: Context = None) -> str:
        """Show vector index statistics for the active project. Read-only, no side effects.

        Use to check how many chunks are indexed, verify a reindex completed,
        or inspect the embedding model and chunking configuration.
        Use check_knowledge_quality() instead when you want quality issues, not stats.

        Args:
            project: Target project name (optional)

        Returns:
            Total chunk count, docs path, embedding provider and model,
            chunking strategy, and per-document-type chunk distribution.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
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
    def reindex(force: bool = False, project: str = "", mcp_ctx: Context = None) -> str:
        """Re-index the knowledge base docs into the vector store.

        Modifies the vector index in place. Does not modify source .md files.
        By default only re-embeds changed files (fast, diff-aware). Set
        force=True to rebuild all embeddings from scratch — use this after
        changing the embedding model, not for routine updates.

        Use git_pull_reindex() instead when the docs changes came from a
        git push to the knowledge repo.

        Args:
            force: Rebuild all embeddings from scratch, not just changed files
                   (default: False — use only when changing embedding model)
            project: Target project name (optional)

        Returns:
            Files indexed, changed, skipped; chunks upserted; stale chunks removed.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
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
    def git_pull_reindex(project: str = "", mcp_ctx: Context = None) -> str:
        """Pull latest commits from the knowledge repo git remote, then re-index.

        Call this AFTER pushing .md files to the knowledge repo. Runs
        'git pull' on the cloned docs directory, then re-indexes only changed
        files. No-op if the repo is already up to date.

        Requires MCP_GIT_REPO_URL to be configured. Use reindex() instead
        when files were written locally (not via git push).

        Args:
            project: Target project name (optional)

        Returns:
            "Already up to date" if no changes, otherwise files indexed,
            chunks upserted, and stale chunks removed.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
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
    def check_knowledge_quality(project: str = "", mcp_ctx: Context = None) -> str:
        """Validate the knowledge base for consistency and structural correctness. Read-only.

        Does not modify any files or the vector index. Use periodically
        or after adding many documents to spot quality regressions.
        Use validate_doc() instead to check a single document before committing.
        Use get_index_stats() to check chunk counts rather than quality.

        Args:
            project: Target project name (optional)

        Returns:
            Quality score 0–100, counts of critical/warning/info issues,
            and a per-file issue list tagged [!] critical, [~] warning, [i] info.
            Critical issues cause files to be skipped during indexing.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
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
    def list_projects(mcp_ctx: Context = None) -> str:
        """List all registered projects with chunk counts and health stats. Read-only.

        Use to check which projects exist, their index sizes, quality scores,
        and git repo URLs. Use get_active_project() to check only the active
        project for the current session.

        Returns:
            Per-project summary: name (with active marker), total chunks,
            quality score, docs path, and git repo URL if configured.
            Returns setup instructions when no projects are registered.
        """
        projects = registry.all()
        if not projects:
            return (
                "No projects registered. "
                "Call setup_project(name='...') to create one."
            )

        current_active = _get_active(mcp_ctx)
        lines = [f"**{len(projects)} project(s) registered:**\n"]
        for ctx in projects:
            stats = ctx.indexer.stats
            health = ctx.health.status
            qs = health.get("quality_score")
            qs_str = f"{qs}/100" if qs is not None else "–"
            active = " ← **active**" if ctx.name == current_active else ""
            lines.append(
                f"- **{ctx.name}**{active} — {stats['total_chunks']} chunks, "
                f"quality {qs_str}, "
                f"path: `{stats['docs_path']}`"
            )
            if ctx.merged_config.git_repo_url:
                lines.append(f"  git: `{ctx.merged_config.git_repo_url}`")
        return "\n".join(lines)

    # ── Project management tools ────────────────────────

    @mcp.tool()
    def setup_project(
        name: str,
        git_repo_url: str = "",
        git_branch: str = "main",
        display_name: str = "",
        git_auto_push: bool = True,
        git_sync_interval: int = 300,
        mcp_ctx: Context = None,
    ) -> str:
        """Register and initialise a new project in Flaiwheel.

        Side effects: creates a project directory under MCP_DOCS_PATH, optionally
        clones the git knowledge repo, runs an initial index, and binds this
        session to the new project. Idempotent — safe to call again if the
        project already exists (just rebinds the session).

        Call once per project. Use set_project() to switch between already
        registered projects. Use list_projects() to see what exists.

        Args:
            name: Short project identifier, no spaces (e.g. "my-app")
            git_repo_url: HTTPS URL of the knowledge git repo (optional,
                          can be added later via the Web UI)
            git_branch: Branch to track for git sync (default: "main")
            display_name: Human-readable label shown in the Web UI (optional)
            git_auto_push: Auto-commit and push write_*() docs to git (default: True)
            git_sync_interval: Background git pull interval in seconds (default: 300)

        Returns:
            Project name, chunk count, active-project confirmation, and next steps.
        """
        if registry.get(name):
            _set_active(mcp_ctx, name)
            ctx = registry.get(name)
            return (
                f"Project '{name}' already exists "
                f"({ctx.indexer.stats['total_chunks']} chunks). "
                f"Active project set to **{name}**."
            )

        pc = ProjectConfig(
            name=name,
            display_name=display_name or name,
            git_repo_url=git_repo_url,
            git_branch=git_branch,
            git_auto_push=git_auto_push,
            git_sync_interval=git_sync_interval,
        )
        try:
            ctx = registry.setup_new_project(pc)
        except Exception as e:
            return f"Failed to set up project: {e}"

        _set_active(mcp_ctx, name)

        return (
            f"Project **{name}** created and indexed "
            f"({ctx.indexer.stats['total_chunks']} chunks).\n"
            f"Active project set to **{name}** — all subsequent calls target this project.\n\n"
            f"Next steps:\n"
            f"- `search_docs('...')` to query the knowledge base\n"
            f"- `write_bugfix_summary(...)` after every bugfix\n"
            f"- `git_pull_reindex()` after pushing docs to the knowledge repo"
        )

    @mcp.tool()
    def set_project(name: str, mcp_ctx: Context = None) -> str:
        """Bind all subsequent tool calls in this session to a specific project.

        In-memory only — no files are created or modified. The binding is
        per-connection: setting project A in workspace-1 does not affect
        workspace-2. The project= parameter on individual tools overrides
        this session binding for a single call.

        Call at the START of every session. Use setup_project() to create
        a new project. Use get_active_project() to check the current binding.

        Args:
            name: Name of a registered project (see list_projects())

        Returns:
            Active project name, chunk count, and docs path on success.
            Lists available projects and suggests setup_project() on failure.
        """
        ctx = registry.get(name)
        if ctx is None:
            names = registry.names()
            if not names:
                return (
                    f"Project '{name}' not found and no projects registered. "
                    f"Call setup_project(name='{name}') to create it."
                )
            return (
                f"Project '{name}' not found. "
                f"Available: {', '.join(names)}.\n"
                f"Call setup_project(name='{name}') to create it, "
                f"or set_project('one-of-the-above') to switch."
            )

        _set_active(mcp_ctx, name)

        stats = ctx.indexer.stats
        return (
            f"Active project set to **{name}** "
            f"({stats['total_chunks']} chunks, "
            f"path: `{stats['docs_path']}`).\n"
            f"All subsequent tool calls will target this project."
        )

    @mcp.tool()
    def get_active_project(mcp_ctx: Context = None) -> str:
        """Show the active project for this session. Read-only, no side effects.

        Use to verify which project is bound before making tool calls.
        Use set_project() to change the binding. Use list_projects() to see
        all registered projects and their stats.

        Returns:
            Active project name, chunk count, and docs path when bound.
            Instructions to call set_project() or setup_project() when not bound.
        """
        current = _get_active(mcp_ctx)
        if current and registry.get(current):
            ctx = registry.get(current)
            stats = ctx.indexer.stats
            return (
                f"Active project: **{current}** "
                f"({stats['total_chunks']} chunks, "
                f"path: `{stats['docs_path']}`)"
            )
        names = registry.names()
        if not names:
            return "No active project. No projects registered. Call setup_project() first."
        if len(names) == 1:
            return (
                f"No active project set (auto-using '{names[0]}' as the only project). "
                f"Call set_project('{names[0]}') to make it explicit."
            )
        return (
            f"No active project set. {len(names)} projects available: "
            f"{', '.join(names)}. Call set_project('name') to bind one."
        )

    # ── Bootstrap / Cleanup tools ────────────────────────

    _bootstrap_cache: dict[str, KnowledgeBootstrap] = {}

    @mcp.tool()
    def analyze_knowledge_repo(project: str = "", mcp_ctx: Context = None) -> str:
        """Analyse the knowledge repo for structure issues, duplicates, and misplaced files.

        Read-only — no files are modified. Scans files already inside the
        knowledge repo (inside the Docker volume), not the project source repo.
        Caches the report in memory so execute_cleanup() can act on it in the
        same session.

        To classify and migrate files from the project source repo use
        classify_documents() instead. For a simpler quality check without
        cleanup proposals use check_knowledge_quality().

        Args:
            project: Target project name (optional)

        Returns:
            Structured report with file counts by category, duplicate pairs,
            misplaced files, and numbered proposed cleanup actions (a1, a2, …)
            ready for execute_cleanup().
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err

        docs = Path(ctx.merged_config.docs_path)
        bootstrap = KnowledgeBootstrap(
            docs_path=docs,
            embedding_fn=registry.embedding_fn,
            quality_checker=ctx.quality_checker,
        )
        report = bootstrap.analyze()
        _bootstrap_cache[ctx.name] = bootstrap
        return format_report(report)

    @mcp.tool()
    def execute_cleanup(actions: str, project: str = "", mcp_ctx: Context = None) -> str:
        """Execute approved cleanup actions from analyze_knowledge_repo().

        Side effects: moves files within the knowledge repo using git mv
        (preserves git history) and creates missing category directories.
        NEVER deletes any file. Requires analyze_knowledge_repo() to have
        been called first in this session.

        Use "all" to execute every proposed action, or pass a comma-separated
        list of specific action IDs (e.g. "a1,a3") to cherry-pick.
        Call reindex() after cleanup to rebuild the search index.

        Args:
            actions: Comma-separated action IDs from the analysis report,
                     e.g. "a1,a2,a5", or "all" to execute everything
            project: Target project name (optional)

        Returns:
            Per-action results (directories created, files moved), any errors,
            and a rollback command to undo the moves if needed.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err

        bootstrap = _bootstrap_cache.get(ctx.name)
        if not bootstrap or not bootstrap.last_report:
            return (
                "No analysis report available. "
                "Call analyze_knowledge_repo() first."
            )

        if actions.strip().lower() == "all":
            action_ids = [
                a["id"] for a in bootstrap.last_report["proposed_actions"]
            ]
        else:
            action_ids = [a.strip() for a in actions.split(",") if a.strip()]

        if not action_ids:
            return "No action IDs provided."

        result = bootstrap.execute(action_ids)

        lines = [
            f"**Cleanup executed:** {result['executed']} action(s)\n",
        ]
        for r in result.get("results", []):
            if r["type"] == "create_dir":
                lines.append(f"- Created directory (action {r['id']})")
            elif r["type"] == "move":
                lines.append(f"- Moved `{r['from']}` → `{r['to']}` (action {r['id']})")
            elif r["type"] == "flag_review":
                lines.append(f"- Flagged for review (action {r['id']})")

        if result.get("errors"):
            lines.append(f"\n**Errors:** {len(result['errors'])}")
            for e in result["errors"]:
                lines.append(f"- {e}")

        if result.get("rollback_command"):
            lines.append(f"\n**Rollback:** `{result['rollback_command']}`")

        lines.append(
            "\n**Next:** Call `reindex()` to rebuild the search index, "
            "then `check_knowledge_quality()` to verify improvement."
        )

        return "\n".join(lines)

    # ── Remote Classification (for project repo docs) ────

    _classifier_cache: Optional[DocumentClassifier] = None

    @mcp.tool()
    def classify_documents(files: str, project: str = "", mcp_ctx: Context = None) -> str:
        """Classify project repo documents for migration into the knowledge base. Read-only.

        Does not write any files. The agent reads project files locally and
        passes their content here; the Docker container cannot access the
        project source repo directly. Flaiwheel classifies each file by
        semantic similarity and returns a migration plan.

        Trigger: user says "This is the Way" or "42".
        Step 1 of the migration workflow — after classification, use the
        suggested write_*() tool for each file to push it into the knowledge base.
        Use analyze_knowledge_repo() instead when files are already inside the
        knowledge repo and need reorganisation.

        Args:
            files: JSON array of {"path": "...", "content": "..."} objects.
                   Send the first ~2000 characters of each file as content.
                   Example: [{"path": "docs/auth.md", "content": "# Auth..."}]
            project: Target project name (optional)

        Returns:
            Per-file classification (category, suggested write_*() tool),
            duplicate detection, and a step-by-step migration plan.
        """
        nonlocal _classifier_cache

        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err

        try:
            file_list = json.loads(files)
        except (json.JSONDecodeError, TypeError) as e:
            return (
                f"Invalid JSON in 'files' parameter: {e}\n\n"
                "Expected format: [{\"path\": \"file.md\", \"content\": \"first 2000 chars...\"}]"
            )

        if not isinstance(file_list, list):
            return "The 'files' parameter must be a JSON array of objects."

        if _classifier_cache is None:
            _classifier_cache = DocumentClassifier(embedding_fn=registry.embedding_fn)

        result = _classifier_cache.classify(file_list)
        return format_classification_report(result)

    # ── Cold-Start Source Code Analyzer ─────────────────

    @mcp.tool()
    def analyze_codebase(
        path: str, force: bool = False, project: str = "", mcp_ctx: Context = None
    ) -> str:
        """Analyze a source code directory and return a cold-start bootstrap report. Read-only.

        Does not modify source files or the vector index. Runs entirely
        server-side using Python ast, regex, and local MiniLM embeddings —
        no cloud calls, no token cost.

        The report is cached at /data/coldstart-{project}.md after the first
        run and returned instantly on subsequent calls. Use force=True only
        after significant code changes — not for routine sessions.

        Use at the START of work on an unfamiliar codebase instead of reading
        dozens of files. Then use the write_*() tools to document the top
        files identified in the report. Use classify_documents() for existing
        .md files in the project repo.

        The path must be accessible inside the Docker container (i.e. mounted
        as a volume). It cannot reach paths on the host that are not mounted.

        Args:
            path: Absolute path to the source directory to scan
            force: Regenerate even if a cached report exists (default: False)
            project: Target project name (optional)

        Returns:
            Markdown report (~5–20 KB) with language distribution, category map,
            top 20 files ranked by documentability, near-duplicate file pairs,
            undocumented directories, and recommended next steps.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err
        _telem(ctx.name, "analyze_codebase")

        resolved = Path(path).resolve()

        if not resolved.is_absolute():
            return f"Error: path must be absolute. Got: {path}"
        if not resolved.exists():
            return f"Error: path does not exist: {resolved}"
        if not resolved.is_dir():
            return f"Error: path is not a directory: {resolved}"

        cache_dir = Path("/data")
        if not cache_dir.exists():
            cache_dir = Path.home() / ".flaiwheel"
            cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"coldstart-{ctx.name}.md"

        if not force and cache_file.exists():
            return cache_file.read_text(encoding="utf-8")

        analyzer = CodebaseAnalyzer(embedding_fn=registry.embedding_fn)
        result = analyzer.analyze(str(resolved))
        report = format_codebase_report(result)

        try:
            cache_file.write_text(report, encoding="utf-8")
        except OSError:
            pass

        return report

    @mcp.tool()
    def check_update() -> str:
        """Check whether a newer Flaiwheel version is available on GitHub. Read-only.

        Makes a single network request to GitHub (git ls-remote) to compare
        version tags against the running version. No files are modified.
        Use when you suspect Flaiwheel may be outdated, or periodically to
        keep the server current.

        Returns:
            "Up to date" message, or the available version number plus the
            exact bash command to give the user for upgrading.
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

    # ── Session memory tools ─────────────────────────────

    @mcp.tool()
    def save_session_summary(
        summary: str,
        decisions: str = "",
        open_questions: str = "",
        files_modified: str = "",
        project: str = "",
        mcp_ctx: Context = None,
    ) -> str:
        """Append a session summary to the project's session log.

        Side effects: appends a JSON entry to /data/sessions-{project}.json.
        Does not modify the vector index or the knowledge repo. Safe to call
        multiple times in one session — each call adds a new entry.

        Call at the END of every session. Use get_recent_sessions() at the
        START of the next session to restore context.

        Args:
            summary: What was accomplished this session (1–3 sentences)
            decisions: Key decisions made, comma-separated (optional)
            open_questions: Unresolved questions or next steps, comma-separated (optional)
            files_modified: Files changed, comma-separated (optional)
            project: Target project name (optional)

        Returns:
            Confirmation with the project name and total session count stored.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err
        _telem(ctx.name, "save_session_summary")

        session = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary.strip(),
            "decisions": [d.strip() for d in decisions.split(",") if d.strip()] if decisions else [],
            "open_questions": [q.strip() for q in open_questions.split(",") if q.strip()] if open_questions else [],
            "files_modified": [f.strip() for f in files_modified.split(",") if f.strip()] if files_modified else [],
        }

        sessions = _load_sessions(ctx.name)
        sessions.append(session)
        _save_sessions(ctx.name, sessions)

        return f"Session summary saved for project '{ctx.name}'. Total sessions: {len(sessions)}."

    @mcp.tool()
    def get_recent_sessions(
        limit: int = 5,
        project: str = "",
        mcp_ctx: Context = None,
    ) -> str:
        """Retrieve recent session summaries to restore context. Read-only.

        Reads from /data/sessions-{project}.json. Does not modify any data.
        Call at the START of every session before any other tools to understand
        what was done previously and pick up open questions.
        Use save_session_summary() at the END of a session to store context.

        Args:
            limit: Number of most-recent sessions to return (default: 5, max: 20)
            project: Target project name (optional)

        Returns:
            Timestamped session entries showing summary, decisions, open
            questions, and modified files for each session, newest first.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err

        limit = min(max(1, limit), 20)
        sessions = _load_sessions(ctx.name)

        if not sessions:
            return f"No session history for project '{ctx.name}'. Start documenting sessions with save_session_summary()."

        recent = sessions[-limit:]
        recent.reverse()

        lines = [f"## Recent Sessions for '{ctx.name}' ({len(recent)} of {len(sessions)} total)\n"]
        for i, s in enumerate(recent, 1):
            ts = s.get("timestamp", "unknown")
            lines.append(f"### Session {i} — {ts}")
            lines.append(f"**Summary:** {s.get('summary', '–')}")
            if s.get("decisions"):
                lines.append("**Decisions:** " + " | ".join(s["decisions"]))
            if s.get("open_questions"):
                lines.append("**Open questions:** " + " | ".join(s["open_questions"]))
            if s.get("files_modified"):
                lines.append("**Files modified:** " + ", ".join(s["files_modified"]))
            lines.append("")

        return "\n".join(lines)

    @mcp.tool()
    def get_file_context(
        filename: str,
        project: str = "",
        mcp_ctx: Context = None,
    ) -> str:
        """Retrieve knowledge base context relevant to a specific source file. Read-only.

        Runs multiple semantic searches derived from the filename and returns
        architecture decisions, past bugfixes, and best practices related to
        that file — without requiring a manual search query. No files modified.

        Complements get_recent_sessions() (temporal context) with file-level
        spatial context. Use before reading or editing any source file.
        Use search_docs() for free-form queries not tied to a specific file.

        Args:
            filename: File path or name being opened/edited, e.g.
                      "payment.service.ts" or "src/auth/jwt.py"
            project: Target project name (optional)

        Returns:
            Relevant architecture docs, bugfix summaries, and best practices
            for the given file, ranked by relevance. Returns "no context found"
            when the knowledge base has nothing for that file yet.
        """
        ctx, err = _ctx(project or None, mcp_ctx)
        if not ctx:
            return err
        _telem(ctx.name, "get_file_context")

        # Build a multi-term query from the filename parts:
        # "src/payment/stripe-webhook.service.ts" → "stripe webhook payment service"
        from pathlib import Path as _Path
        p = _Path(filename)
        # stem without extension suffixes (e.g. "stripe-webhook.service" → "stripe webhook service")
        stem = re.sub(r"\.", " ", p.stem)
        # parent directory name (skip generic names like "src", "lib", "app")
        _skip = {"src", "lib", "app", "components", "utils", "helpers", "common", "shared", ".", ""}
        parent = p.parent.name if p.parent.name not in _skip else ""
        query = f"{stem} {parent}".strip()

        results = ctx.indexer.search(query, top_k=4)
        ctx.health.record_search("get_file_context", bool(results))
        _record_search_result(ctx.name, "get_file_context", bool(results), len(results))

        if not results:
            return (
                f"No Flaiwheel context found for `{filename}`.\n"
                "This may be a documentation gap — consider documenting decisions "
                "related to this module after your changes."
            )

        lines = [
            f"## Flaiwheel Context for `{filename}`\n",
            f"*{len(results)} relevant knowledge entries found. "
            "Integrate this context before making changes.*\n",
        ]
        for r in results:
            loc = r["source"]
            relevance = r.get("relevance", 0)
            doc_type = r.get("type", "—")
            heading = r.get("heading", "")
            text = r.get("text", "")[:600]
            lines.append(f"### {heading or loc}")
            lines.append(f"*Source: `{loc}` | Type: {doc_type} | Relevance: {relevance}%*\n")
            lines.append(text)
            lines.append("")

        return "\n".join(lines) + _nudge(ctx.name)

    mcp.get_telemetry_data = get_telemetry_data
    mcp.get_impact_metrics = get_impact_metrics
    mcp.record_ci_guardrail_report = record_ci_guardrail_report
    return mcp
