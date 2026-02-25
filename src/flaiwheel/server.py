# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# Non-commercial use only. Commercial licensing: info@4rce.com

"""
MCP Server factory – creates a FastMCP instance with tools
that share the indexer/config from the main process.

Tools:
  - search_docs: Semantic search across all docs
  - search_bugfixes: Search only bugfix summaries
  - search_by_type: Search filtered by document type
  - write_bugfix_summary: Document a bugfix + index immediately
  - get_index_stats: Index statistics
  - reindex: Manual re-index
  - check_knowledge_quality: Validate knowledge base consistency
"""
import re
import threading
from datetime import date
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from .config import Config
from .indexer import DocsIndexer
from .quality import KnowledgeQualityChecker
from .watcher import GitWatcher


def create_mcp_server(
    config: Config,
    indexer: DocsIndexer,
    index_lock: threading.Lock,
    watcher: GitWatcher,
    quality_checker: KnowledgeQualityChecker,
) -> FastMCP:
    """Factory: returns a configured FastMCP server that shares state with web.py."""

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
            "6. Periodically call check_knowledge_quality() to maintain docs"
        ),
    )

    @mcp.tool()
    def search_docs(query: str, top_k: int = 5) -> str:
        """Semantic search over the ENTIRE project documentation.
        Returns only the most relevant chunks (token-efficient!).

        Use this ALWAYS before writing or changing code.

        Args:
            query: What you want to know (natural language, be specific)
            top_k: Number of results (default: 5, increase for broad questions)

        Returns:
            Relevant doc chunks with source reference and relevance score
        """
        results = indexer.search(query, top_k=top_k)

        if not results:
            return (
                "No relevant documents found. "
                "Try a different or more specific query."
            )

        output = []
        for r in results:
            output.append(
                f"**{r['source']}** > _{r['heading']}_ "
                f"(Relevance: {r['relevance']}%, Type: {r['type']})\n\n"
                f"{r['text']}\n\n---"
            )
        return "\n".join(output)

    @mcp.tool()
    def search_bugfixes(query: str, top_k: int = 5) -> str:
        """Search ONLY bugfix summaries for similar past problems.
        Use this to learn from earlier bugs and avoid repetition.

        Args:
            query: Description of the current problem/bug
            top_k: Number of results (default: 5)

        Returns:
            Similar bugfix summaries with root cause, solution and lessons learned
        """
        results = indexer.search(query, top_k=top_k, type_filter="bugfix")

        if not results:
            return (
                "No similar bugfixes found - this might be a new problem. "
                "Don't forget to call write_bugfix_summary() after fixing!"
            )

        output = [f"Found {len(results)} similar bugfixes\n"]
        for r in results:
            output.append(
                f"### {r['source']} (Relevance: {r['relevance']}%)\n\n"
                f"{r['text']}\n\n---"
            )
        return "\n".join(output)

    @mcp.tool()
    def search_by_type(query: str, doc_type: str, top_k: int = 5) -> str:
        """Search filtered by document type.

        Args:
            query: Search query
            doc_type: One of: "docs", "bugfix", "best-practice", "api",
                      "architecture", "changelog", "setup", "readme"
            top_k: Number of results
        """
        results = indexer.search(query, top_k=top_k, type_filter=doc_type)

        if not results:
            return f"No results of type '{doc_type}' found."

        output = []
        for r in results:
            output.append(
                f"**{r['source']}** > _{r['heading']}_ ({r['relevance']}%)\n\n"
                f"{r['text']}\n\n---"
            )
        return "\n".join(output)

    @mcp.tool()
    def write_bugfix_summary(
        title: str,
        root_cause: str,
        solution: str,
        lesson_learned: str,
        affected_files: str = "",
        tags: str = "",
    ) -> str:
        """Write a bugfix summary as .md file and index it IMMEDIATELY.

        MUST be called after every bugfix! These summaries are found during
        future bugs and help avoid repeating mistakes.

        Args:
            title: Short, descriptive title of the bug
            root_cause: What was the actual cause? (technical)
            solution: How was it fixed? (describe code changes)
            lesson_learned: What should be done differently in the future?
            affected_files: Affected files (comma-separated)
            tags: Categories (e.g. "payment,race-condition,critical")
        """
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        filename = f"bugfix-log/{date.today().isoformat()}-{slug}.md"

        filepath = Path(config.docs_path) / filename
        safe_base = Path(config.docs_path).resolve()
        if not filepath.resolve().is_relative_to(safe_base):
            return "Error: Invalid title - path traversal detected."

        filepath.parent.mkdir(parents=True, exist_ok=True)

        content = (
            f"# {title}\n\n"
            f"**Date:** {date.today().isoformat()}  \n"
            f"**Tags:** {tags}  \n"
            f"**Affected files:** {affected_files}\n\n"
            f"## Root Cause\n{root_cause}\n\n"
            f"## Solution\n{solution}\n\n"
            f"## Lesson Learned\n{lesson_learned}\n"
        )

        filepath.write_text(content, encoding="utf-8")
        chunk_count = indexer.index_single(filename, content)

        watcher.push_pending()

        return (
            f"Bugfix summary saved and indexed!\n"
            f"  File: {filename}\n"
            f"  Chunks: {chunk_count}\n"
            f"  Auto-pushed to remote: {config.git_auto_push and bool(config.git_repo_url)}\n"
            f"  Will be found for similar bugs from now on."
        )

    @mcp.tool()
    def get_index_stats() -> str:
        """Show statistics about the current vector index."""
        stats = indexer.stats

        type_dist = "\n".join(
            f"  - {t}: {c} chunks" for t, c in stats["type_distribution"].items()
        ) or "  (empty)"

        return (
            f"**Index Statistics**\n\n"
            f"- **Chunks total:** {stats['total_chunks']}\n"
            f"- **Docs path:** {stats['docs_path']}\n"
            f"- **Embedding:** {stats['embedding_provider']} ({stats['embedding_model']})\n"
            f"- **Chunking:** {stats['chunk_strategy']}\n\n"
            f"**Type distribution:**\n{type_dist}"
        )

    @mcp.tool()
    def reindex() -> str:
        """Re-index all documentation. Use when many files changed."""
        with index_lock:
            result = indexer.index_all()
        return (
            f"Re-index complete!\n"
            f"  Files: {result['files_indexed']}\n"
            f"  Chunks: {result['chunks_created']}\n"
            f"  Stale removed: {result['chunks_removed']}"
        )

    @mcp.tool()
    def check_knowledge_quality() -> str:
        """Validate the knowledge base for consistency, completeness
        and structural correctness. Returns a quality score (0-100)
        and a list of issues to fix.

        Call this periodically to keep the knowledge base clean.
        Fix critical issues immediately – they reduce search quality.
        """
        report = quality_checker.check_all()

        lines = [
            f"**Knowledge Quality Score: {report['score']}/100**\n",
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

    return mcp
