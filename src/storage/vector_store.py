"""Persistent vector storage on top of ChromaDB.

Responsibilities
----------------
- Open one persistent Chroma client backed by `settings.chroma_path` and
  hand out a single collection named `settings.chroma_collection`.
- Index every ingested item by its URL: the document text is
  `IngestionResult.aggregated_text`, the metadata is a flat dictionary
  derived from `AnalysisResult` plus extraction-level fields, so the
  search results carry enough context to render in the iOS UI without a
  second fetch.
- Provide `search_items`, `get_all_categories`, and `get_by_url` for the
  orchestrator + CLI.

Chroma metadata restriction: values must be `str | int | float | bool`.
Lists / dicts therefore get either pipe-joined for filterability OR
JSON-encoded for round-trip on retrieval. We do both for the entities
payload because the iOS app needs the structured form back.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils import embedding_functions as ef

from src.config import settings
from src.logger import get_logger
from src.schemas import IngestionResult, SearchHit, SourceType

logger = get_logger(__name__)


# Metadata keys we promise downstream code will exist on every stored item.
META_KEYS = (
    "url", "source_type", "title", "category", "is_uncertain",
    "alternative_categories", "summary", "key_insights",
    "price", "location", "technologies",
    "entities_json", "ingested_at", "created_at", "status",
)

# `status` lifecycle: "processing" → ("completed" | "failed")
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


class VectorStoreManager:
    """Thin wrapper around a single Chroma collection."""

    def __init__(
        self,
        path: str | Path | None = None,
        collection_name: str | None = None,
        embedding_backend: str | None = None,
    ) -> None:
        self.path = Path(path) if path else settings.chroma_path
        self.path.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name or settings.chroma_collection
        self.embedding_backend = embedding_backend or settings.embedding_backend

        logger.info(
            "Opening Chroma at path=%s collection=%s backend=%s",
            self.path, self.collection_name, self.embedding_backend,
        )

        self._client = chromadb.PersistentClient(
            path=str(self.path),
            settings=ChromaSettings(
                anonymized_telemetry=settings.chroma_telemetry,
                allow_reset=True,
            ),
        )
        self._embedder = self._build_embedder(self.embedding_backend)
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self._embedder,
            metadata={"hnsw:space": "cosine"},
        )

    # ============================================================ write path
    def add_item(self, url: str, ingestion_result: IngestionResult) -> bool:
        """Upsert one fully-processed item by URL. Returns True on success.

        Status is taken from `ingestion_result.status` (default "completed"),
        so the background pipeline can write either "completed" on success or
        "failed" on error by setting that field before calling us.
        """
        text = ingestion_result.aggregated_text
        if not text.strip():
            logger.warning("Refusing to store %s — no aggregated text.", url)
            return False
        if ingestion_result.analysis is None:
            logger.warning("Refusing to store %s — no analysis attached.", url)
            return False

        metadata = self._build_metadata(url, ingestion_result)
        try:
            self._collection.upsert(
                ids=[url],
                documents=[text],
                metadatas=[metadata],
            )
        except Exception:
            logger.exception("Chroma upsert failed for %s", url)
            return False

        logger.info(
            "Stored %s → category=%r status=%s (count now %d)",
            url, metadata.get("category"), metadata.get("status"), self.count(),
        )
        return True

    def add_placeholder(self, url: str, source_type: SourceType) -> bool:
        """Persist a minimal stub the moment a share is accepted, so the iOS
        client sees the item immediately and the background pipeline can fill
        in real data over the top of this row later.

        The document embedded is just the URL — the placeholder is searchable
        but unlikely to win against real items. Once the background task
        finishes, `add_item` upserts the same id with the full embedding.
        """
        now = datetime.now(timezone.utc)
        metadata: dict[str, Any] = {
            "url": url,
            "source_type": source_type.value,
            "title": "",
            "category": "Processing",
            "is_uncertain": False,
            "alternative_categories": "",
            "summary": "Working on this — extract, analyze, index…",
            "key_insights": "[]",
            "price": "",
            "location": "",
            "technologies": "",
            "entities_json": "{}",
            "status": STATUS_PROCESSING,
            "ingested_at": now.isoformat(timespec="seconds"),
            "created_at": int(now.timestamp()),
        }
        try:
            self._collection.upsert(ids=[url], documents=[url], metadatas=[metadata])
        except Exception:
            logger.exception("Chroma placeholder upsert failed for %s", url)
            return False
        logger.info("Placeholder stored %s (count now %d)", url, self.count())
        return True

    def delete_item(self, url: str) -> bool:
        """Remove one item by URL. Returns True iff the row actually existed."""
        try:
            existing = self._collection.get(ids=[url])
        except Exception:
            logger.exception("delete_item could not read %s", url)
            return False
        if not (existing.get("ids") or []):
            return False
        try:
            self._collection.delete(ids=[url])
        except Exception:
            logger.exception("Chroma delete failed for %s", url)
            return False
        logger.info("Deleted %s (count now %d)", url, self.count())
        return True

    def update_item(
        self,
        url: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        category: str | None = None,
    ) -> SearchHit | None:
        """Patch a stored row's title / summary / category in place.

        Only fields that are not None are applied. Returns the updated
        SearchHit, or None if the row didn't exist. We never re-embed —
        editing metadata doesn't change semantic content the user cares
        about for search ranking.
        """
        try:
            existing = self._collection.get(ids=[url], include=["metadatas", "documents"])
        except Exception:
            logger.exception("update_item could not read %s", url)
            return None
        if not (existing.get("ids") or []):
            return None

        meta = (existing.get("metadatas") or [{}])[0] or {}
        if title is not None:
            meta["title"] = title
        if summary is not None:
            meta["summary"] = summary
        if category is not None:
            meta["category"] = category

        try:
            self._collection.update(ids=[url], metadatas=[meta])
        except Exception:
            logger.exception("Chroma update failed for %s", url)
            return None

        doc = (existing.get("documents") or [""])[0] or ""
        logger.info(
            "Patched %s — fields=%s",
            url, [k for k, v in {"title": title, "summary": summary, "category": category}.items() if v is not None],
        )
        return SearchHit(
            url=url,
            document=doc,
            category=meta.get("category"),
            summary=meta.get("summary"),
            metadata=dict(meta),
        )

    def rename_category(self, old_name: str, new_name: str) -> int:
        """Bulk-rename a category. Returns the number of rows that moved."""
        if not old_name or not new_name or old_name == new_name:
            return 0
        try:
            res = self._collection.get(
                where={"category": old_name},
                include=["metadatas"],
            )
        except Exception:
            logger.exception("rename_category lookup failed for %r", old_name)
            return 0

        ids = res.get("ids") or []
        if not ids:
            return 0

        new_metas: list[dict[str, Any]] = []
        for meta in res.get("metadatas") or []:
            m = dict(meta or {})
            m["category"] = new_name
            new_metas.append(m)

        try:
            self._collection.update(ids=ids, metadatas=new_metas)
        except Exception:
            logger.exception("rename_category update failed (%r → %r)", old_name, new_name)
            return 0
        logger.info("Renamed category %r → %r across %d items", old_name, new_name, len(ids))
        return len(ids)

    def delete_category(self, name: str) -> int:
        """Bulk-delete every row whose category matches `name`. Returns
        the number of rows removed."""
        if not name:
            return 0
        try:
            res = self._collection.get(where={"category": name})
        except Exception:
            logger.exception("delete_category lookup failed for %r", name)
            return 0
        ids = res.get("ids") or []
        if not ids:
            return 0
        try:
            self._collection.delete(ids=ids)
        except Exception:
            logger.exception("delete_category delete failed for %r", name)
            return 0
        logger.info("Deleted category %r — %d items removed", name, len(ids))
        return len(ids)

    def mark_failed(self, url: str, error: str) -> bool:
        """Flip an existing row's status to "failed" with the error reason.

        Used when the background pipeline crashes after a placeholder was
        already written. If the row doesn't exist (e.g. add_placeholder never
        ran), we no-op — there's nothing useful to mark.
        """
        try:
            existing = self._collection.get(ids=[url], include=["metadatas"])
        except Exception:
            logger.exception("mark_failed could not read %s", url)
            return False

        if not (existing.get("ids") or []):
            logger.warning("mark_failed: no existing row for %s", url)
            return False

        meta = (existing.get("metadatas") or [{}])[0] or {}
        meta["status"] = STATUS_FAILED
        snippet = (error or "")[:200]
        meta["summary"] = f"Couldn't process: {snippet}" if snippet else "Couldn't process this item."
        try:
            self._collection.update(ids=[url], metadatas=[meta])
        except Exception:
            logger.exception("Chroma update failed for %s", url)
            return False
        logger.warning("Marked %s as failed: %s", url, snippet)
        return True

    # ============================================================ read path
    def search_items(
        self,
        query: str,
        limit: int = 5,
        category: str | None = None,
    ) -> list[SearchHit]:
        """Semantic search; optionally restrict to a single category."""
        if not query.strip():
            return []

        where = {"category": category} if category else None
        try:
            res = self._collection.query(
                query_texts=[query],
                n_results=limit,
                where=where,
            )
        except Exception:
            logger.exception("Chroma query failed (query=%r)", query)
            return []

        return self._hydrate_query(res)

    def get_all_categories(self) -> list[str]:
        """Unique sorted list of every category value seen in the store.

        Skips placeholder rows whose status is "processing" so the
        synthetic "Processing" bucket never appears in the iOS dashboard.
        """
        try:
            res = self._collection.get(include=["metadatas"])
        except Exception:
            logger.exception("Chroma get(all) failed")
            return []
        seen: set[str] = set()
        for meta in res.get("metadatas") or []:
            m = meta or {}
            if m.get("status") == STATUS_PROCESSING:
                continue
            cat = m.get("category")
            if isinstance(cat, str) and cat and cat != "Processing":
                seen.add(cat)
        return sorted(seen)

    def get_by_url(self, url: str) -> SearchHit | None:
        try:
            res = self._collection.get(ids=[url], include=["metadatas", "documents"])
        except Exception:
            logger.exception("Chroma get-by-url failed for %s", url)
            return None
        ids = res.get("ids") or []
        if not ids:
            return None
        meta = (res.get("metadatas") or [{}])[0] or {}
        doc = (res.get("documents") or [""])[0] or ""
        return SearchHit(
            url=ids[0],
            document=doc,
            category=meta.get("category"),
            summary=meta.get("summary"),
            metadata=dict(meta),
        )

    def count(self) -> int:
        try:
            return self._collection.count()
        except Exception:
            logger.exception("Chroma count() failed")
            return 0

    # ============================================================ internals
    def _build_embedder(self, backend: str) -> Any:
        backend = (backend or "default").lower()
        if backend == "ollama":
            logger.info(
                "Using OllamaEmbeddingFunction url=%s model=%s",
                settings.ollama_host, settings.ollama_embed_model,
            )
            return ef.OllamaEmbeddingFunction(
                url=settings.ollama_host,
                model_name=settings.ollama_embed_model,
            )
        # Fallback to the bundled ONNX all-MiniLM-L6-v2 (no extra deps).
        logger.info("Using bundled DefaultEmbeddingFunction (all-MiniLM-L6-v2)")
        return ef.DefaultEmbeddingFunction()

    def _build_metadata(self, url: str, result: IngestionResult) -> dict[str, Any]:
        analysis = result.analysis
        assert analysis is not None  # guarded in add_item

        title: str | None = None
        if result.article is not None:
            title = result.article.title
        elif result.video is not None:
            title = result.video.title

        ents = analysis.extracted_entities.model_dump()
        technologies = ents.get("technologies") or []

        now = datetime.now(timezone.utc)
        meta: dict[str, Any] = {
            "url": url,
            "source_type": result.source_type.value,
            "title": title or "",
            "category": analysis.suggested_category,
            "is_uncertain": bool(analysis.is_uncertain),
            "alternative_categories": "|".join(analysis.alternative_categories),
            "summary": analysis.summary_one_liner,
            "key_insights": json.dumps(analysis.key_insights, ensure_ascii=False),
            "price": ents.get("price") or "",
            "location": ents.get("location") or "",
            "technologies": "|".join(technologies) if technologies else "",
            "entities_json": json.dumps(ents, ensure_ascii=False),
            "status": result.status or STATUS_COMPLETED,
            "ingested_at": now.isoformat(timespec="seconds"),
            "created_at": int(now.timestamp()),
        }
        # Chroma metadata rejects None — coerce any None we may have missed.
        return {k: (v if v is not None else "") for k, v in meta.items()}

    @staticmethod
    def _hydrate_query(res: dict[str, Any]) -> list[SearchHit]:
        """Flatten Chroma's nested query() result into typed SearchHits."""
        if not res:
            return []
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[None] * len(ids)])[0]

        hits: list[SearchHit] = []
        for i, _id in enumerate(ids):
            meta = (metas[i] if i < len(metas) else {}) or {}
            hits.append(
                SearchHit(
                    url=meta.get("url") or _id,
                    distance=float(dists[i]) if i < len(dists) and dists[i] is not None else None,
                    document=docs[i] if i < len(docs) else "",
                    category=meta.get("category"),
                    summary=meta.get("summary"),
                    metadata=dict(meta),
                )
            )
        return hits
