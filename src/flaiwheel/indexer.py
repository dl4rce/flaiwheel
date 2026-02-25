# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH. All rights reserved.
# Non-commercial use only. Commercial licensing: info@4rce.com

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
import re
from pathlib import Path
from typing import Optional
import chromadb
from chromadb.utils import embedding_functions
from .config import Config

DOC_TYPES = [
    "docs", "bugfix", "best-practice", "api",
    "architecture", "changelog", "setup", "readme",
]


class DocsIndexer:
    def __init__(self, config: Config):
        self.config = config
        self._init_vectorstore()

    def _init_vectorstore(self):
        self.chroma = chromadb.PersistentClient(path=self.config.vectorstore_path)

        if self.config.embedding_provider == "local":
            self.ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=self.config.embedding_model
            )
        else:
            self.ef = embedding_functions.OpenAIEmbeddingFunction(
                api_key=self.config.openai_api_key,
                model_name=self.config.openai_embedding_model,
            )

        self.collection = self.chroma.get_or_create_collection(
            "project_docs",
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"},
        )

    def reinit(self, config: Config):
        """Re-init with new config (e.g. after model change in Web UI)."""
        self.config = config
        try:
            self.chroma.delete_collection("project_docs")
        except Exception:
            pass
        self._init_vectorstore()

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

        for line in text.split("\n"):
            match = re.match(r"^(#{1,3})\s+(.*)", line)
            if match:
                if current_lines:
                    self._flush_chunk(
                        chunks, current_lines, current_heading,
                        current_heading_path, source,
                    )

                level = len(match.group(1))
                title = match.group(2).strip()

                heading_stack = [(l, t) for l, t in heading_stack if l < level]
                heading_stack.append((level, title))

                current_heading = title
                current_heading_path = " > ".join(t for _, t in heading_stack)
                current_lines = [line]
            else:
                current_lines.append(line)

        if current_lines:
            self._flush_chunk(
                chunks, current_lines, current_heading,
                current_heading_path, source,
            )

        return chunks

    def _flush_chunk(
        self, chunks: list, lines: list[str], heading: str,
        heading_path: str, source: str,
    ):
        raw = "\n".join(lines).strip()
        if len(raw) <= 50:
            return
        display_text = f"[{heading_path}]\n\n{raw}" if heading_path else raw
        chunks.append(self._make_chunk(display_text, heading, heading_path, source))

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

            chunk_text = chunk_text.strip()
            if len(chunk_text) > 50:
                chunks.append(
                    self._make_chunk(chunk_text, f"chunk-{len(chunks)}", "", source)
                )
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
        return "docs"

    # ── Indexing ─────────────────────────────────────────

    def index_all(self) -> dict:
        """Full (re-)index of all .md files with stale chunk cleanup."""
        docs_path = Path(self.config.docs_path)

        if not docs_path.exists():
            return {"status": "error", "message": f"Path does not exist: {docs_path}"}

        existing_ids: set[str] = set()
        try:
            result = self.collection.get(include=[])
            existing_ids = set(result["ids"])
        except Exception:
            pass

        all_chunks: list[dict] = []
        file_count = 0

        for md_file in sorted(docs_path.rglob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                rel_path = str(md_file.relative_to(docs_path))
                chunks = self.chunk_markdown(content, rel_path)
                all_chunks.extend(chunks)
                file_count += 1
            except Exception as e:
                print(f"Warning: Error processing {md_file}: {e}")

        # Deduplicate: ChromaDB upsert rejects duplicate IDs within a batch
        deduped: dict[str, dict] = {}
        for chunk in all_chunks:
            deduped[chunk["id"]] = chunk
        unique_chunks = list(deduped.values())

        new_ids: set[str] = set()
        if unique_chunks:
            batch_size = 5000
            for i in range(0, len(unique_chunks), batch_size):
                batch = unique_chunks[i : i + batch_size]
                self.collection.upsert(
                    ids=[c["id"] for c in batch],
                    documents=[c["text"] for c in batch],
                    metadatas=[c["metadata"] for c in batch],
                )
            new_ids = set(deduped.keys())
        if len(all_chunks) != len(unique_chunks):
            print(f"Deduplicated {len(all_chunks) - len(unique_chunks)} chunks with identical IDs")

        stale_ids = existing_ids - new_ids
        if stale_ids:
            stale_list = list(stale_ids)
            for i in range(0, len(stale_list), 5000):
                self.collection.delete(ids=stale_list[i : i + 5000])
            print(f"Cleaned up {len(stale_ids)} stale chunks")

        result = {
            "status": "success",
            "files_indexed": file_count,
            "chunks_created": len(unique_chunks),
            "chunks_removed": len(stale_ids),
            "docs_path": str(docs_path),
        }
        print(
            f"Index: {file_count} files -> {len(unique_chunks)} chunks"
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
            self.chroma.delete_collection("project_docs")
        except Exception:
            pass
        self.collection = self.chroma.get_or_create_collection(
            "project_docs",
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"},
        )

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
