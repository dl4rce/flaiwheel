# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.md.

"""
Markdown docs -> Chunks -> Vector Embeddings -> ChromaDB

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
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import chromadb
from chromadb.utils import embedding_functions
from .config import Config

DEFAULT_COLLECTION = "project_docs"


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
            md_files = sorted(docs_path.rglob("*.md")) if docs_path.exists() else []

            migration = ModelMigration(
                old_model=old_model,
                new_model=new_model,
                total_files=len(md_files),
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

                for md_file in md_files:
                    if migration.status == "cancelled":
                        break
                    try:
                        content = md_file.read_text(encoding="utf-8", errors="ignore")
                        rel_path = str(md_file.relative_to(docs_path))

                        if quality_checker:
                            issues = quality_checker.check_file(md_file, rel_path)
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
                        print(f"Migration: error processing {md_file}: {e}")
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

        old_hashes = {} if force else self._load_file_hashes()
        new_hashes: dict[str, str] = {}

        existing_ids: set[str] = set()
        try:
            result = self.collection.get(include=[])
            existing_ids = set(result["ids"])
        except Exception:
            pass

        all_chunks: list[dict] = []
        changed_chunks: list[dict] = []
        file_count = 0
        skipped = 0
        quality_skipped: list[dict] = []

        for md_file in sorted(docs_path.rglob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                rel_path = str(md_file.relative_to(docs_path))
                content_hash = self._content_hash(content)
                new_hashes[rel_path] = content_hash

                if quality_checker:
                    issues = quality_checker.check_file(md_file, rel_path)
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
                print(f"Warning: Error processing {md_file}: {e}")

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

        # Remove chunks from deleted/renamed files
        stale_ids = existing_ids - new_ids
        if stale_ids:
            stale_list = list(stale_ids)
            for i in range(0, len(stale_list), 5000):
                self.collection.delete(ids=stale_list[i : i + 5000])

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

    # ── Search ───────────────────────────────────────────

    def search(
        self, query: str, top_k: int = 5, type_filter: Optional[str] = None,
    ) -> list[dict]:
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
            print(f"Search error: {e}")
            return []

        if not results["documents"] or not results["documents"][0]:
            return []

        return [
            {
                "text": doc,
                "source": meta["source"],
                "heading": meta["heading"],
                "heading_path": meta.get("heading_path", ""),
                "type": meta["type"],
                "char_count": meta.get("char_count", 0),
                "line_start": meta.get("line_start", 0),
                "line_end": meta.get("line_end", 0),
                "distance": dist,
                "relevance": round((1 - dist) * 100, 1),
            }
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ]

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
