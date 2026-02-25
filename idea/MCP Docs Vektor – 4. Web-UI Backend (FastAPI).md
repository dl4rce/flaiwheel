# MCP Docs Vektor – Code Teil 4: Web-UI Backend

## `src/mcp_docs_vector/web.py`

```python
# src/mcp_docs_vector/web.py
"""
Web-UI Backend (FastAPI) – Konfiguration, Monitoring, Test-Suche.
Läuft parallel zum MCP-Server im selben Container.

Endpoints:
  GET  /              → Web-Frontend (HTML)
  GET  /api/config    → Aktuelle Konfiguration
  POST /api/config    → Konfiguration ändern
  GET  /api/stats     → Index-Statistiken
  POST /api/reindex   → Manueller Re-Index
  POST /api/search    → Test-Suche (zum Testen im Browser)
  GET  /api/models    → Verfügbare Embedding-Modelle
  POST /api/clear     → Index löschen
"""
import asyncio
import threading
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from .config import Config, LOCAL_MODELS
from .indexer import DocsIndexer
from .watcher import GitWatcher


# ── Shared State ──────────────────────────────────────
config: Config = None
indexer: DocsIndexer = None
watcher: GitWatcher = None
_index_lock = threading.Lock()


class ConfigUpdate(BaseModel):
    """Request-Body für Config-Updates aus dem Web-UI."""
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
    transport: Optional[str] = None
    sse_port: Optional[int] = None
    web_port: Optional[int] = None


class SearchRequest(BaseModel):
    """Request-Body für Test-Suche."""
    query: str
    top_k: int = 5
    type_filter: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/Shutdown."""
    global config, indexer, watcher
    
    # Config laden
    config = Config.load()
    
    # Indexer initialisieren
    indexer = DocsIndexer(config)
    
    # Git Watcher starten
    watcher = GitWatcher(config, indexer)
    watcher.start()
    
    # Initial Index
    print(f"🔍 Initial indexing {config.docs_path} ...")
    result = indexer.index_all()
    print(f"✅ {result}")
    
    yield
    
    # Shutdown
    if watcher:
        watcher.stop()


app = FastAPI(
    title="MCP Docs Vector",
    description="Self-contained Vektor-Suche für Projektdokumentation",
    lifespan=lifespan
)


# ── Web Frontend ──────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def web_frontend():
    """Serviert das Web-Frontend."""
    template_path = Path(__file__).parent / "templates" / "index.html"
    if template_path.exists():
        return HTMLResponse(template_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Template nicht gefunden</h1>", status_code=500)


# ── API Endpoints ─────────────────────────────────────

@app.get("/api/config")
async def get_config():
    """Aktuelle Konfiguration (ohne Secrets)."""
    return {
        "config": config.to_safe_dict(),
        "available_models": LOCAL_MODELS
    }


@app.post("/api/config")
async def update_config(update: ConfigUpdate):
    """Konfiguration ändern. Bei Embedding-Modell-Wechsel wird der Index neu gebaut."""
    global config, indexer
    
    old_model = config.embedding_model
    old_provider = config.embedding_provider
    
    # Nur gesetzte Felder übernehmen
    update_dict = update.model_dump(exclude_none=True)
    for key, value in update_dict.items():
        if hasattr(config, key):
            setattr(config, key, value)
    
    # Persistieren
    config.save()
    
    # Wenn Embedding-Modell geändert → Index komplett neu bauen
    model_changed = (
        old_model != config.embedding_model or
        old_provider != config.embedding_provider
    )
    
    if model_changed:
        indexer.reinit(config)
        result = indexer.index_all()
        return {
            "status": "success",
            "message": "Config gespeichert + Index mit neuem Modell neu gebaut",
            "reindex_result": result,
            "model_changed": True
        }
    
    return {
        "status": "success",
        "message": "Config gespeichert",
        "model_changed": False
    }


@app.get("/api/stats")
async def get_stats():
    """Index-Statistiken."""
    return indexer.stats


@app.post("/api/reindex")
async def trigger_reindex():
    """Manueller Re-Index."""
    with _index_lock:
        result = indexer.index_all()
    return result


@app.post("/api/clear")
async def clear_index():
    """Index komplett löschen."""
    indexer.clear_index()
    return {"status": "success", "message": "Index gelöscht"}


@app.post("/api/search")
async def test_search(req: SearchRequest):
    """Test-Suche (für Web-UI)."""
    results = indexer.search(
        query=req.query,
        top_k=req.top_k,
        type_filter=req.type_filter
    )
    return {
        "query": req.query,
        "count": len(results),
        "results": results
    }


@app.get("/api/models")
async def get_models():
    """Verfügbare Embedding-Modelle."""
    return {
        "local_models": LOCAL_MODELS,
        "current": {
            "provider": config.embedding_provider,
            "model": config.embedding_model if config.embedding_provider == "local"
                     else config.openai_embedding_model
        }
    }


@app.post("/api/git/pull")
async def trigger_git_pull():
    """Manueller Git Pull + Reindex."""
    if not watcher or not config.git_repo_url:
        return {"status": "error", "message": "Kein Git-Repo konfiguriert"}
    
    changed = watcher.pull_and_check()
    result = None
    if changed:
        result = indexer.index_all()
    
    return {
        "status": "success",
        "changes_detected": changed,
        "reindex_result": result
    }


def run_web():
    """Startet den Web-Server."""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.web_port if config else 8080)
```
