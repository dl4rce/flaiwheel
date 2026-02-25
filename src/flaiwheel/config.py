# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# Non-commercial use only. Commercial licensing: info@4rce.com

"""
Central configuration – configurable via:
1. Environment variables (MCP_ prefix)
2. .env file
3. Web-UI (writes to /data/config.json)
"""
import json
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Literal

CONFIG_FILE = Path("/data/config.json")


class Config(BaseSettings):
    # ── Documentation ────────────────────────────
    docs_path: str = "/docs"
    docs_glob: str = "**/*.md"

    # ── Vector DB ────────────────────────────────
    vectorstore_path: str = "/data/vectorstore"

    # ── Embeddings ───────────────────────────────
    embedding_provider: Literal["local", "openai"] = "local"
    embedding_model: str = "all-MiniLM-L6-v2"
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

    # ── Server / Transport ───────────────────────
    transport: Literal["stdio", "sse"] = "sse"
    sse_port: int = 8081
    web_port: int = 8080

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
                print(f"Warning: Config file error: {e}")

        return config

    def save(self):
        """Persist current config for Web-UI."""
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(self.model_dump(), indent=2, default=str)
        )

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
