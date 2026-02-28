# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.md.

"""
Documents -> Markdown text -> Chunks -> Vector Embeddings -> ChromaDB

Supports: .md, .txt, .pdf, .html, .rst, .docx, .json, .yaml, .csv
All non-markdown formats are converted to markdown-like text in memory.

Chunking strategies:
- "heading": Split at ## headings (default, best for structured docs)
- "fixed":   Fixed chunk size with overlap
- "hybrid":  Heading split + subdivide if chunk too large

Chunk IDs are content-based (sha256 of source + text) so they are
stable across reindexing regardless of section ordering.
"""
import hashlib
import json
import re
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import bm25s
import chromadb
from chromadb.utils import embedding_functions
from .config import Config
from .readers import extract_text, SUPPORTED_EXTENSIONS

_reranker_cache: dict[str, object] = {}
_reranker_lock = threading.Lock()


def _get_reranker(model_name: str):
    """Lazy-load and cache a cross-encoder reranker model."""
    with _reranker_lock:
        if model_name in _reranker_cache:
            return _reranker_cache[model_name]
    try:
        from sentence_transformers import CrossEncoder
        model = CrossEncoder(model_name)
        with _reranker_lock:
            _reranker_cache[model_name] = model
        return model
    except Exception as e:
        print(f"Warning: Failed to load reranker model '{model_name}': {e}")
        return None

DEFAULT_COLLECTION = "project_docs"


def _iter_docs(docs_path: Path):
    """Yield all supported document files under docs_path, deduplicated.
    Skips subdirectories that contain their own .git (other project repos)."""
    nested_repos: set[Path] = set()
    for child in docs_path.iterdir():
        if child.is_dir() and (child / ".git").exists():
            nested_repos.add(child)

    seen: set[Path] = set()
    for ext in sorted(SUPPORTED_EXTENSIONS):
        for p in docs_path.rglob(f"*{ext}"):
            if any(p.is_relative_to(nr) for nr in nested_repos):
                continue
            if p not in seen:
                seen.add(p)
                yield p


@dataclass
class ModelMigration:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "running"
    old_model: str = ""
    new_model: str = ""
    total_files: int = 0
    files_done: int = 0
    chunks_created: int = 0
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: Optional[str] = None
    error: Optional[str] = None
    thread: Optional[threading.Thread] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "old_model": self.old_model,
            "new_model": self.new_model,
            "total_files": self.total_files,
            "files_done": self.files_done,
            "chunks_created": self.chunks_created,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "percent": round(self.files_done / self.total_files * 100) if self.total_files > 0 else 0,
        }

DOC_TYPES = [
    "docs", "bugfix", "best-practice", "api",
    "architecture", "changelog", "setup", "readme", "test",
]


class DocsIndexer:
    def __init__(self, config: Config, collection_name: str = DEFAULT_COLLECTION,
                 embedding_fn=None):
        self.config = config
        self._collection_name = collection_name
        self._shadow_name = f"{collection_name}_migration"
        self._external_ef = embedding_fn
        self._migration: Optional[ModelMigration] = None
        self._migration_lock = threading.Lock()
        self._init_vectorstore()
        self._cleanup_orphaned_shadow()
        self._bm25_index = None
        self._bm25_corpus_ids: list[str] = []
        self._load_bm25_index()

    def _cleanup_orphaned_shadow(self):
        """Remove leftover shadow collection from interrupted migrations."""
        try:
            existing = [c.name for c in self.chroma.list_collections()]
            if self._shadow_name in existing:
                self.chroma.delete_collection(self._shadow_name)
                print(f"Cleaned up orphaned shadow collection '{self._shadow_name}'")
        except Exception:
            pass

    def _init_vectorstore(self):
        self.chroma = chromadb.PersistentClient(path=self.config.vectorstore_path)

        if self._external_ef:
            self.ef = self._external_ef
        elif self.config.embedding_provider == "local":
            self.ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=self.config.embedding_model
            )
        else:
            self.ef = embedding_functions.OpenAIEmbeddingFunction(
                api_key=self.config.openai_api_key,
                model_name=self.config.openai_embedding_model,
            )

        self.collection = self.chroma.get_or_create_collection(
            self._collection_name,
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"},
        )
        self._heal_dimension_mismatch()

    def _heal_dimension_mismatch(self):
        """Detect and auto-fix embedding dimension mismatch.

        This happens when the global embedding model changes (env var or Web UI)
        but the persisted collection still has vectors from the old model.
        Since all projects share one global model, there's no way to query the
        old vectors with the new model — both reads and writes would crash.

        The source docs live in git so the collection is just a derived cache.
        Safe to recreate: the next index_all() will re-embed everything."""
        if self.collection.count() == 0:
            return
        try:
            probe = self.collection.get(limit=1, include=["embeddings"])
            embs = probe.get("embeddings")
            if embs is None or len(embs) == 0:
                return
            first_emb = embs[0]
            if first_emb is None or len(first_emb) == 0:
                return
            stored_dim = len(first_emb)
            current_dim = len(self.ef([" "])[0])
            if stored_dim == current_dim:
                return
            model = (
                self.config.embedding_model
                if self.config.embedding_provider == "local"
                else self.config.openai_embedding_model
            )
            print(
                f"Dimension mismatch in '{self._collection_name}': "
                f"stored={stored_dim}d, model '{model}'={current_dim}d — "
                f"recreating collection (source docs in git, will re-embed)"
            )
            self.chroma.delete_collection(self._collection_name)
            self.collection = self.chroma.get_or_create_collection(
                self._collection_name,
                embedding_function=self.ef,
                metadata={"hnsw:space": "cosine"},
            )
            try:
                self._hashes_path.unlink(missing_ok=True)
            except Exception:
                pass
        except Exception as e:
            print(f"Warning: dimension check failed: {e}")

    def reinit(self, config: Config, embedding_fn=None):
        """Re-init with new config (e.g. after model change in Web UI)."""
        self.config = config
        if embedding_fn is not None:
            self._external_ef = embedding_fn
        try:
            self.chroma.delete_collection(self._collection_name)
        except Exception:
            pass
        try:
            self._hashes_path.unlink(missing_ok=True)
        except Exception:
            pass
        self._bm25_index = None
        self._bm25_corpus_ids = []
        bm25_dir = self._bm25_index_path()
        if bm25_dir.exists():
            shutil.rmtree(bm25_dir)
        self._init_vectorstore()

    # ── Model Hot-Swap (background migration) ────────────

    def start_model_swap(
        self, new_config: Config, index_lock: threading.Lock,
        quality_checker=None, health=None, new_ef=None,
    ) -> dict:
        """Start a background migration to a new embedding model.

        The old collection keeps serving searches until the new one is ready,
        then they are atomically swapped.  Pass new_ef to share an
        already-loaded embedding function across multiple projects.
        """
        with self._migration_lock:
            if self._migration and self._migration.status == "running":
                return {"status": "error", "message": "Migration already in progress", "migration": self._migration.to_dict()}

            old_model = (
                self.config.embedding_model
                if self.config.embedding_provider == "local"
                else self.config.openai_embedding_model
            )
            new_model = (
                new_config.embedding_model
                if new_config.embedding_provider == "local"
                else new_config.openai_embedding_model
            )
            if old_model == new_model and self.config.embedding_provider == new_config.embedding_provider:
                return {"status": "skipped", "message": "Same model selected, nothing to do"}

            docs_path = Path(new_config.docs_path)
            doc_files = sorted(_iter_docs(docs_path)) if docs_path.exists() else []

            migration = ModelMigration(
                old_model=old_model,
                new_model=new_model,
                total_files=len(doc_files),
            )
            self._migration = migration

        shadow_name = self._shadow_name
        collection_name = self._collection_name

        def _worker():
            try:
                nonlocal new_ef
                if new_ef is None:
                    if new_config.embedding_provider == "local":
                        new_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                            model_name=new_config.embedding_model
                        )
                    else:
                        new_ef = embedding_functions.OpenAIEmbeddingFunction(
                            api_key=new_config.openai_api_key,
                            model_name=new_config.openai_embedding_model,
                        )

                try:
                    self.chroma.delete_collection(shadow_name)
                except Exception:
                    pass

                shadow = self.chroma.get_or_create_collection(
                    shadow_name,
                    embedding_function=new_ef,
                    metadata={"hnsw:space": "cosine"},
                )

                for doc_file in doc_files:
                    if migration.status == "cancelled":
                        break
                    try:
                        content = extract_text(doc_file)
                        if content is None:
                            migration.files_done += 1
                            continue
                        rel_path = str(doc_file.relative_to(docs_path))

                        if quality_checker and doc_file.suffix.lower() == ".md":
                            issues = quality_checker.check_file(doc_file, rel_path)
                            critical = [i for i in issues if i["severity"] == "critical"]
                            if critical:
                                migration.files_done += 1
                                continue

                        chunks = self.chunk_markdown(content, rel_path)
                        if chunks:
                            shadow.upsert(
                                ids=[c["id"] for c in chunks],
                                documents=[c["text"] for c in chunks],
                                metadatas=[c["metadata"] for c in chunks],
                            )
                            migration.chunks_created += len(chunks)
                    except Exception as e:
                        print(f"Migration: error processing {doc_file}: {e}")
                    migration.files_done += 1

                if migration.status == "cancelled":
                    try:
                        self.chroma.delete_collection(shadow_name)
                    except Exception:
                        pass
                    migration.finished_at = datetime.now(timezone.utc).isoformat()
                    if health:
                        health.record_migration(migration.to_dict())
                    return

                with index_lock:
                    try:
                        self.chroma.delete_collection(collection_name)
                    except Exception:
                        pass

                    self.config = new_config
                    self.ef = new_ef
                    self._external_ef = new_ef

                    self.collection = self.chroma.get_or_create_collection(
                        collection_name,
                        embedding_function=new_ef,
                        metadata={"hnsw:space": "cosine"},
                    )

                    shadow_data = shadow.get(include=["documents", "metadatas"])
                    if shadow_data["ids"]:
                        batch_size = 5000
                        for i in range(0, len(shadow_data["ids"]), batch_size):
                            end = i + batch_size
                            self.collection.upsert(
                                ids=shadow_data["ids"][i:end],
                                documents=shadow_data["documents"][i:end],
                                metadatas=shadow_data["metadatas"][i:end],
                            )

                    try:
                        self.chroma.delete_collection(shadow_name)
                    except Exception:
                        pass

                    try:
                        self._hashes_path.unlink(missing_ok=True)
                    except Exception:
                        pass

                migration.status = "complete"
                migration.finished_at = datetime.now(timezone.utc).isoformat()

                if health:
                    health.record_migration(migration.to_dict())
                    health.record_index(ok=True, chunks=migration.chunks_created, files=migration.files_done)

            except Exception as e:
                migration.status = "failed"
                migration.error = str(e)
                migration.finished_at = datetime.now(timezone.utc).isoformat()
                try:
                    self.chroma.delete_collection(shadow_name)
                except Exception:
                    pass
                if health:
                    health.record_migration(migration.to_dict())
                print(f"Migration failed: {e}")

        t = threading.Thread(target=_worker, daemon=True, name=f"migration-{collection_name}")
        migration.thread = t
        t.start()

        if health:
            health.record_migration(migration.to_dict())

        return {"status": "started", "migration": migration.to_dict()}

    def cancel_migration(self) -> dict:
        with self._migration_lock:
            if not self._migration or self._migration.status != "running":
                return {"status": "error", "message": "No active migration to cancel"}
            self._migration.status = "cancelled"
            return {"status": "cancelled", "migration": self._migration.to_dict()}

    @property
    def migration_status(self) -> Optional[dict]:
        if self._migration is None:
            return None
        return self._migration.to_dict()

    # ── Chunk ID (content-based, position-independent) ───

    @staticmethod
    def _make_chunk_id(source: str, text: str) -> str:
        content = f"{source}\n{text}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    # ── Chunking ─────────────────────────────────────────

    def chunk_markdown(self, text: str, source: str) -> list[dict]:
        strategy = self.config.chunk_strategy
        if strategy == "heading":
            return self._chunk_by_heading(text, source)
        elif strategy == "fixed":
            return self._chunk_fixed_size(text, source)
        elif strategy == "hybrid":
            return self._chunk_hybrid(text, source)
        return self._chunk_by_heading(text, source)

    def _chunk_by_heading(self, text: str, source: str) -> list[dict]:
        """Split at headings, preserving parent heading context."""
        chunks = []
        heading_stack: list[tuple[int, str]] = []
        current_lines: list[str] = []
        current_heading = "intro"
        current_heading_path = ""
        chunk_start_line = 1

        for line_num, line in enumerate(text.split("\n"), start=1):
            match = re.match(r"^(#{1,3})\s+(.*)", line)
            if match:
                if current_lines:
                    self._flush_chunk(
                        chunks, current_lines, current_heading,
                        current_heading_path, source, chunk_start_line,
                    )

                level = len(match.group(1))
                title = match.group(2).strip()

                heading_stack = [(l, t) for l, t in heading_stack if l < level]
                heading_stack.append((level, title))

                current_heading = title
                current_heading_path = " > ".join(t for _, t in heading_stack)
                current_lines = [line]
                chunk_start_line = line_num
            else:
                current_lines.append(line)

        if current_lines:
            self._flush_chunk(
                chunks, current_lines, current_heading,
                current_heading_path, source, chunk_start_line,
            )

        return chunks

    def _flush_chunk(
        self, chunks: list, lines: list[str], heading: str,
        heading_path: str, source: str, line_start: int = 1,
    ):
        raw = "\n".join(lines).strip()
        if len(raw) <= 50:
            return
        line_end = line_start + len(lines) - 1
        display_text = f"[{heading_path}]\n\n{raw}" if heading_path else raw
        chunk = self._make_chunk(display_text, heading, heading_path, source)
        chunk["metadata"]["line_start"] = line_start
        chunk["metadata"]["line_end"] = line_end
        chunks.append(chunk)

    def _chunk_fixed_size(self, text: str, source: str) -> list[dict]:
        max_chars = self.config.chunk_max_chars
        overlap = self.config.chunk_overlap
        chunks = []
        start = 0

        while start < len(text):
            end = start + max_chars
            chunk_text = text[start:end]

            if end < len(text):
                last_period = chunk_text.rfind(". ")
                if last_period > max_chars * 0.5:
                    chunk_text = chunk_text[: last_period + 1]
                    end = start + last_period + 1

            line_start = text[:start].count("\n") + 1
            line_end = line_start + chunk_text.count("\n")

            chunk_text = chunk_text.strip()
            if len(chunk_text) > 50:
                chunk = self._make_chunk(
                    chunk_text, f"chunk-{len(chunks)}", "", source,
                )
                chunk["metadata"]["line_start"] = line_start
                chunk["metadata"]["line_end"] = line_end
                chunks.append(chunk)
            start = end - overlap

        return chunks

    def _chunk_hybrid(self, text: str, source: str) -> list[dict]:
        heading_chunks = self._chunk_by_heading(text, source)
        final_chunks = []

        for chunk in heading_chunks:
            if len(chunk["text"]) > self.config.chunk_max_chars:
                sub_chunks = self._chunk_fixed_size(chunk["text"], source)
                for i, sc in enumerate(sub_chunks):
                    sc["metadata"]["heading"] = (
                        f"{chunk['metadata']['heading']} (part {i + 1})"
                    )
                    sc["id"] = self._make_chunk_id(source, sc["text"])
                final_chunks.extend(sub_chunks)
            else:
                final_chunks.append(chunk)

        return final_chunks

    def _make_chunk(
        self, text: str, heading: str, heading_path: str, source: str,
    ) -> dict:
        text = text.strip()
        return {
            "id": self._make_chunk_id(source, text),
            "text": text,
            "metadata": {
                "source": source,
                "heading": heading,
                "heading_path": heading_path,
                "type": self._detect_type(source),
                "char_count": len(text),
                "word_count": len(text.split()),
            },
        }

    @staticmethod
    def _detect_type(path: str) -> str:
        p = path.lower()
        if "bugfix" in p or "bug-fix" in p:
            return "bugfix"
        if "best-practice" in p or "bestpractice" in p:
            return "best-practice"
        if "api" in p:
            return "api"
        if "architect" in p:
            return "architecture"
        if "changelog" in p or "release" in p:
            return "changelog"
        if "setup" in p or "install" in p:
            return "setup"
        if "readme" in p:
            return "readme"
        if "test" in p:
            return "test"
        return "docs"

    # ── File hash tracking (for diff-aware reindex) ─────

    @property
    def _hashes_path(self) -> Path:
        suffix = "" if self._collection_name == DEFAULT_COLLECTION else f"_{self._collection_name}"
        return Path(self.config.vectorstore_path) / f"file_hashes{suffix}.json"

    def _load_file_hashes(self) -> dict[str, str]:
        try:
            return json.loads(self._hashes_path.read_text())
        except Exception:
            return {}

    def _save_file_hashes(self, hashes: dict[str, str]):
        self._hashes_path.parent.mkdir(parents=True, exist_ok=True)
        self._hashes_path.write_text(json.dumps(hashes))

    @staticmethod
    def _content_hash(content: str) -> str:
        return hashlib.md5(content.encode()).hexdigest()

    # ── Indexing ─────────────────────────────────────────

    def index_all(self, force: bool = False, quality_checker=None) -> dict:
        """Diff-aware (re-)index: only re-embeds changed/new files.
        Set force=True to skip hash check (full rebuild).
        If quality_checker is provided, files with critical issues are
        skipped (NOT indexed) but NEVER deleted or modified."""
        docs_path = Path(self.config.docs_path)

        if not docs_path.exists():
            return {"status": "error", "message": f"Path does not exist: {docs_path}"}

        existing_ids: set[str] = set()
        try:
            result = self.collection.get(include=[])
            existing_ids = set(result["ids"])
        except Exception:
            pass

        if not force and not existing_ids:
            force = True
            print("Collection empty — forcing full re-index (ignoring hash cache)")

        old_hashes = {} if force else self._load_file_hashes()
        new_hashes: dict[str, str] = {}

        all_chunks: list[dict] = []
        changed_chunks: list[dict] = []
        file_count = 0
        skipped = 0
        quality_skipped: list[dict] = []

        for doc_file in sorted(_iter_docs(docs_path)):
            try:
                content = extract_text(doc_file)
                if content is None:
                    continue
                rel_path = str(doc_file.relative_to(docs_path))
                content_hash = self._content_hash(content)
                new_hashes[rel_path] = content_hash

                if quality_checker and doc_file.suffix.lower() == ".md":
                    issues = quality_checker.check_file(doc_file, rel_path)
                    critical = [i for i in issues if i["severity"] == "critical"]
                    if critical:
                        reasons = "; ".join(i["message"] for i in critical)
                        quality_skipped.append({"file": rel_path, "reason": reasons})
                        print(f"Quality gate: skipping {rel_path} ({reasons})")
                        continue

                chunks = self.chunk_markdown(content, rel_path)
                all_chunks.extend(chunks)
                file_count += 1

                if old_hashes.get(rel_path) != content_hash:
                    changed_chunks.extend(chunks)
                else:
                    skipped += 1
            except Exception as e:
                print(f"Warning: Error processing {doc_file}: {e}")

        # Deduplicate
        deduped_all: dict[str, dict] = {}
        for chunk in all_chunks:
            deduped_all[chunk["id"]] = chunk
        new_ids = set(deduped_all.keys())

        deduped_changed: dict[str, dict] = {}
        for chunk in changed_chunks:
            deduped_changed[chunk["id"]] = chunk
        upsert_chunks = list(deduped_changed.values())

        if upsert_chunks:
            batch_size = 5000
            for i in range(0, len(upsert_chunks), batch_size):
                batch = upsert_chunks[i : i + batch_size]
                self.collection.upsert(
                    ids=[c["id"] for c in batch],
                    documents=[c["text"] for c in batch],
                    metadatas=[c["metadata"] for c in batch],
                )

        # Remove chunks from deleted/renamed files — but NEVER wipe all
        # chunks when 0 files were found (repo not cloned yet / empty dir).
        stale_ids = existing_ids - new_ids
        if stale_ids and file_count > 0:
            stale_list = list(stale_ids)
            for i in range(0, len(stale_list), 5000):
                self.collection.delete(ids=stale_list[i : i + 5000])
        elif stale_ids and file_count == 0 and existing_ids:
            print(f"Safety: 0 files on disk but {len(existing_ids)} chunks in DB "
                  f"— skipping stale removal (repo may not be cloned yet)")
            stale_ids = set()

        # Verify ChromaDB actually persisted before saving hashes.
        # If count is 0 but we expected chunks, don't save hashes —
        # next startup will re-embed everything.
        actual_count = self.collection.count()
        expected_count = len(deduped_all) - len(stale_ids)
        if actual_count > 0 or expected_count == 0:
            self._save_file_hashes(new_hashes)
        else:
            print(f"Warning: ChromaDB count={actual_count} but expected ~{expected_count}, "
                  f"not saving hash cache (will re-embed on next run)")

        self._build_bm25_index(list(deduped_all.values()))

        result = {
            "status": "success",
            "files_indexed": file_count,
            "files_changed": file_count - skipped,
            "files_skipped": skipped,
            "files_quality_skipped": len(quality_skipped),
            "quality_skipped": quality_skipped,
            "chunks_upserted": len(upsert_chunks),
            "chunks_total": len(deduped_all),
            "chunks_removed": len(stale_ids),
            "docs_path": str(docs_path),
        }
        print(
            f"Index: {file_count} files ({file_count - skipped} changed, "
            f"{skipped} skipped) -> {len(upsert_chunks)} chunks upserted"
            f" ({len(stale_ids)} stale removed)"
        )
        return result

    def index_single(self, filepath: str, content: str) -> int:
        chunks = self.chunk_markdown(content, filepath)
        if chunks:
            self.collection.upsert(
                ids=[c["id"] for c in chunks],
                documents=[c["text"] for c in chunks],
                metadatas=[c["metadata"] for c in chunks],
            )
        return len(chunks)

    def clear_index(self):
        try:
            self.chroma.delete_collection(self._collection_name)
        except Exception:
            pass
        self.collection = self.chroma.get_or_create_collection(
            self._collection_name,
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"},
        )
        # Reset file hashes so next index_all() re-embeds everything
        try:
            self._hashes_path.unlink(missing_ok=True)
        except Exception:
            pass
        self._bm25_index = None
        self._bm25_corpus_ids = []
        bm25_dir = self._bm25_index_path()
        if bm25_dir.exists():
            shutil.rmtree(bm25_dir)

    # ── BM25 (keyword search) ────────────────────────────

    def _bm25_index_path(self) -> Path:
        return Path(self.config.vectorstore_path) / f"{self._collection_name}_bm25"

    def _load_bm25_index(self):
        """Load persisted BM25 index if it exists."""
        idx_dir = self._bm25_index_path()
        ids_path = idx_dir / "corpus_ids.json"
        if idx_dir.exists() and ids_path.exists():
            try:
                self._bm25_index = bm25s.BM25.load(idx_dir, load_corpus=False)
                with open(ids_path) as f:
                    self._bm25_corpus_ids = json.load(f)
            except Exception:
                self._bm25_index = None
                self._bm25_corpus_ids = []

    def _build_bm25_index(self, chunks: list[dict]):
        """Build BM25 index from chunks and persist."""
        if not chunks:
            return
        corpus = [c["text"] for c in chunks]
        ids = [c["id"] for c in chunks]
        corpus_tokens = bm25s.tokenize(corpus, stopwords="en")
        retriever = bm25s.BM25()
        retriever.index(corpus_tokens)
        idx_dir = self._bm25_index_path()
        idx_dir.mkdir(parents=True, exist_ok=True)
        retriever.save(idx_dir)
        with open(idx_dir / "corpus_ids.json", "w") as f:
            json.dump(ids, f)
        self._bm25_index = retriever
        self._bm25_corpus_ids = ids

    def _bm25_search(self, query: str, top_k: int, type_filter: Optional[str] = None) -> list[dict]:
        """BM25 keyword search. Returns list of {id, text, metadata, score}."""
        if self._bm25_index is None or not self._bm25_corpus_ids:
            return []
        query_tokens = bm25s.tokenize([query], stopwords="en")
        fetch_k = min(top_k * 5, len(self._bm25_corpus_ids))
        results, scores = self._bm25_index.retrieve(query_tokens, k=fetch_k)
        hits: list[dict] = []
        for i in range(results.shape[1]):
            idx = int(results[0, i])
            score = float(scores[0, i])
            if idx < 0 or idx >= len(self._bm25_corpus_ids) or score <= 0:
                continue
            chunk_id = self._bm25_corpus_ids[idx]
            try:
                doc = self.collection.get(ids=[chunk_id], include=["documents", "metadatas"])
                if not doc["ids"]:
                    continue
                meta = doc["metadatas"][0] if doc["metadatas"] else {}
                text = doc["documents"][0] if doc["documents"] else ""
            except Exception:
                continue
            if type_filter and meta.get("type", "") != type_filter:
                continue
            hits.append({"id": chunk_id, "text": text, "metadata": meta, "score": score, "_from": "bm25"})
            if len(hits) >= top_k:
                break
        return hits

    def _rrf_fuse(
        self, vector_hits: list[dict], bm25_hits: list[dict], top_k: int,
        k: int | None = None,
        vector_weight: float | None = None,
        bm25_weight: float | None = None,
    ) -> list[dict]:
        """Reciprocal Rank Fusion: merge two ranked lists with configurable weights."""
        k = k if k is not None else self.config.rrf_k
        vw = vector_weight if vector_weight is not None else self.config.rrf_vector_weight
        bw = bm25_weight if bm25_weight is not None else self.config.rrf_bm25_weight
        scores: dict[str, float] = {}
        docs: dict[str, dict] = {}
        for rank, hit in enumerate(vector_hits, 1):
            cid = hit["id"]
            scores[cid] = scores.get(cid, 0.0) + vw / (k + rank)
            docs[cid] = hit
        for rank, hit in enumerate(bm25_hits, 1):
            cid = hit["id"]
            scores[cid] = scores.get(cid, 0.0) + bw / (k + rank)
            if cid not in docs:
                docs[cid] = hit
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [docs[cid] for cid, _ in ranked]

    # ── Search ───────────────────────────────────────────

    def _vector_search(self, query: str, top_k: int, type_filter: Optional[str] = None) -> list[dict]:
        """ChromaDB vector search. Returns list of {id, text, metadata, score, _from}."""
        if self.collection.count() == 0:
            return []
        kwargs: dict = {
            "query_texts": [query],
            "n_results": min(top_k, self.collection.count()),
        }
        if type_filter:
            kwargs["where"] = {"type": type_filter}
        try:
            results = self.collection.query(**kwargs)
        except Exception as e:
            print(f"Vector search error: {e}")
            return []
        if not results["documents"] or not results["documents"][0]:
            return []
        return [
            {"id": cid, "text": doc, "metadata": meta, "score": dist, "_from": "vector"}
            for cid, doc, meta, dist in zip(
                results["ids"][0],
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ]

    def _rerank(self, query: str, hits: list[dict], top_k: int) -> list[dict]:
        """Re-score hits with a cross-encoder reranker for higher precision."""
        if not hits:
            return hits
        reranker = _get_reranker(self.config.reranker_model)
        if reranker is None:
            return hits[:top_k]
        pairs = [(query, hit["text"]) for hit in hits]
        try:
            scores = reranker.predict(pairs)
            for hit, score in zip(hits, scores):
                hit["rerank_score"] = float(score)
            hits.sort(key=lambda h: h.get("rerank_score", 0), reverse=True)
        except Exception as e:
            print(f"Reranker error: {e}")
        return hits[:top_k]

    @staticmethod
    def _normalize_bm25_relevance(hits: list[dict]) -> None:
        """Normalize BM25 scores to 0-100 relevance, in-place."""
        if not hits:
            return
        scores = [h["score"] for h in hits if h.get("score", 0) > 0]
        if not scores:
            return
        max_score = max(scores)
        if max_score <= 0:
            return
        for hit in hits:
            raw = hit.get("score", 0)
            hit["bm25_relevance"] = round((raw / max_score) * 100, 1) if raw > 0 else 0.0

    def search(
        self, query: str, top_k: int = 5, type_filter: Optional[str] = None,
    ) -> list[dict]:
        use_reranker = self.config.reranker_enabled
        fetch_k = top_k * 5 if use_reranker else top_k

        vector_hits = self._vector_search(query, fetch_k, type_filter)

        if self.config.hybrid_search and self._bm25_index is not None and self._bm25_corpus_ids:
            bm25_hits = self._bm25_search(query, fetch_k, type_filter)
            self._normalize_bm25_relevance(bm25_hits)
            rerank_pool = top_k * 4 if use_reranker else top_k
            merged = self._rrf_fuse(vector_hits, bm25_hits, rerank_pool)
        else:
            self._normalize_bm25_relevance([])
            merged = vector_hits

        if use_reranker and len(merged) > 1:
            merged = self._rerank(query, merged, top_k)
        else:
            merged = merged[:top_k]

        min_rel = self.config.min_relevance
        out: list[dict] = []
        for hit in merged:
            meta = hit["metadata"]
            dist = hit.get("score", 0)
            if hit.get("_from") == "vector":
                relevance = round((1 - dist) * 100, 1)
            elif hit.get("bm25_relevance") is not None:
                relevance = hit["bm25_relevance"]
                dist = 0.0
            else:
                relevance = 0.0
                dist = 0.0

            if hit.get("rerank_score") is not None:
                relevance = round(max(0, min(100, hit["rerank_score"] * 100)), 1)

            if min_rel > 0 and relevance < min_rel:
                continue

            out.append({
                "text": hit["text"],
                "source": meta["source"],
                "heading": meta["heading"],
                "heading_path": meta.get("heading_path", ""),
                "type": meta["type"],
                "char_count": meta.get("char_count", 0),
                "line_start": meta.get("line_start", 0),
                "line_end": meta.get("line_end", 0),
                "distance": dist,
                "relevance": relevance,
            })
        return out

    # ── Stats (efficient: queries by type, no bulk load) ─

    @property
    def stats(self) -> dict:
        total = self.collection.count()

        type_counts: dict[str, int] = {}
        if total > 0:
            for doc_type in DOC_TYPES:
                try:
                    result = self.collection.get(
                        where={"type": doc_type}, include=[]
                    )
                    count = len(result["ids"])
                    if count > 0:
                        type_counts[doc_type] = count
                except Exception:
                    pass

        return {
            "total_chunks": total,
            "type_distribution": type_counts,
            "docs_path": self.config.docs_path,
            "embedding_provider": self.config.embedding_provider,
            "embedding_model": (
                self.config.embedding_model
                if self.config.embedding_provider == "local"
                else self.config.openai_embedding_model
            ),
            "chunk_strategy": self.config.chunk_strategy,
        }
