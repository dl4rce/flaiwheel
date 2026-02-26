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
from . import __version__
from .config import Config
from .health import HealthTracker
from .indexer import DocsIndexer
from .quality import KnowledgeQualityChecker
from .watcher import GitWatcher

GITHUB_REPO = "dl4rce/flaiwheel"


def create_mcp_server(
    config: Config,
    indexer: DocsIndexer,
    index_lock: threading.Lock,
    watcher: GitWatcher,
    quality_checker: KnowledgeQualityChecker,
    health: HealthTracker | None = None,
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
        if health:
            health.record_search("search_docs", bool(results))

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
        if health:
            health.record_search("search_bugfixes", bool(results))

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
    def search_by_type(query: str, doc_type: str, top_k: int = 5) -> str:
        """Search filtered by document type.

        Args:
            query: Search query
            doc_type: One of: "docs", "bugfix", "best-practice", "api",
                      "architecture", "changelog", "setup", "readme"
            top_k: Number of results
        """
        results = indexer.search(query, top_k=top_k, type_filter=doc_type)
        if health:
            health.record_search("search_by_type", bool(results))

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
    def reindex(force: bool = False) -> str:
        """Re-index documentation. Diff-aware by default (only changed files).
        Set force=True to rebuild all embeddings from scratch.

        Args:
            force: If True, re-embed all files regardless of changes (default: False)
        """
        with index_lock:
            result = indexer.index_all(force=force)
        return (
            f"Re-index complete!\n"
            f"  Files: {result['files_indexed']} ({result.get('files_changed', '?')} changed, "
            f"{result.get('files_skipped', '?')} skipped)\n"
            f"  Chunks upserted: {result.get('chunks_upserted', result.get('chunks_created', '?'))}\n"
            f"  Stale removed: {result['chunks_removed']}"
        )

    @mcp.tool()
    def git_pull_reindex() -> str:
        """Pull latest changes from the knowledge repo and re-index.

        Call this AFTER you have committed and pushed new or updated .md files
        to the knowledge repo. Flaiwheel will pull the changes and re-index
        so they become searchable immediately.

        Returns:
            Summary of pull result and reindex statistics
        """
        if not watcher or not config.git_repo_url:
            return "No git repo configured. Set MCP_GIT_REPO_URL first."

        changed = watcher.pull_and_check()
        if not changed:
            return "No new changes in knowledge repo. Already up to date."

        with index_lock:
            result = indexer.index_all()
        if health:
            health.record_index(
                ok=result.get("status") == "success",
                chunks=result.get("chunks_upserted", 0),
                files=result.get("files_indexed", 0),
            )
        return (
            f"Pulled new changes and re-indexed!\n"
            f"  Files: {result['files_indexed']} ({result.get('files_changed', '?')} changed, "
            f"{result.get('files_skipped', '?')} skipped)\n"
            f"  Chunks upserted: {result.get('chunks_upserted', result.get('chunks_created', '?'))}\n"
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

    @mcp.tool()
    def check_update() -> str:
        """Check if a newer version of Flaiwheel is available on GitHub.

        Compares the running version with the latest Git tag.
        If an update is available, returns the update command for the user.

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
