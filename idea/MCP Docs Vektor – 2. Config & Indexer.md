# MCP Docs Vektor – Code Teil 2: Config & Indexer

## `src/mcp_docs_vector/config.py`

```python
# src/mcp_docs_vector/config.py
"""
Zentrale Konfiguration – steuerbar über:
1. Environment-Variablen (MCP_ prefix)
2. .env Datei
3. Web-UI (schreibt in /data/config.json)
"""
import json
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Literal

CONFIG_FILE = "/data/config.json"

class Config(BaseSettings):
    # ── Dokumentation ─────────────────────────────
    docs_path: str = "/docs"
    docs_glob: str = "**/*.md"
    
    # ── Vektor-DB ─────────────────────────────────
    vectorstore_path: str = "/data/vectorstore"
    
    # ── Embeddings ────────────────────────────────
    embedding_provider: Literal["local", "openai"] = "local"
    # Lokale Modelle (sentence-transformers)
    embedding_model: str = "all-MiniLM-L6-v2"
    # OpenAI (nur wenn provider=openai)
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    
    # ── Chunking ──────────────────────────────────
    chunk_strategy: Literal["heading", "fixed", "hybrid"] = "heading"
    chunk_max_chars: int = 2000  # Max Zeichen pro Chunk
    chunk_overlap: int = 200     # Überlappung bei fixed/hybrid
    
    # ── Git Sync ──────────────────────────────────
    git_repo_url: str = ""               # leer = kein auto-clone
    git_branch: str = "main"
    git_sync_interval: int = 300         # Sekunden, 0 = aus
    git_docs_subpath: str = ""           # Unterordner im Repo (leer = root)
    git_token: str = ""                  # für private Repos
    
    # ── Server / Transport ────────────────────────
    transport: Literal["stdio", "sse"] = "sse"
    sse_port: int = 8081
    web_port: int = 8080
    
    class Config:
        env_prefix = "MCP_"
        env_file = ".env"

    @classmethod
    def load(cls) -> "Config":
        """Lädt Config: ENV → .env → config.json (Web-UI Overrides)"""
        config = cls()
        
        # Web-UI Overrides laden falls vorhanden
        config_path = Path(CONFIG_FILE)
        if config_path.exists():
            try:
                overrides = json.loads(config_path.read_text())
                for key, value in overrides.items():
                    if hasattr(config, key) and value != "":
                        setattr(config, key, value)
            except Exception as e:
                print(f"⚠️ Config file error: {e}")
        
        return config
    
    def save(self):
        """Speichert aktuelle Config für Web-UI Persistenz"""
        config_path = Path(CONFIG_FILE)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(self.model_dump(), indent=2, default=str)
        )
    
    def to_safe_dict(self) -> dict:
        """Config ohne Secrets (für Web-UI Anzeige)"""
        d = self.model_dump()
        if d.get("openai_api_key"):
            d["openai_api_key"] = d["openai_api_key"][:8] + "..."
        if d.get("git_token"):
            d["git_token"] = "***set***"
        return d


# ── Verfügbare lokale Modelle (für Web-UI Dropdown) ──────
LOCAL_MODELS = [
    {
        "id": "all-MiniLM-L6-v2",
        "name": "MiniLM-L6 v2",
        "params": "22M",
        "dim": 384,
        "ram": "~90MB",
        "speed": "⚡⚡⚡ Schnellstes",
        "quality": "★★★☆☆ (78%)",
        "lang": "EN",
        "desc": "Ideal für große Repos, wenig RAM"
    },
    {
        "id": "all-MiniLM-L12-v2",
        "name": "MiniLM-L12 v2",
        "params": "33M",
        "dim": 384,
        "ram": "~130MB",
        "speed": "⚡⚡⚡ Sehr schnell",
        "quality": "★★★☆☆ (80%)",
        "lang": "EN",
        "desc": "Guter Kompromiss Speed/Qualität"
    },
    {
        "id": "all-mpnet-base-v2",
        "name": "MPNet Base v2",
        "params": "110M",
        "dim": 768,
        "ram": "~420MB",
        "speed": "⚡⚡ Mittel",
        "quality": "★★★★☆ (83%)",
        "lang": "EN",
        "desc": "Sentence-Transformers Standard"
    },
    {
        "id": "BAAI/bge-base-en-v1.5",
        "name": "BGE Base EN v1.5",
        "params": "110M",
        "dim": 768,
        "ram": "~420MB",
        "speed": "⚡⚡ Mittel",
        "quality": "★★★★☆ (85%)",
        "lang": "EN",
        "desc": "Bestes Preis-Leistung für Englisch"
    },
    {
        "id": "nomic-ai/nomic-embed-text-v1.5",
        "name": "Nomic Embed v1.5 🏆",
        "params": "137M",
        "dim": 768,
        "ram": "~520MB",
        "speed": "⚡ Etwas langsamer",
        "quality": "★★★★★ (87%)",
        "lang": "EN",
        "desc": "Beste Qualität lokal (Englisch)"
    },
    {
        "id": "intfloat/multilingual-e5-base",
        "name": "Multilingual E5 Base 🌍",
        "params": "278M",
        "dim": 768,
        "ram": "~1.1GB",
        "speed": "⚡ Mittel-Langsam",
        "quality": "★★★★☆ (82%)",
        "lang": "DE/EN/Multi",
        "desc": "Gut für gemischte DE/EN Doku"
    },
    {
        "id": "BAAI/bge-m3",
        "name": "BGE-M3 🌍",
        "params": "568M",
        "dim": 1024,
        "ram": "~2.2GB",
        "speed": "⚡ Langsamer",
        "quality": "★★★★★ (86%)",
        "lang": "DE/EN/Multi",
        "desc": "Bestes multilingual Modell"
    },
]
```

---

## `src/mcp_docs_vector/indexer.py`

```python
# src/mcp_docs_vector/indexer.py
"""
Markdown-Dokumentation → Chunks → Vektor-Embeddings → ChromaDB

Unterstützt drei Chunking-Strategien:
- "heading": Split an ## Headings (default, best für strukturierte Docs)
- "fixed":   Feste Chunk-Größe mit Overlap
- "hybrid":  Heading-Split + Unterteilen wenn Chunk zu groß
"""
import hashlib
import re
from pathlib import Path
from typing import Optional
import chromadb
from chromadb.utils import embedding_functions
from .config import Config

class DocsIndexer:
    def __init__(self, config: Config):
        self.config = config
        self._init_vectorstore()
    
    def _init_vectorstore(self):
        """Initialisiert ChromaDB + Embedding-Funktion."""
        self.chroma = chromadb.PersistentClient(path=self.config.vectorstore_path)
        
        if self.config.embedding_provider == "local":
            self.ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=self.config.embedding_model
            )
        else:
            self.ef = embedding_functions.OpenAIEmbeddingFunction(
                api_key=self.config.openai_api_key,
                model_name=self.config.openai_embedding_model
            )
        
        self.collection = self.chroma.get_or_create_collection(
            "project_docs",
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"}  # Cosine-Similarity
        )
    
    def reinit(self, config: Config):
        """Re-initialisiert mit neuer Config (z.B. nach Modell-Wechsel in Web-UI)."""
        self.config = config
        # Collection löschen und neu erstellen bei Modell-Wechsel
        try:
            self.chroma.delete_collection("project_docs")
        except Exception:
            pass
        self._init_vectorstore()
    
    # ── Chunking ──────────────────────────────────────────
    
    def chunk_markdown(self, text: str, source: str) -> list[dict]:
        """Wählt Chunking-Strategie basierend auf Config."""
        strategy = self.config.chunk_strategy
        
        if strategy == "heading":
            return self._chunk_by_heading(text, source)
        elif strategy == "fixed":
            return self._chunk_fixed_size(text, source)
        elif strategy == "hybrid":
            return self._chunk_hybrid(text, source)
        return self._chunk_by_heading(text, source)
    
    def _chunk_by_heading(self, text: str, source: str) -> list[dict]:
        """Split an ## und ### Headings."""
        chunks = []
        current_heading = "intro"
        current_lines = []
        
        for line in text.split("\n"):
            if re.match(r'^#{1,3}\s+', line):
                if current_lines:
                    chunks.append(self._make_chunk(
                        "\n".join(current_lines), current_heading, source, len(chunks)
                    ))
                current_heading = line.lstrip("# ").strip()
                current_lines = [line]
            else:
                current_lines.append(line)
        
        if current_lines:
            chunks.append(self._make_chunk(
                "\n".join(current_lines), current_heading, source, len(chunks)
            ))
        
        return [c for c in chunks if len(c["text"].strip()) > 50]  # Leere Chunks filtern
    
    def _chunk_fixed_size(self, text: str, source: str) -> list[dict]:
        """Feste Chunk-Größe mit Überlappung."""
        max_chars = self.config.chunk_max_chars
        overlap = self.config.chunk_overlap
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + max_chars
            chunk_text = text[start:end]
            
            # Am Satzende schneiden wenn möglich
            if end < len(text):
                last_period = chunk_text.rfind(". ")
                if last_period > max_chars * 0.5:
                    chunk_text = chunk_text[:last_period + 1]
                    end = start + last_period + 1
            
            chunks.append(self._make_chunk(
                chunk_text, f"chunk-{len(chunks)}", source, len(chunks)
            ))
            start = end - overlap
        
        return chunks
    
    def _chunk_hybrid(self, text: str, source: str) -> list[dict]:
        """Heading-Split, dann zu große Chunks nochmal unterteilen."""
        heading_chunks = self._chunk_by_heading(text, source)
        final_chunks = []
        
        for chunk in heading_chunks:
            if len(chunk["text"]) > self.config.chunk_max_chars:
                # Zu groß → nochmal splitten
                sub_chunks = self._chunk_fixed_size(chunk["text"], source)
                for i, sc in enumerate(sub_chunks):
                    sc["metadata"]["heading"] = f"{chunk['metadata']['heading']} (Teil {i+1})"
                    sc["id"] = hashlib.md5(
                        f"{source}:{chunk['metadata']['heading']}:{i}".encode()
                    ).hexdigest()
                final_chunks.extend(sub_chunks)
            else:
                final_chunks.append(chunk)
        
        return final_chunks
    
    def _make_chunk(self, text: str, heading: str, source: str, index: int) -> dict:
        """Erstellt ein Chunk-Dict."""
        text = text.strip()
        return {
            "id": hashlib.md5(f"{source}:{heading}:{index}".encode()).hexdigest(),
            "text": text,
            "metadata": {
                "source": source,
                "heading": heading,
                "type": self._detect_type(source),
                "char_count": len(text),
                "word_count": len(text.split())
            }
        }
    
    def _detect_type(self, path: str) -> str:
        """Erkennt Dokumenttyp anhand des Pfades."""
        path_lower = path.lower()
        if "bugfix" in path_lower or "bug-fix" in path_lower: return "bugfix"
        if "best-practice" in path_lower or "bestpractice" in path_lower: return "best-practice"
        if "api" in path_lower: return "api"
        if "architect" in path_lower: return "architecture"
        if "changelog" in path_lower or "release" in path_lower: return "changelog"
        if "setup" in path_lower or "install" in path_lower: return "setup"
        if "readme" in path_lower: return "readme"
        return "docs"
    
    # ── Indexing ──────────────────────────────────────────
    
    def index_all(self) -> dict:
        """Vollständiger (Re-)Index aller .md Dateien."""
        docs_path = Path(self.config.docs_path)
        
        if not docs_path.exists():
            return {"status": "error", "message": f"Pfad existiert nicht: {docs_path}"}
        
        all_chunks = []
        file_count = 0
        
        for md_file in sorted(docs_path.rglob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                rel_path = str(md_file.relative_to(docs_path))
                chunks = self.chunk_markdown(content, rel_path)
                all_chunks.extend(chunks)
                file_count += 1
            except Exception as e:
                print(f"⚠️ Fehler bei {md_file}: {e}")
        
        if all_chunks:
            # Batch upsert (ChromaDB max 41666 pro Batch)
            batch_size = 5000
            for i in range(0, len(all_chunks), batch_size):
                batch = all_chunks[i:i + batch_size]
                self.collection.upsert(
                    ids=[c["id"] for c in batch],
                    documents=[c["text"] for c in batch],
                    metadatas=[c["metadata"] for c in batch]
                )
        
        result = {
            "status": "success",
            "files_indexed": file_count,
            "chunks_created": len(all_chunks),
            "docs_path": str(docs_path)
        }
        print(f"✅ Index: {file_count} Files → {len(all_chunks)} Chunks")
        return result
    
    def index_single(self, filepath: str, content: str) -> int:
        """Einzelne Datei (re-)indizieren."""
        chunks = self.chunk_markdown(content, filepath)
        if chunks:
            self.collection.upsert(
                ids=[c["id"] for c in chunks],
                documents=[c["text"] for c in chunks],
                metadatas=[c["metadata"] for c in chunks]
            )
        return len(chunks)
    
    def clear_index(self):
        """Löscht den gesamten Index."""
        try:
            self.chroma.delete_collection("project_docs")
        except Exception:
            pass
        self.collection = self.chroma.get_or_create_collection(
            "project_docs",
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"}
        )
    
    # ── Suche ─────────────────────────────────────────────
    
    def search(self, query: str, top_k: int = 5, type_filter: str = None) -> list[dict]:
        """Semantische Suche in der Dokumentation."""
        if self.collection.count() == 0:
            return []
        
        kwargs = {
            "query_texts": [query],
            "n_results": min(top_k, self.collection.count())
        }
        if type_filter:
            kwargs["where"] = {"type": type_filter}
        
        try:
            results = self.collection.query(**kwargs)
        except Exception as e:
            print(f"⚠️ Suchfehler: {e}")
            return []
        
        if not results["documents"] or not results["documents"][0]:
            return []
        
        return [
            {
                "text": doc,
                "source": meta["source"],
                "heading": meta["heading"],
                "type": meta["type"],
                "char_count": meta.get("char_count", 0),
                "distance": dist,
                "relevance": round((1 - dist) * 100, 1)
            }
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0]
            )
        ]
    
    # ── Stats ─────────────────────────────────────────────
    
    @property
    def stats(self) -> dict:
        """Index-Statistiken für Web-UI."""
        count = self.collection.count()
        
        # Typ-Verteilung ermitteln
        type_counts = {}
        if count > 0:
            try:
                all_meta = self.collection.get(limit=count, include=["metadatas"])
                for meta in all_meta["metadatas"]:
                    t = meta.get("type", "unknown")
                    type_counts[t] = type_counts.get(t, 0) + 1
            except Exception:
                pass
        
        return {
            "total_chunks": count,
            "type_distribution": type_counts,
            "docs_path": self.config.docs_path,
            "embedding_provider": self.config.embedding_provider,
            "embedding_model": self.config.embedding_model if self.config.embedding_provider == "local" else self.config.openai_embedding_model,
            "chunk_strategy": self.config.chunk_strategy
        }
```
