# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# Non-commercial use only. Commercial licensing: info@4rce.com

"""
Web-UI Backend (FastAPI) – configuration, monitoring, test search.
Runs in a background thread alongside the MCP server.

All state (config, indexer, watcher, auth) is injected via create_web_app().
"""
import hashlib
import hmac
import secrets
import threading
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from .auth import AuthManager
from .config import LOCAL_MODELS, Config
from .health import HealthTracker
from .indexer import DocsIndexer
from .quality import KnowledgeQualityChecker
from .watcher import GitWatcher


class ConfigUpdate(BaseModel):
    docs_path: Optional[str] = None
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_embedding_model: Optional[str] = None
    chunk_strategy: Optional[str] = None
    chunk_max_chars: Optional[int] = None
    chunk_overlap: Optional[int] = None
    git_repo_url: Optional[str] = None
    git_branch: Optional[str] = None
    git_sync_interval: Optional[int] = None
    git_docs_subpath: Optional[str] = None
    git_token: Optional[str] = None
    git_auto_push: Optional[bool] = None
    transport: Optional[str] = None
    sse_port: Optional[int] = None
    web_port: Optional[int] = None


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    type_filter: Optional[str] = None


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


def create_web_app(
    config: Config,
    indexer: DocsIndexer,
    watcher: GitWatcher,
    index_lock: threading.Lock,
    config_lock: threading.Lock,
    auth: AuthManager,
    quality_checker: KnowledgeQualityChecker,
    health: HealthTracker | None = None,
) -> FastAPI:
    """Factory: returns a FastAPI app that shares state with the MCP server."""

    app = FastAPI(
        title="Flaiwheel",
        description="Self-improving knowledge base for AI coding agents",
    )
    security = HTTPBasic()

    def require_auth(credentials: HTTPBasicCredentials = Depends(security)):
        if not auth.verify(credentials.username, credentials.password):
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": 'Basic realm="Flaiwheel"'},
            )
        return credentials.username

    # ── Health (no auth — used by Docker healthcheck) ──

    @app.get("/health")
    async def health_check():
        from . import __version__
        status = health.status if health else {}
        return {
            "status": "ok" if (not health or health.is_healthy) else "degraded",
            "version": __version__,
            "chunks": indexer.collection.count(),
            "last_index_at": status.get("last_index_at"),
            "last_index_ok": status.get("last_index_ok"),
            "last_pull_at": status.get("last_pull_at"),
            "last_pull_ok": status.get("last_pull_ok"),
            "git_commit": status.get("git_commit"),
            "git_branch": status.get("git_branch"),
        }

    @app.get("/api/health")
    async def health_detail(_user: str = Depends(require_auth)):
        return health.status if health else {}

    # ── Web Frontend ─────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def web_frontend(_user: str = Depends(require_auth)):
        template_path = Path(__file__).parent / "templates" / "index.html"
        if template_path.exists():
            return HTMLResponse(template_path.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>Template not found</h1>", status_code=500)

    # ── API Endpoints ────────────────────────────────

    @app.get("/api/config")
    async def get_config(_user: str = Depends(require_auth)):
        return {"config": config.to_safe_dict(), "available_models": LOCAL_MODELS}

    @app.post("/api/config")
    async def update_config(
        update: ConfigUpdate, _user: str = Depends(require_auth),
    ):
        with config_lock:
            old_model = config.embedding_model
            old_provider = config.embedding_provider

            update_dict = update.model_dump(exclude_none=True)
            for key, value in update_dict.items():
                if hasattr(config, key):
                    setattr(config, key, value)

            config.save()

            model_changed = (
                old_model != config.embedding_model
                or old_provider != config.embedding_provider
            )

        if model_changed:
            with index_lock:
                indexer.reinit(config)
                result = indexer.index_all()
            return {
                "status": "success",
                "message": "Config saved + index rebuilt with new model",
                "reindex_result": result,
                "model_changed": True,
            }

        return {"status": "success", "message": "Config saved", "model_changed": False}

    @app.get("/api/stats")
    async def get_stats(_user: str = Depends(require_auth)):
        return indexer.stats

    @app.post("/api/reindex")
    async def trigger_reindex(_user: str = Depends(require_auth)):
        with index_lock:
            result = indexer.index_all()
        if health:
            health.record_index(
                ok=result.get("status") == "success",
                chunks=result.get("chunks_upserted", 0),
                files=result.get("files_indexed", 0),
            )
        return result

    @app.post("/api/clear")
    async def clear_index(_user: str = Depends(require_auth)):
        with index_lock:
            indexer.clear_index()
        return {"status": "success", "message": "Index cleared"}

    @app.post("/api/search")
    async def test_search(
        req: SearchRequest, _user: str = Depends(require_auth),
    ):
        results = indexer.search(
            query=req.query, top_k=req.top_k, type_filter=req.type_filter,
        )
        return {"query": req.query, "count": len(results), "results": results}

    @app.get("/api/models")
    async def get_models(_user: str = Depends(require_auth)):
        return {
            "local_models": LOCAL_MODELS,
            "current": {
                "provider": config.embedding_provider,
                "model": (
                    config.embedding_model
                    if config.embedding_provider == "local"
                    else config.openai_embedding_model
                ),
            },
        }

    @app.post("/api/git/pull")
    async def trigger_git_pull(_user: str = Depends(require_auth)):
        if not watcher or not config.git_repo_url:
            return {"status": "error", "message": "No git repo configured"}

        changed = watcher.pull_and_check()
        result = None
        if changed:
            with index_lock:
                result = indexer.index_all()

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
    async def get_quality(_user: str = Depends(require_auth)):
        return quality_checker.check_all()

    # ── GitHub Webhook (no auth — uses HMAC signature) ──

    @app.post("/webhook/github")
    async def github_webhook(request: Request):
        body = await request.body()

        if config.webhook_secret:
            sig_header = request.headers.get("x-hub-signature-256", "")
            expected = "sha256=" + hmac.new(
                config.webhook_secret.encode(), body, hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(sig_header, expected):
                raise HTTPException(status_code=403, detail="Invalid signature")

        event = request.headers.get("x-github-event", "")
        if event == "ping":
            return {"status": "pong"}

        if event != "push":
            return {"status": "ignored", "event": event}

        changed = watcher.pull_and_check()
        result = None
        if changed:
            with index_lock:
                result = indexer.index_all()

        return {
            "status": "ok",
            "changes_detected": changed,
            "reindex_result": result,
        }

    return app
