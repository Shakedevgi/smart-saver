"""Persistent vector storage.

Two backends share the same public API:

  Supabase pgvector (production)
    Used when `path` is NOT given.  Reads SMART_SAVER_SUPABASE_* and
    SMART_SAVER_GEMINI_API_KEY from settings.  Embeddings via Gemini
    gemini-embedding-001 (768-dim), stored in a pgvector column.

  ChromaDB (test / legacy)
    Used when `path` IS given (smoke tests pass a tempdir).  Keeps all
    existing test assertions green without needing Supabase credentials.

Both imports are lazy so the production Docker image doesn't need
chromadb installed, and CI doesn't need the supabase package.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import settings
from src.logger import get_logger
from src.schemas import IngestionResult, SearchHit, SourceType

logger = get_logger(__name__)

STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


class VectorStoreManager:
    """Dual-backend vector store (Supabase pgvector or ChromaDB)."""

    def __init__(
        self,
        path: str | Path | None = None,
        collection_name: str | None = None,
        embedding_backend: str | None = None,
    ) -> None:
        self._use_supabase = path is None
        if self._use_supabase:
            self._init_supabase()
        else:
            self._init_chroma(path, collection_name, embedding_backend)

    # ================================================================ init
    def _init_supabase(self) -> None:
        from supabase import create_client

        self._sb = create_client(settings.supabase_url, settings.supabase_key)
        logger.info("VectorStoreManager: Supabase backend at %s", settings.supabase_url)

    def _init_chroma(
        self,
        path: str | Path | None,
        collection_name: str | None,
        embedding_backend: str | None,
    ) -> None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        from chromadb.utils import embedding_functions as ef

        self._chroma_path = Path(path) if path else settings.chroma_path
        self._chroma_path.mkdir(parents=True, exist_ok=True)
        self._collection_name = collection_name or settings.chroma_collection
        self._embedding_backend = embedding_backend or settings.embedding_backend

        logger.info(
            "VectorStoreManager: ChromaDB backend path=%s collection=%s",
            self._chroma_path, self._collection_name,
        )
        self._chroma_client = chromadb.PersistentClient(
            path=str(self._chroma_path),
            settings=ChromaSettings(
                anonymized_telemetry=settings.chroma_telemetry,
                allow_reset=True,
            ),
        )
        embedder = self._build_chroma_embedder(self._embedding_backend, ef)
        self._chroma_col = self._chroma_client.get_or_create_collection(
            name=self._collection_name,
            embedding_function=embedder,
            metadata={"hnsw:space": "cosine"},
        )

    # ============================================================ write path
    def add_item(self, url: str, ingestion_result: IngestionResult) -> bool:
        if self._use_supabase:
            return self._sb_add_item(url, ingestion_result)
        return self._chroma_add_item(url, ingestion_result)

    def add_placeholder(self, url: str, source_type: SourceType) -> bool:
        if self._use_supabase:
            return self._sb_add_placeholder(url, source_type)
        return self._chroma_add_placeholder(url, source_type)

    def delete_item(self, url: str) -> bool:
        if self._use_supabase:
            return self._sb_delete_item(url)
        return self._chroma_delete_item(url)

    def update_item(
        self,
        url: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        category: str | None = None,
    ) -> SearchHit | None:
        if self._use_supabase:
            return self._sb_update_item(url, title=title, summary=summary, category=category)
        return self._chroma_update_item(url, title=title, summary=summary, category=category)

    def rename_category(self, old_name: str, new_name: str) -> int:
        if self._use_supabase:
            return self._sb_rename_category(old_name, new_name)
        return self._chroma_rename_category(old_name, new_name)

    def delete_category(self, name: str) -> int:
        if self._use_supabase:
            return self._sb_delete_category(name)
        return self._chroma_delete_category(name)

    def update_status(self, url: str, status: str) -> bool:
        if self._use_supabase:
            return self._sb_update_status(url, status)
        return self._chroma_update_status(url, status)

    def mark_failed(self, url: str, error: str) -> bool:
        if self._use_supabase:
            return self._sb_mark_failed(url, error)
        return self._chroma_mark_failed(url, error)

    # ============================================================ read path
    def search_items(
        self,
        query: str,
        limit: int = 5,
        category: str | None = None,
    ) -> list[SearchHit]:
        if self._use_supabase:
            return self._sb_search_items(query, limit, category)
        return self._chroma_search_items(query, limit, category)

    def get_all_categories(self) -> list[str]:
        if self._use_supabase:
            return self._sb_get_all_categories()
        return self._chroma_get_all_categories()

    def get_by_url(self, url: str) -> SearchHit | None:
        if self._use_supabase:
            return self._sb_get_by_url(url)
        return self._chroma_get_by_url(url)

    def count(self) -> int:
        if self._use_supabase:
            return self._sb_count()
        return self._chroma_count()

    # =========================================================== supabase impl
    def _embed(self, text: str) -> list[float]:
        import time
        import httpx
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent"
        headers = {"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"}
        payload = {
            "model": "models/gemini-embedding-001",
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": 768,
        }
        for attempt in range(3):
            resp = httpx.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 429 and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()["embedding"]["values"]
        resp.raise_for_status()  # unreachable but satisfies type checker

    def _sb_add_item(self, url: str, result: IngestionResult) -> bool:
        text = result.aggregated_text
        if not text.strip():
            logger.warning("Refusing to store %s — no aggregated text.", url)
            return False
        if result.analysis is None:
            logger.warning("Refusing to store %s — no analysis attached.", url)
            return False

        try:
            embedding = self._embed(text)
            data = self._build_sb_row(url, result, embedding=embedding)
            self._sb.table("items").upsert(data).execute()
        except Exception:
            logger.exception("Supabase upsert failed for %s", url)
            return False

        logger.info("Stored %s → category=%r status=%s", url, data["category"], data["status"])
        return True

    def _sb_add_placeholder(self, url: str, source_type: SourceType) -> bool:
        now = datetime.now(timezone.utc)
        data = {
            "url": url,
            "document": url,
            "embedding": None,  # filled in when pipeline completes
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
            self._sb.table("items").upsert(data).execute()
        except Exception:
            logger.exception("Supabase placeholder upsert failed for %s", url)
            return False
        logger.info("Placeholder stored %s", url)
        return True

    def _sb_delete_item(self, url: str) -> bool:
        try:
            existing = self._sb.table("items").select("url").eq("url", url).execute()
            if not existing.data:
                return False
            self._sb.table("items").delete().eq("url", url).execute()
        except Exception:
            logger.exception("Supabase delete failed for %s", url)
            return False
        logger.info("Deleted %s", url)
        return True

    def _sb_update_item(
        self,
        url: str,
        *,
        title: str | None,
        summary: str | None,
        category: str | None,
    ) -> SearchHit | None:
        try:
            existing = self._sb.table("items").select("*").eq("url", url).execute()
            if not existing.data:
                return None
            updates: dict[str, Any] = {}
            if title is not None:
                updates["title"] = title
            if summary is not None:
                updates["summary"] = summary
            if category is not None:
                updates["category"] = category
            if updates:
                self._sb.table("items").update(updates).eq("url", url).execute()
            row = existing.data[0]
            row.update(updates)
        except Exception:
            logger.exception("Supabase update_item failed for %s", url)
            return None
        return self._sb_row_to_hit(row)

    def _sb_rename_category(self, old_name: str, new_name: str) -> int:
        if not old_name or not new_name or old_name == new_name:
            return 0
        try:
            existing = self._sb.table("items").select("url").eq("category", old_name).execute()
            count = len(existing.data)
            if not count:
                return 0
            self._sb.table("items").update({"category": new_name}).eq("category", old_name).execute()
        except Exception:
            logger.exception("Supabase rename_category failed (%r → %r)", old_name, new_name)
            return 0
        logger.info("Renamed category %r → %r across %d items", old_name, new_name, count)
        return count

    def _sb_delete_category(self, name: str) -> int:
        if not name:
            return 0
        try:
            existing = self._sb.table("items").select("url").eq("category", name).execute()
            count = len(existing.data)
            if not count:
                return 0
            self._sb.table("items").delete().eq("category", name).execute()
        except Exception:
            logger.exception("Supabase delete_category failed for %r", name)
            return 0
        logger.info("Deleted category %r — %d items removed", name, count)
        return count

    def _sb_update_status(self, url: str, status: str) -> bool:
        try:
            existing = self._sb.table("items").select("url").eq("url", url).execute()
            if not existing.data:
                logger.debug("update_status: no row yet for %s — skipping", url)
                return False
            self._sb.table("items").update({"status": status}).eq("url", url).execute()
        except Exception:
            logger.exception("Supabase update_status failed for %s", url)
            return False
        logger.debug("Status %s → %r", url, status)
        return True

    def _sb_mark_failed(self, url: str, error: str) -> bool:
        try:
            existing = self._sb.table("items").select("url").eq("url", url).execute()
            if not existing.data:
                logger.warning("mark_failed: no existing row for %s", url)
                return False
            snippet = (error or "")[:200]
            self._sb.table("items").update({
                "status": STATUS_FAILED,
                "summary": f"Couldn't process: {snippet}" if snippet else "Couldn't process this item.",
            }).eq("url", url).execute()
        except Exception:
            logger.exception("Supabase mark_failed update failed for %s", url)
            return False
        logger.warning("Marked %s as failed: %s", url, (error or "")[:100])
        return True

    def _sb_search_items(
        self,
        query: str,
        limit: int,
        category: str | None,
    ) -> list[SearchHit]:
        if not query.strip():
            return []

        # "everything" = browse-all; skip embedding and fetch directly.
        if query.strip().lower() == "everything":
            return self._sb_browse_all(limit, category)

        try:
            embedding = self._embed(query)
            resp = self._sb.rpc("match_items", {
                "query_embedding": embedding,
                "match_count": limit,
                "filter_category": category,
            }).execute()
            hits = [self._sb_row_to_hit(row) for row in (resp.data or [])]
        except Exception:
            logger.exception("Supabase search failed (query=%r)", query)
            return []

        if category is not None:
            return hits
        return [h for h in hits if h.distance is None or h.distance < settings.search_distance_threshold]

    def _sb_browse_all(self, limit: int, category: str | None) -> list[SearchHit]:
        try:
            q = self._sb.table("items").select("*").neq("status", STATUS_PROCESSING).limit(limit)
            if category:
                q = q.eq("category", category)
            resp = q.execute()
            return [self._sb_row_to_hit(row) for row in (resp.data or [])]
        except Exception:
            logger.exception("Supabase browse_all failed")
            return []

    def _sb_get_all_categories(self) -> list[str]:
        try:
            resp = self._sb.table("items").select("category, status").execute()
        except Exception:
            logger.exception("Supabase get_all_categories failed")
            return []
        seen: set[str] = set()
        for row in resp.data or []:
            if row.get("status") == STATUS_PROCESSING:
                continue
            cat = row.get("category")
            if isinstance(cat, str) and cat and cat != "Processing":
                seen.add(cat)
        return sorted(seen)

    def _sb_get_by_url(self, url: str) -> SearchHit | None:
        try:
            resp = self._sb.table("items").select("*").eq("url", url).execute()
        except Exception:
            logger.exception("Supabase get_by_url failed for %s", url)
            return None
        if not resp.data:
            return None
        return self._sb_row_to_hit(resp.data[0])

    def _sb_count(self) -> int:
        try:
            resp = self._sb.table("items").select("url", count="exact").execute()
            return resp.count or 0
        except Exception:
            logger.exception("Supabase count() failed")
            return 0

    @staticmethod
    def _sb_row_to_hit(row: dict[str, Any]) -> SearchHit:
        return SearchHit(
            url=row.get("url", ""),
            distance=row.get("distance"),
            document=row.get("document", ""),
            category=row.get("category"),
            summary=row.get("summary"),
            metadata={k: v for k, v in row.items() if k not in ("embedding", "distance")},
        )

    def _build_sb_row(
        self, url: str, result: IngestionResult, embedding: list[float]
    ) -> dict[str, Any]:
        analysis = result.analysis
        assert analysis is not None

        title: str | None = None
        if result.article is not None:
            title = result.article.title
        elif result.video is not None:
            title = result.video.title

        ents = analysis.extracted_entities.model_dump()
        technologies = ents.get("technologies") or []
        now = datetime.now(timezone.utc)

        return {
            "url": url,
            "document": result.aggregated_text,
            "embedding": embedding,
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

    # =========================================================== chromadb impl
    def _chroma_add_item(self, url: str, ingestion_result: IngestionResult) -> bool:
        text = ingestion_result.aggregated_text
        if not text.strip():
            logger.warning("Refusing to store %s — no aggregated text.", url)
            return False
        if ingestion_result.analysis is None:
            logger.warning("Refusing to store %s — no analysis attached.", url)
            return False

        metadata = self._build_chroma_metadata(url, ingestion_result)
        try:
            self._chroma_col.upsert(ids=[url], documents=[text], metadatas=[metadata])
        except Exception:
            logger.exception("Chroma upsert failed for %s", url)
            return False
        logger.info("Stored %s → category=%r status=%s", url, metadata.get("category"), metadata.get("status"))
        return True

    def _chroma_add_placeholder(self, url: str, source_type: SourceType) -> bool:
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
            self._chroma_col.upsert(ids=[url], documents=[url], metadatas=[metadata])
        except Exception:
            logger.exception("Chroma placeholder upsert failed for %s", url)
            return False
        logger.info("Placeholder stored %s (count now %d)", url, self.count())
        return True

    def _chroma_delete_item(self, url: str) -> bool:
        try:
            existing = self._chroma_col.get(ids=[url])
        except Exception:
            logger.exception("delete_item could not read %s", url)
            return False
        if not (existing.get("ids") or []):
            return False
        try:
            self._chroma_col.delete(ids=[url])
        except Exception:
            logger.exception("Chroma delete failed for %s", url)
            return False
        logger.info("Deleted %s", url)
        return True

    def _chroma_update_item(
        self,
        url: str,
        *,
        title: str | None,
        summary: str | None,
        category: str | None,
    ) -> SearchHit | None:
        try:
            existing = self._chroma_col.get(ids=[url], include=["metadatas", "documents"])
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
            self._chroma_col.update(ids=[url], metadatas=[meta])
        except Exception:
            logger.exception("Chroma update failed for %s", url)
            return None
        doc = (existing.get("documents") or [""])[0] or ""
        return SearchHit(url=url, document=doc, category=meta.get("category"), summary=meta.get("summary"), metadata=dict(meta))

    def _chroma_rename_category(self, old_name: str, new_name: str) -> int:
        if not old_name or not new_name or old_name == new_name:
            return 0
        try:
            res = self._chroma_col.get(where={"category": old_name}, include=["metadatas"])
        except Exception:
            logger.exception("rename_category lookup failed for %r", old_name)
            return 0
        ids = res.get("ids") or []
        if not ids:
            return 0
        new_metas = [{**dict(m or {}), "category": new_name} for m in (res.get("metadatas") or [])]
        try:
            self._chroma_col.update(ids=ids, metadatas=new_metas)
        except Exception:
            logger.exception("rename_category update failed (%r → %r)", old_name, new_name)
            return 0
        logger.info("Renamed category %r → %r across %d items", old_name, new_name, len(ids))
        return len(ids)

    def _chroma_delete_category(self, name: str) -> int:
        if not name:
            return 0
        try:
            res = self._chroma_col.get(where={"category": name})
        except Exception:
            logger.exception("delete_category lookup failed for %r", name)
            return 0
        ids = res.get("ids") or []
        if not ids:
            return 0
        try:
            self._chroma_col.delete(ids=ids)
        except Exception:
            logger.exception("delete_category delete failed for %r", name)
            return 0
        logger.info("Deleted category %r — %d items removed", name, len(ids))
        return len(ids)

    def _chroma_update_status(self, url: str, status: str) -> bool:
        try:
            existing = self._chroma_col.get(ids=[url], include=["metadatas"])
        except Exception:
            logger.exception("update_status could not read %s", url)
            return False
        if not (existing.get("ids") or []):
            logger.debug("update_status: no row yet for %s — skipping", url)
            return False
        meta = (existing.get("metadatas") or [{}])[0] or {}
        meta["status"] = status
        try:
            self._chroma_col.update(ids=[url], metadatas=[meta])
        except Exception:
            logger.exception("update_status Chroma update failed for %s", url)
            return False
        logger.debug("Status %s → %r", url, status)
        return True

    def _chroma_mark_failed(self, url: str, error: str) -> bool:
        try:
            existing = self._chroma_col.get(ids=[url], include=["metadatas"])
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
            self._chroma_col.update(ids=[url], metadatas=[meta])
        except Exception:
            logger.exception("Chroma update failed for %s", url)
            return False
        logger.warning("Marked %s as failed: %s", url, snippet)
        return True

    def _chroma_search_items(
        self, query: str, limit: int, category: str | None
    ) -> list[SearchHit]:
        if not query.strip():
            return []
        where = {"category": category} if category else None
        try:
            res = self._chroma_col.query(query_texts=[query], n_results=limit, where=where)
        except Exception:
            logger.exception("Chroma query failed (query=%r)", query)
            return []
        hits = self._hydrate_chroma_query(res)
        if category is not None or query.strip().lower() == "everything":
            return hits
        return [h for h in hits if h.distance is None or h.distance < settings.search_distance_threshold]

    def _chroma_get_all_categories(self) -> list[str]:
        try:
            res = self._chroma_col.get(include=["metadatas"])
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

    def _chroma_get_by_url(self, url: str) -> SearchHit | None:
        try:
            res = self._chroma_col.get(ids=[url], include=["metadatas", "documents"])
        except Exception:
            logger.exception("Chroma get-by-url failed for %s", url)
            return None
        ids = res.get("ids") or []
        if not ids:
            return None
        meta = (res.get("metadatas") or [{}])[0] or {}
        doc = (res.get("documents") or [""])[0] or ""
        return SearchHit(url=ids[0], document=doc, category=meta.get("category"), summary=meta.get("summary"), metadata=dict(meta))

    def _chroma_count(self) -> int:
        try:
            return self._chroma_col.count()
        except Exception:
            logger.exception("Chroma count() failed")
            return 0

    def _build_chroma_metadata(self, url: str, result: IngestionResult) -> dict[str, Any]:
        analysis = result.analysis
        assert analysis is not None

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
        return {k: (v if v is not None else "") for k, v in meta.items()}

    @staticmethod
    def _hydrate_chroma_query(res: dict[str, Any]) -> list[SearchHit]:
        if not res:
            return []
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[None] * len(ids)])[0]
        hits: list[SearchHit] = []
        for i, _id in enumerate(ids):
            meta = (metas[i] if i < len(metas) else {}) or {}
            hits.append(SearchHit(
                url=meta.get("url") or _id,
                distance=float(dists[i]) if i < len(dists) and dists[i] is not None else None,
                document=docs[i] if i < len(docs) else "",
                category=meta.get("category"),
                summary=meta.get("summary"),
                metadata=dict(meta),
            ))
        return hits

    @staticmethod
    def _build_chroma_embedder(backend: str, ef: Any) -> Any:
        if (backend or "default").lower() == "ollama":
            return ef.OllamaEmbeddingFunction(
                url=settings.ollama_host,
                model_name=settings.ollama_embed_model,
            )
        return ef.DefaultEmbeddingFunction()
