# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.md.

"""
Web-UI Backend (FastAPI) – configuration, monitoring, test search.
Runs in a background thread alongside the MCP server.

All per-project endpoints accept an optional ?project=name query parameter.
When omitted the default (first) project is used.
"""
import hashlib
import hmac
import re
import threading
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from .auth import AuthManager
from .bootstrap import KnowledgeBootstrap
from .config import LOCAL_MODELS, RERANKER_MODELS, Config
from .project import ProjectConfig, ProjectContext, ProjectRegistry, merge_config


class GlobalConfigUpdate(BaseModel):
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_embedding_model: Optional[str] = None
    chunk_strategy: Optional[str] = None
    chunk_max_chars: Optional[int] = None
    chunk_overlap: Optional[int] = None
    reranker_enabled: Optional[bool] = None
    reranker_model: Optional[str] = None
    rrf_k: Optional[int] = None
    rrf_vector_weight: Optional[float] = None
    rrf_bm25_weight: Optional[float] = None
    min_relevance: Optional[float] = None


class ProjectConfigUpdate(BaseModel):
    git_repo_url: Optional[str] = None
    git_branch: Optional[str] = None
    git_sync_interval: Optional[int] = None
    git_docs_subpath: Optional[str] = None
    git_token: Optional[str] = None
    git_auto_push: Optional[bool] = None
    display_name: Optional[str] = None


class AddProjectRequest(BaseModel):
    name: str
    display_name: str = ""
    git_repo_url: str = ""
    git_branch: str = "main"
    git_token: str = ""
    git_docs_subpath: str = ""
    git_auto_push: bool = True
    git_sync_interval: int = 300


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    type_filter: Optional[str] = None


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


class BootstrapExecuteRequest(BaseModel):
    actions: list[str]


class CaptureCommitRequest(BaseModel):
    commit_hash: str
    commit_type: str       # fix, feat, refactor, docs, perf
    commit_message: str
    commit_scope: str = ""
    files_changed: list[str] = []
    diff_summary: str = ""


class CIGuardrailReportRequest(BaseModel):
    violations_found: int = 0
    violations_blocking: int = 0
    violations_fixed_before_merge: int = 0
    cycle_time_baseline_minutes: Optional[float] = None
    cycle_time_actual_minutes: Optional[float] = None
    project: Optional[str] = None
    pr_number: Optional[int] = None
    branch: Optional[str] = None
    commit_sha: Optional[str] = None
    source: str = "github-actions"


def create_web_app(
    global_config: Config,
    registry: ProjectRegistry,
    config_lock: threading.Lock,
    auth: AuthManager,
    get_telemetry: callable = None,
    get_impact_metrics: callable = None,
    record_ci_guardrail: callable = None,
) -> FastAPI:
    """Factory: returns a FastAPI app backed by a ProjectRegistry."""

    app = FastAPI(
        title="Flaiwheel",
        description="Self-improving knowledge base for AI coding agents",
    )
    security = HTTPBasic(auto_error=False)

    def require_auth(
        request: Request,
        credentials: Optional[HTTPBasicCredentials] = Depends(security),
    ):
        # Requests from localhost are trusted without credentials.
        # This allows the post-commit git hook to call the API without
        # storing or reading any password — git CLI auth is sufficient context.
        client_host = request.client.host if request.client else ""
        if client_host in ("127.0.0.1", "::1", "localhost"):
            return "localhost"

        if credentials is None or not auth.verify(credentials.username, credentials.password):
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": 'Basic realm="Flaiwheel"'},
            )
        return credentials.username

    def _resolve(project: str | None) -> ProjectContext:
        ctx = registry.resolve(project)
        if ctx is None:
            names = registry.names()
            if not names:
                raise HTTPException(404, "No projects registered")
            raise HTTPException(404, f"Project not found. Available: {', '.join(names)}")
        return ctx

    # ── Health (no auth — Docker healthcheck) ─────────

    @app.get("/health")
    async def health_check(project: Optional[str] = Query(None)):
        from . import __version__

        if project:
            ctx = registry.resolve(project)
            if not ctx:
                return {"status": "error", "message": f"Project '{project}' not found"}
            status = ctx.health.status
            return {
                "status": "ok" if ctx.health.is_healthy else "degraded",
                "version": __version__,
                "project": ctx.name,
                "chunks": ctx.indexer.collection.count(),
                "last_index_at": status.get("last_index_at"),
                "last_index_ok": status.get("last_index_ok"),
                "last_pull_at": status.get("last_pull_at"),
                "last_pull_ok": status.get("last_pull_ok"),
                "git_commit": status.get("git_commit"),
                "git_branch": status.get("git_branch"),
                "searches_total": status.get("searches_total", 0),
                "searches_hits": status.get("searches_hits", 0),
                "searches_misses": status.get("searches_misses", 0),
                "quality_score": status.get("quality_score"),
                "quality_issues_critical": status.get("quality_issues_critical", 0),
                "skipped_files_count": len(status.get("skipped_files", [])),
                "migration_status": status.get("migration_status"),
            }

        all_healthy = True
        for ctx in registry.all():
            if not ctx.health.is_healthy:
                all_healthy = False
                break

        default = registry.get_default()
        if default:
            status = default.health.status
            return {
                "status": "ok" if all_healthy else "degraded",
                "version": __version__,
                "project": default.name,
                "project_count": len(registry),
                "chunks": default.indexer.collection.count(),
                "last_index_at": status.get("last_index_at"),
                "last_index_ok": status.get("last_index_ok"),
                "last_pull_at": status.get("last_pull_at"),
                "last_pull_ok": status.get("last_pull_ok"),
                "git_commit": status.get("git_commit"),
                "git_branch": status.get("git_branch"),
                "searches_total": status.get("searches_total", 0),
                "searches_hits": status.get("searches_hits", 0),
                "searches_misses": status.get("searches_misses", 0),
                "quality_score": status.get("quality_score"),
                "quality_issues_critical": status.get("quality_issues_critical", 0),
                "skipped_files_count": len(status.get("skipped_files", [])),
                "migration_status": status.get("migration_status"),
            }

        from . import __version__ as v
        return {"status": "ok", "version": v, "project_count": 0}

    @app.get("/api/health")
    async def health_detail(
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        ctx = _resolve(project)
        return ctx.health.status

    # ── Web Frontend ──────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def web_frontend(_user: str = Depends(require_auth)):
        template_path = Path(__file__).parent / "templates" / "index.html"
        if template_path.exists():
            return HTMLResponse(template_path.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>Template not found</h1>", status_code=500)

    # ── Project CRUD ──────────────────────────────────

    @app.get("/api/projects")
    async def list_projects(_user: str = Depends(require_auth)):
        projects = []
        for ctx in registry.all():
            stats = ctx.indexer.stats
            h = ctx.health.status
            projects.append({
                "name": ctx.name,
                "display_name": ctx.project_config.display_name,
                "chunks": stats["total_chunks"],
                "quality_score": h.get("quality_score"),
                "git_repo_url": ctx.merged_config.git_repo_url,
                "docs_path": ctx.merged_config.docs_path,
                "config": ctx.project_config.to_safe_dict(),
            })
        return {"projects": projects, "count": len(projects)}

    @app.post("/api/projects")
    async def add_project(
        req: AddProjectRequest,
        _user: str = Depends(require_auth),
    ):
        pc = ProjectConfig(
            name=req.name,
            display_name=req.display_name or req.name,
            git_repo_url=req.git_repo_url,
            git_branch=req.git_branch,
            git_token=req.git_token,
            git_docs_subpath=req.git_docs_subpath,
            git_auto_push=req.git_auto_push,
            git_sync_interval=req.git_sync_interval,
        )
        try:
            ctx = registry.setup_new_project(pc)
        except ValueError as e:
            raise HTTPException(409, str(e))
        except Exception as e:
            raise HTTPException(500, f"Failed to add project: {e}")

        return {
            "status": "success",
            "project": ctx.name,
            "chunks": ctx.indexer.stats["total_chunks"],
        }

    @app.delete("/api/projects/{name}")
    async def remove_project(name: str, _user: str = Depends(require_auth)):
        if not registry.remove(name):
            raise HTTPException(404, f"Project '{name}' not found")
        registry.save()
        return {"status": "success", "message": f"Project '{name}' removed"}

    # ── Global Config ─────────────────────────────────

    @app.get("/api/config")
    async def get_config(
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        base = global_config.to_safe_dict()
        if project:
            ctx = _resolve(project)
            base["project"] = ctx.project_config.to_safe_dict()
        return {
            "config": base,
            "available_models": LOCAL_MODELS,
            "reranker_models": RERANKER_MODELS,
        }

    @app.post("/api/config")
    async def update_global_config_endpoint(
        update: GlobalConfigUpdate,
        _user: str = Depends(require_auth),
    ):
        with config_lock:
            old_model = global_config.embedding_model
            old_provider = global_config.embedding_provider

            update_dict = update.model_dump(exclude_none=True)
            for key, value in update_dict.items():
                if hasattr(global_config, key):
                    setattr(global_config, key, value)

            global_config.save()
            registry.update_global_config(global_config)

            model_changed = (
                old_model != global_config.embedding_model
                or old_provider != global_config.embedding_provider
            )

        if model_changed:
            from chromadb.utils import embedding_functions as ef_mod
            if global_config.embedding_provider == "local":
                new_ef = ef_mod.SentenceTransformerEmbeddingFunction(
                    model_name=global_config.embedding_model
                )
            else:
                new_ef = ef_mod.OpenAIEmbeddingFunction(
                    api_key=global_config.openai_api_key,
                    model_name=global_config.openai_embedding_model,
                )
            registry.embedding_fn = new_ef

            migrations = []
            for ctx in registry.all():
                result = ctx.indexer.start_model_swap(
                    ctx.merged_config, ctx.index_lock,
                    quality_checker=ctx.quality_checker,
                    health=ctx.health,
                    new_ef=new_ef,
                )
                migrations.append({"project": ctx.name, **result})

            return {
                "status": "success",
                "message": "Config saved — model migration started for all projects",
                "model_changed": True,
                "migrations": migrations,
            }

        return {"status": "success", "message": "Config saved", "model_changed": False}

    # ── Per-project Config ────────────────────────────

    @app.post("/api/projects/{name}/config")
    async def update_project_config(
        name: str,
        update: ProjectConfigUpdate,
        _user: str = Depends(require_auth),
    ):
        ctx = _resolve(name)
        update_dict = update.model_dump(exclude_none=True)
        for key, value in update_dict.items():
            if hasattr(ctx.project_config, key):
                setattr(ctx.project_config, key, value)

        ctx.merged_config = merge_config(global_config, ctx.project_config)
        ctx.indexer.config = ctx.merged_config
        registry.save()

        return {"status": "success", "message": f"Project '{name}' config saved"}

    # ── Migration ─────────────────────────────────────

    @app.get("/api/migration/status")
    async def migration_status(
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        ctx = _resolve(project)
        return {"migration": ctx.indexer.migration_status}

    @app.post("/api/migration/cancel")
    async def cancel_migration(
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        ctx = _resolve(project)
        result = ctx.indexer.cancel_migration()
        if result["status"] == "error":
            raise HTTPException(status_code=400, detail=result["message"])
        return result

    # ── Stats / Index ─────────────────────────────────

    @app.get("/api/stats")
    async def get_stats(
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        ctx = _resolve(project)
        return ctx.indexer.stats

    @app.get("/api/telemetry")
    async def telemetry_data(
        _user: str = Depends(require_auth),
    ):
        if get_telemetry:
            return get_telemetry()
        return {}

    @app.get("/api/impact-metrics")
    async def impact_metrics(
        days: int = Query(30, ge=1, le=365),
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        if get_impact_metrics:
            return get_impact_metrics(project=project, days=days)
        return {
            "project": project or "all",
            "window_days": days,
            "search_events": 0,
            "search_hits": 0,
            "ci_reports": 0,
            "guardrail_violations_found": 0,
            "guardrail_violations_blocking": 0,
            "regressions_avoided": 0,
            "cycle_time_minutes_saved_observed": 0.0,
            "estimated_time_saved_minutes": 0.0,
            "estimated_time_saved_hours": 0.0,
            "assumptions": {},
        }

    @app.post("/api/telemetry/ci-guardrail-report")
    async def ci_guardrail_report(
        req: CIGuardrailReportRequest,
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        if not record_ci_guardrail:
            raise HTTPException(status_code=503, detail="CI telemetry reporter unavailable")

        effective_project = project or req.project
        if not effective_project:
            default_ctx = registry.get_default()
            if default_ctx:
                effective_project = default_ctx.name

        metadata = {
            "source": req.source,
            "pr_number": req.pr_number,
            "branch": req.branch,
            "commit_sha": req.commit_sha,
        }
        result = record_ci_guardrail(
            project=effective_project,
            violations_found=max(0, int(req.violations_found)),
            violations_blocking=max(0, int(req.violations_blocking)),
            violations_fixed_before_merge=max(0, int(req.violations_fixed_before_merge)),
            cycle_time_baseline_minutes=req.cycle_time_baseline_minutes,
            cycle_time_actual_minutes=req.cycle_time_actual_minutes,
            metadata=metadata,
        )
        if get_impact_metrics:
            result["impact_30d"] = get_impact_metrics(project=effective_project, days=30)
        return result

    @app.post("/api/index-flaiwheel-docs")
    async def index_flaiwheel_docs(
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        ctx = _resolve(project)
        docs_path = Path(ctx.merged_config.docs_path)
        total: int = 0
        files: list[str] = []
        for name in ("README.md", "FLAIWHEEL_TOOLS.md"):
            filepath = docs_path / name
            if filepath.exists():
                try:
                    content = filepath.read_text(encoding="utf-8", errors="ignore")
                    with ctx.index_lock:
                        n = ctx.indexer.index_single(name, content)
                    total += n
                    files.append(name)
                except Exception as e:
                    return {"status": "error", "message": str(e), "file": name}
        return {"status": "success", "chunks": total, "files": files}

    @app.post("/api/reindex")
    async def trigger_reindex(
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        ctx = _resolve(project)
        with ctx.index_lock:
            result = ctx.indexer.index_all(quality_checker=ctx.quality_checker)
        ctx.health.record_index(
            ok=result.get("status") == "success",
            chunks=result.get("chunks_upserted", 0),
            files=result.get("files_indexed", 0),
        )
        ctx.health.record_skipped_files(result.get("quality_skipped", []))
        try:
            qr = ctx.quality_checker.check_all()
            ctx.health.record_quality(
                qr["score"], qr.get("critical", 0),
                qr.get("warnings", 0), qr.get("info", 0),
            )
        except Exception:
            pass
        return result

    @app.post("/api/clear")
    async def clear_index(
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        ctx = _resolve(project)
        with ctx.index_lock:
            ctx.indexer.clear_index()
        return {"status": "success", "message": f"Index cleared for project '{ctx.name}'"}

    @app.post("/api/search")
    async def test_search(
        req: SearchRequest,
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        ctx = _resolve(project)
        results = ctx.indexer.search(
            query=req.query, top_k=req.top_k, type_filter=req.type_filter,
        )
        return {"query": req.query, "count": len(results), "results": results}

    @app.get("/api/models")
    async def get_models(_user: str = Depends(require_auth)):
        return {
            "local_models": LOCAL_MODELS,
            "reranker_models": RERANKER_MODELS,
            "current": {
                "provider": global_config.embedding_provider,
                "model": (
                    global_config.embedding_model
                    if global_config.embedding_provider == "local"
                    else global_config.openai_embedding_model
                ),
                "reranker_enabled": global_config.reranker_enabled,
                "reranker_model": global_config.reranker_model,
            },
        }

    @app.post("/api/git/pull")
    async def trigger_git_pull(
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        ctx = _resolve(project)
        if not ctx.merged_config.git_repo_url:
            return {"status": "error", "message": "No git repo configured for this project"}

        changed = ctx.watcher.pull_and_check()
        result = None
        if changed:
            with ctx.index_lock:
                result = ctx.indexer.index_all(quality_checker=ctx.quality_checker)
            ctx.health.record_index(
                ok=result.get("status") == "success",
                chunks=result.get("chunks_upserted", 0),
                files=result.get("files_indexed", 0),
            )
            ctx.health.record_skipped_files(result.get("quality_skipped", []))
            try:
                qr = ctx.quality_checker.check_all()
                ctx.health.record_quality(
                    qr["score"], qr.get("critical", 0),
                    qr.get("warnings", 0), qr.get("info", 0),
                )
            except Exception:
                pass

        return {
            "status": "success",
            "changes_detected": changed,
            "reindex_result": result,
        }

    @app.post("/api/auth/change-password")
    async def change_password(
        req: PasswordChange, _user: str = Depends(require_auth),
    ):
        with config_lock:
            ok = auth.change_password(req.old_password, req.new_password)
        if not ok:
            raise HTTPException(status_code=400, detail="Old password is incorrect")
        return {"status": "success", "message": "Password changed"}

    @app.get("/api/quality")
    async def get_quality(
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        ctx = _resolve(project)
        return ctx.quality_checker.check_all()

    # ── Bootstrap / Cleanup ─────────────────────────────

    _bootstrap_cache: dict[str, KnowledgeBootstrap] = {}

    @app.post("/api/bootstrap/analyze")
    async def bootstrap_analyze(
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        ctx = _resolve(project)
        docs = Path(ctx.merged_config.docs_path)
        bootstrap = KnowledgeBootstrap(
            docs_path=docs,
            embedding_fn=registry.embedding_fn,
            quality_checker=ctx.quality_checker,
        )
        report = bootstrap.analyze()
        _bootstrap_cache[ctx.name] = bootstrap
        return report

    @app.get("/api/bootstrap/report")
    async def bootstrap_report(
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        ctx = _resolve(project)
        bootstrap = _bootstrap_cache.get(ctx.name)
        if bootstrap and bootstrap.last_report:
            return bootstrap.last_report
        return {"summary": {"total_files": 0}, "file_inventory": [],
                "duplicate_clusters": [], "proposed_actions": [],
                "needs_ai_rewrite": []}

    @app.post("/api/bootstrap/execute")
    async def bootstrap_execute(
        req: BootstrapExecuteRequest,
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        ctx = _resolve(project)
        bootstrap = _bootstrap_cache.get(ctx.name)
        if not bootstrap or not bootstrap.last_report:
            raise HTTPException(400, "No analysis report. Run analyze first.")
        result = bootstrap.execute(req.actions)
        if result.get("executed", 0) > 0:
            with ctx.index_lock:
                ctx.indexer.index_all(quality_checker=ctx.quality_checker)
            try:
                ctx.watcher.push_pending()
            except Exception:
                pass
        return result

    # ── GitHub Webhook (HMAC auth) ────────────────────

    @app.get("/api/search/by-file")
    async def search_by_file(
        filename: str = Query(..., description="File path or name, e.g. payment.service.ts"),
        top_k: int = Query(4, ge=1, le=10),
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        """Return Flaiwheel knowledge relevant to a specific source file.

        Used by IDE extensions (VS Code, Cursor), Claude Code hooks, and any tool
        that wants to pre-load context for a file without a manual search query.
        Trusted from localhost without credentials.

        Returns a lightweight JSON payload optimised for IDE consumption.
        """
        ctx = _resolve(project)

        # Derive search query from filename (mirrors get_file_context MCP tool logic)
        from pathlib import Path as _Path
        p = _Path(filename)
        _skip = {"src", "lib", "app", "components", "utils", "helpers", "common", "shared", ".", ""}
        stem = re.sub(r"\.", " ", p.stem)
        parent = p.parent.name if p.parent.name not in _skip else ""
        query = f"{stem} {parent}".strip()

        results = ctx.indexer.search(query=query, top_k=top_k)

        return {
            "filename": filename,
            "query": query,
            "project": ctx.name,
            "count": len(results),
            "results": [
                {
                    "title": r.get("heading") or r["source"],
                    "source": r["source"],
                    "type": r.get("type", "—"),
                    "relevance": r.get("relevance", 0),
                    "summary": r.get("text", "")[:300],
                }
                for r in results
            ],
        }

    @app.post("/api/capture-commit")
    async def capture_commit(
        req: CaptureCommitRequest,
        project: Optional[str] = Query(None),
        _user: str = Depends(require_auth),
    ):
        """Capture a git commit as a structured knowledge doc.

        Called automatically by the Flaiwheel post-commit git hook.
        Generates a markdown file from the commit data, indexes it, and pushes it
        to the knowledge repo — no agent or MCP session required.

        Supported commit types (Conventional Commits):
          fix      → bugfix-log/
          feat     → changelog/
          refactor → best-practices/
          docs     → architecture/
          perf     → best-practices/
        """
        ctx = _resolve(project)
        today = date.today().isoformat()
        slug = re.sub(r"[^a-z0-9]+", "-", req.commit_message.lower()).strip("-")[:60]
        files_str = ", ".join(req.files_changed) if req.files_changed else "—"
        scope_str = f" ({req.commit_scope})" if req.commit_scope else ""
        short_hash = req.commit_hash[:8] if req.commit_hash else "unknown"

        commit_type = req.commit_type.lower()

        if commit_type == "fix":
            filename = f"bugfix-log/{today}-{slug}.md"
            content = (
                f"# {req.commit_message}\n\n"
                f"**Date:** {today}  \n"
                f"**Commit:** `{short_hash}`  \n"
                f"**Scope:** {req.commit_scope or '—'}  \n"
                f"**Affected files:** {files_str}\n\n"
                f"## Root Cause\n"
                f"*Auto-captured from git commit — enrich with root cause details.*\n\n"
                f"## Solution\n"
                f"{req.diff_summary or f'See commit `{short_hash}` for full diff.'}\n\n"
                f"## Lesson Learned\n"
                f"*Review and enrich this entry with lessons learned and prevention tips.*\n"
            )
        elif commit_type == "feat":
            filename = f"changelog/{today}-{slug}.md"
            content = (
                f"# {req.commit_message}\n\n"
                f"**Date:** {today}  \n"
                f"**Commit:** `{short_hash}`  \n"
                f"**Scope:** {req.commit_scope or '—'}  \n"
                f"**Changed files:** {files_str}\n\n"
                f"## Summary\n"
                f"*Auto-captured from git commit — enrich with feature description.*\n\n"
                f"## Changes\n"
                f"{req.diff_summary or f'See commit `{short_hash}` for full diff.'}\n\n"
                f"## Impact\n"
                f"*Describe user-facing or API-level impact.*\n"
            )
        elif commit_type in ("refactor", "perf"):
            filename = f"best-practices/{today}-{slug}.md"
            content = (
                f"# {req.commit_message}\n\n"
                f"**Date:** {today}  \n"
                f"**Commit:** `{short_hash}`  \n"
                f"**Type:** {commit_type}{scope_str}  \n"
                f"**Affected files:** {files_str}\n\n"
                f"## What Changed\n"
                f"{req.diff_summary or f'See commit `{short_hash}` for full diff.'}\n\n"
                f"## Pattern / Rationale\n"
                f"*Describe the pattern established and why it improves the codebase.*\n\n"
                f"## When to Apply\n"
                f"*Describe when this pattern should be reused.*\n"
            )
        elif commit_type == "docs":
            filename = f"architecture/{today}-{slug}.md"
            content = (
                f"# {req.commit_message}\n\n"
                f"**Date:** {today}  \n"
                f"**Commit:** `{short_hash}`  \n"
                f"**Changed files:** {files_str}\n\n"
                f"## Overview\n"
                f"{req.diff_summary or f'See commit `{short_hash}` for full diff.'}\n\n"
                f"## Decisions\n"
                f"*Enrich with architectural decisions documented in this change.*\n"
            )
        else:
            return {"status": "skipped", "reason": f"commit type '{commit_type}' not captured"}

        filepath = Path(ctx.merged_config.docs_path) / filename
        safe_base = Path(ctx.merged_config.docs_path).resolve()
        if not filepath.resolve().is_relative_to(safe_base):
            raise HTTPException(status_code=400, detail="Path traversal detected")

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        chunk_count = ctx.indexer.index_single(filename, content)
        ctx.watcher.push_pending()

        return {
            "status": "captured",
            "filename": filename,
            "chunks": chunk_count,
            "commit": short_hash,
            "type": commit_type,
        }

    @app.post("/webhook/github")
    async def github_webhook(request: Request):
        body = await request.body()

        matched_ctx: ProjectContext | None = None
        for ctx in registry.all():
            secret = ctx.merged_config.webhook_secret
            if secret:
                sig_header = request.headers.get("x-hub-signature-256", "")
                expected = "sha256=" + hmac.new(
                    secret.encode(), body, hashlib.sha256,
                ).hexdigest()
                if hmac.compare_digest(sig_header, expected):
                    matched_ctx = ctx
                    break

        if matched_ctx is None:
            default = registry.get_default()
            if default and not default.merged_config.webhook_secret:
                matched_ctx = default

        if matched_ctx is None:
            raise HTTPException(status_code=403, detail="Invalid signature or no matching project")

        event = request.headers.get("x-github-event", "")
        if event == "ping":
            return {"status": "pong"}

        if event != "push":
            return {"status": "ignored", "event": event}

        changed = matched_ctx.watcher.pull_and_check()
        result = None
        if changed:
            with matched_ctx.index_lock:
                result = matched_ctx.indexer.index_all(quality_checker=matched_ctx.quality_checker)

        return {
            "status": "ok",
            "project": matched_ctx.name,
            "changes_detected": changed,
            "reindex_result": result,
        }

    return app
