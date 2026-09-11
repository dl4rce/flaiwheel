# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.

"""
Central configuration – configurable via:
1. Environment variables (MCP_ prefix)
2. .env file
3. Web-UI (writes to /data/config.json)
"""
import json
from pathlib import Path
from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, NoDecode
from typing import Annotated, Any, Literal

from .logutil import diag

CONFIG_FILE = Path("/data/config.json")


def _split_list(value: Any) -> list[str]:
    """Normalise a list-ish setting from any source into ``list[str]``.

    Accepts (in order of preference) a real list, a JSON array, or a
    comma-separated string. The comma form is what people actually type
    into ``docker run -e`` / compose ``environment:``, and without it
    pydantic-settings raises ``SettingsError`` at startup for a perfectly
    natural value — a confusing failure for a deployment knob.

    ``MCP_SSE_ALLOWED_HOSTS=flaiwheel.example.com,flaiwheel.lan``
    ``MCP_SSE_ALLOWED_HOSTS=["flaiwheel.example.com"]``
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
    return [part.strip() for part in text.split(",") if part.strip()]


# ``NoDecode`` stops pydantic-settings from JSON-parsing the raw env value
# before our validator sees it, so both syntaxes above work.
StrList = Annotated[list[str], NoDecode, BeforeValidator(_split_list)]


class Config(BaseSettings):
    # ── Documentation ────────────────────────────
    docs_path: str = "/docs"
    docs_glob: str = "**/*.md"

    # ── Vector DB ────────────────────────────────
    vectorstore_path: str = "/data/vectorstore"

    # ── Embeddings ───────────────────────────────
    embedding_provider: Literal["local", "openai"] = "local"
    embedding_model: str = "all-MiniLM-L12-v2"
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"

    # ── Chunking ─────────────────────────────────
    chunk_strategy: Literal["heading", "fixed", "hybrid"] = "heading"
    chunk_max_chars: int = 2000
    chunk_overlap: int = 200

    # ── Git Sync ─────────────────────────────────
    git_repo_url: str = ""
    git_branch: str = "main"
    git_sync_interval: int = 300
    git_docs_subpath: str = ""
    git_token: str = ""
    git_auto_push: bool = True
    git_commit_prefix: str = "knowledge"
    webhook_secret: str = ""

    # ── Secret scanning (auto-commits are never human-reviewed) ──
    # block = refuse to commit on findings | warn = commit anyway, report | off
    gitleaks_mode: Literal["block", "warn", "off"] = "block"

    # ── Search ───────────────────────────────────
    hybrid_search: bool = True
    reranker_enabled: bool = True
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"
    rrf_k: int = 60
    rrf_vector_weight: float = 1.0
    rrf_bm25_weight: float = 1.0
    min_relevance: float = 0.0

    # ── Server / Transport ───────────────────────
    transport: Literal["stdio", "sse"] = "sse"
    sse_port: int = 8081
    web_port: int = 8080

    # ── MCP SSE transport security (remote / LAN deployments) ──
    # Bind address for the MCP SSE server. This is an ADDRESS, not a
    # hostname: 0.0.0.0 keeps the historical default (required so a
    # published Docker port is reachable); 127.0.0.1 for loopback-only.
    sse_host: str = "0.0.0.0"
    # Extra ``Host`` header values the transport-security guard accepts,
    # as comma-separated or JSON. Needed to serve remote/LAN clients
    # directly instead of behind a Host-rewriting reverse proxy.
    # See SECURITY.md — TLS is still required for non-localhost deployments.
    sse_allowed_hosts: StrList = []
    # Extra ``Origin`` header values. Only browser-based MCP clients send
    # an Origin; CLI/IDE clients do not, so the default is usually enough.
    sse_allowed_origins: StrList = []
    # DNS-rebinding protection stays ON by default. Disabling it removes
    # the Host AND Origin guard entirely — only do this when every client
    # already reaches Flaiwheel over a trusted, authenticated channel.
    sse_dns_rebinding_protection: bool = True
    # Native TLS for the MCP SSE endpoint. When BOTH are set the endpoint is
    # served over HTTPS directly, so a remote deployment needs no reverse
    # proxy at all. TLS is all-or-nothing: a partial or unreadable pair is a
    # startup error, never a fallback to plaintext — see _resolve_tls().
    sse_tls_certfile: str = ""
    sse_tls_keyfile: str = ""

    @property
    def sse_tls_configured(self) -> bool:
        """True when a complete certificate/key pair is set."""
        return bool(self.sse_tls_certfile.strip() and self.sse_tls_keyfile.strip())

    @property
    def sse_tls_partial(self) -> bool:
        """True when exactly one of cert/key is set — a misconfiguration."""
        return bool(self.sse_tls_certfile.strip()) != bool(self.sse_tls_keyfile.strip())

    # ── Auth ─────────────────────────────────────
    auth_username: str = "admin"
    auth_password_hash: str = ""

    class Config:
        env_prefix = "MCP_"
        env_file = ".env"

    @classmethod
    def load(cls) -> "Config":
        """Load config: ENV -> .env -> config.json (Web-UI overrides)."""
        config = cls()

        if CONFIG_FILE.exists():
            try:
                overrides = json.loads(CONFIG_FILE.read_text())
                for key, value in overrides.items():
                    if hasattr(config, key) and value != "":
                        setattr(config, key, value)
            except Exception as e:
                diag(f"Warning: Config file error: {e}")

        return config

    def save(self):
        """Persist current config for Web-UI."""
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(
                json.dumps(self.model_dump(), indent=2, default=str)
            )
        except OSError as e:
            diag(f"Warning: Cannot save config ({e}) — read-only filesystem?")


    def to_safe_dict(self) -> dict:
        """Config without secrets (for Web-UI display)."""
        d = self.model_dump()
        if d.get("openai_api_key"):
            d["openai_api_key"] = d["openai_api_key"][:8] + "..."
        if d.get("git_token"):
            d["git_token"] = "***set***"
        d.pop("auth_password_hash", None)
        return d


LOCAL_MODELS = [
    {
        "id": "all-MiniLM-L6-v2",
        "name": "MiniLM-L6 v2",
        "params": "22M",
        "dim": 384,
        "ram": "~90MB",
        "speed": "Fast",
        "quality": "78%",
        "lang": "EN",
        "desc": "Ideal for large repos, low RAM",
    },
    {
        "id": "all-MiniLM-L12-v2",
        "name": "MiniLM-L12 v2",
        "params": "33M",
        "dim": 384,
        "ram": "~130MB",
        "speed": "Fast",
        "quality": "80%",
        "lang": "EN",
        "desc": "Good speed/quality balance",
    },
    {
        "id": "all-mpnet-base-v2",
        "name": "MPNet Base v2",
        "params": "110M",
        "dim": 768,
        "ram": "~420MB",
        "speed": "Medium",
        "quality": "83%",
        "lang": "EN",
        "desc": "Sentence-Transformers standard",
    },
    {
        "id": "BAAI/bge-base-en-v1.5",
        "name": "BGE Base EN v1.5",
        "params": "110M",
        "dim": 768,
        "ram": "~420MB",
        "speed": "Medium",
        "quality": "85%",
        "lang": "EN",
        "desc": "Best value for English",
    },
    {
        "id": "nomic-ai/nomic-embed-text-v1.5",
        "name": "Nomic Embed v1.5",
        "params": "137M",
        "dim": 768,
        "ram": "~520MB",
        "speed": "Slower",
        "quality": "87%",
        "lang": "EN",
        "desc": "Best local quality (English)",
    },
    {
        "id": "intfloat/multilingual-e5-base",
        "name": "Multilingual E5 Base",
        "params": "278M",
        "dim": 768,
        "ram": "~1.1GB",
        "speed": "Slower",
        "quality": "82%",
        "lang": "DE/EN/Multi",
        "desc": "Good for mixed DE/EN docs",
    },
    {
        "id": "BAAI/bge-m3",
        "name": "BGE-M3",
        "params": "568M",
        "dim": 1024,
        "ram": "~2.2GB",
        "speed": "Slow",
        "quality": "86%",
        "lang": "DE/EN/Multi",
        "desc": "Best multilingual model",
    },
]

RERANKER_MODELS = [
    {
        "id": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "name": "MS MARCO MiniLM-L6",
        "params": "22M",
        "ram": "~90MB",
        "speed": "Fast",
        "quality": "Good",
        "desc": "Best speed/quality balance for reranking",
    },
    {
        "id": "cross-encoder/ms-marco-MiniLM-L-12-v2",
        "name": "MS MARCO MiniLM-L12",
        "params": "33M",
        "ram": "~130MB",
        "speed": "Medium",
        "quality": "Better",
        "desc": "Higher precision, still fast",
    },
    {
        "id": "BAAI/bge-reranker-base",
        "name": "BGE Reranker Base",
        "params": "110M",
        "ram": "~420MB",
        "speed": "Slower",
        "quality": "Best",
        "desc": "State-of-the-art reranking accuracy",
    },
]
