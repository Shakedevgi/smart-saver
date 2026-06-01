"""FastAPI server — thin REST layer over `IngestionOrchestrator`.

Run locally:
    uvicorn src.api.main:app --reload
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000   # physical iOS device

Lifecycle:
    A single `IngestionOrchestrator` is built in the lifespan handler and
    reused across requests. Its internal `LLMAnalyzer` and
    `VectorStoreManager` are themselves lazy, so the Chroma collection and
    Ollama HTTP session are opened on first use, not at import time.

Tests:
    `tests/test_smoke.py` overrides the `get_orchestrator` dependency to
    inject a tempdir-backed store and a fake LLM, so the test client never
    needs the Ollama daemon or the network.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.config import settings
from src.logger import get_logger
from src.orchestrator import IngestionOrchestrator
from src.schemas import IngestionResult, SearchHit, SourceType
from src.utils.url_classifier import classify, sanitize_url

logger = get_logger(__name__)


# =================================================== request / response models
class IngestRequest(BaseModel):
    url: str = Field(..., description="The URL of an article or video to ingest.")
    analyze: bool = Field(True, description="Run the LLM analyzer after extraction.")
    store: bool = Field(True, description="Persist the result to the vector store.")
    existing_categories: list[str] | None = Field(
        default=None,
        description=(
            "Override the auto-pulled list of accepted categories. "
            "When None, the orchestrator reads them from the vector store."
        ),
    )


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural-language search query.")
    # Cap is generous: the iOS "All" tile asks for up to 200 in one shot to
    # render the whole library on a single screen. 50 was too tight.
    limit: int = Field(5, ge=1, le=200, description="Maximum number of hits.")
    category: str | None = Field(None, description="Restrict the search to one category.")


class SearchResponse(BaseModel):
    query: str
    category: str | None = None
    hits: list[SearchHit]


class CategoriesResponse(BaseModel):
    categories: list[str]


class HealthResponse(BaseModel):
    status: str = "ok"
    items_indexed: int


class ManualItemRequest(BaseModel):
    """Body for `POST /api/items` — used by the iOS "Add manually"
    sheet. Bypasses extractor + LLM and lands directly as a completed
    row."""
    url: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, description="Required — used as the row title.")
    summary: str = Field(default="", description="Optional — used as the body text and embedded for search.")
    category: str = Field(..., min_length=1)


class DeleteItemRequest(BaseModel):
    url: str = Field(..., min_length=1)


class DeleteItemResponse(BaseModel):
    url: str
    deleted: bool


class UpdateItemRequest(BaseModel):
    url: str = Field(..., min_length=1)
    title: str | None = Field(None, description="New title (omit to leave unchanged).")
    summary: str | None = Field(None, description="New summary (omit to leave unchanged).")
    category: str | None = Field(None, description="New category (omit to leave unchanged).")


class UpdateItemResponse(BaseModel):
    url: str
    updated: bool
    item: SearchHit | None = None


class RenameCategoryRequest(BaseModel):
    old_name: str = Field(..., min_length=1)
    new_name: str = Field(..., min_length=1)


class DeleteCategoryRequest(BaseModel):
    name: str = Field(..., min_length=1)


class CategoryBulkResponse(BaseModel):
    affected: int


# ================================================== orchestrator singleton + DI
_orchestrator: IngestionOrchestrator | None = None


def get_orchestrator() -> IngestionOrchestrator:
    """FastAPI dependency. Tests override this with a fixture-built instance."""
    if _orchestrator is None:
        # Defensive — lifespan should have populated this. Build on demand so
        # ad-hoc `from src.api.main import app` usage still works.
        logger.warning("Orchestrator not built by lifespan — building lazily.")
        return IngestionOrchestrator()
    return _orchestrator


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _orchestrator
    logger.info("API starting up — constructing IngestionOrchestrator")
    _orchestrator = IngestionOrchestrator()
    try:
        yield
    finally:
        logger.info("API shutting down")
        _orchestrator = None


# ============================================================== app factory
def build_app() -> FastAPI:
    """Factory so tests can spin up a fresh app per fixture if they need to."""
    app = FastAPI(
        title="Smart Saver API",
        description="Local-first ingestion + semantic search over saved links.",
        version="0.4.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        # `allow_credentials=True` is invalid alongside allow_origins=["*"] per
        # the CORS spec — browsers reject the response. iOS doesn't enforce
        # CORS, but keeping it correct lets the same server be hit from a
        # browser dev page if needed.
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # =============================================================== routes
    @app.get("/api/health", response_model=HealthResponse, tags=["meta"])
    def health(orch: IngestionOrchestrator = Depends(get_orchestrator)) -> HealthResponse:
        try:
            count = orch._get_or_make_store().count()
        except Exception:
            logger.exception("Health check failed to read store count")
            count = 0
        return HealthResponse(status="ok", items_indexed=count)

    @app.post(
        "/api/ingest",
        response_model=IngestionResult,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["ingest"],
        responses={
            202: {"description": "Placeholder stored; background pipeline scheduled."},
            400: {"description": "URL could not be classified."},
        },
    )
    def ingest(
        req: IngestRequest,
        background_tasks: BackgroundTasks,
        orch: IngestionOrchestrator = Depends(get_orchestrator),
    ) -> IngestionResult:
        """Non-blocking ingest.

        Flow:
          1. Validate the URL (400 fast-fail if the classifier rejects it).
          2. Persist a placeholder row + return a 202 with the placeholder
             JSON. The Share Extension uses this to dismiss in <1 s.
          3. The heavy yt-dlp → Whisper → EasyOCR → Ollama pipeline runs
             AFTER the response, via FastAPI's `BackgroundTasks`. On
             completion the placeholder is upserted with full data; on
             failure it is marked as "failed" via `mark_failed`.

        The iOS dashboard reflects the lifecycle through the new
        `metadata.status` field.
        """
        # Canonicalize once at the boundary: strip share-sheet tracking
        # params so this row de-dupes against any prior ingest of the
        # same content from a different surface (FB Mobile vs Web,
        # iOS share, copied-link, etc.).
        url = sanitize_url(req.url.strip())
        if not url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="`url` must be a non-empty string.",
            )

        source_type = classify(url)
        if source_type is SourceType.UNKNOWN:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not classify URL: {url}",
            )

        try:
            placeholder = orch.create_placeholder(url, source_type, store=req.store)
        except Exception as exc:
            logger.exception("Placeholder write failed for %s", url)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not stage placeholder: {type(exc).__name__}: {exc}",
            ) from exc

        background_tasks.add_task(
            orch.process_in_background,
            url,
            analyze=req.analyze,
            store=req.store,
            existing_categories=req.existing_categories,
        )
        logger.info("202 Accepted — background pipeline scheduled for %s", url)
        return placeholder

    @app.post("/api/search", response_model=SearchResponse, tags=["search"])
    def search(
        req: SearchRequest,
        orch: IngestionOrchestrator = Depends(get_orchestrator),
    ) -> SearchResponse:
        try:
            hits = orch.search(req.query, limit=req.limit, category=req.category)
        except Exception as exc:
            logger.exception("Search failed for query=%r", req.query)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Search failure: {type(exc).__name__}: {exc}",
            ) from exc
        return SearchResponse(query=req.query, category=req.category, hits=hits)

    @app.get("/api/categories", response_model=CategoriesResponse, tags=["search"])
    def categories(
        orch: IngestionOrchestrator = Depends(get_orchestrator),
    ) -> CategoriesResponse:
        try:
            cats = orch.list_categories()
        except Exception as exc:
            logger.exception("list_categories failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Store failure: {type(exc).__name__}: {exc}",
            ) from exc
        return CategoriesResponse(categories=cats)

    # ===================================================== item management
    @app.post(
        "/api/items",
        response_model=IngestionResult,
        status_code=status.HTTP_201_CREATED,
        tags=["items"],
        responses={400: {"description": "Empty url / title / category."}},
    )
    def create_item(
        req: ManualItemRequest,
        orch: IngestionOrchestrator = Depends(get_orchestrator),
    ) -> IngestionResult:
        """Insert a fully-specified item without invoking the extractor
        or LLM. Used by the iOS "Add manually" sheet."""
        url = sanitize_url(req.url.strip())
        title = req.title.strip()
        category = req.category.strip()
        if not url or not title or not category:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="url, title, and category must all be non-empty.",
            )
        try:
            return orch.create_manual_item(
                url, title=title, summary=req.summary, category=category,
            )
        except Exception as exc:
            logger.exception("Manual item creation crashed for %s", url)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Insert failure: {type(exc).__name__}: {exc}",
            ) from exc

    @app.delete(
        "/api/items",
        response_model=DeleteItemResponse,
        tags=["items"],
        responses={404: {"description": "URL not found in store."}},
    )
    def delete_item(
        req: DeleteItemRequest,
        orch: IngestionOrchestrator = Depends(get_orchestrator),
    ) -> DeleteItemResponse:
        try:
            ok = orch.delete_item(req.url)
        except Exception as exc:
            logger.exception("delete_item crashed for %s", req.url)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Delete failure: {type(exc).__name__}: {exc}",
            ) from exc
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No item found for url={req.url!r}",
            )
        return DeleteItemResponse(url=req.url, deleted=True)

    @app.patch(
        "/api/items",
        response_model=UpdateItemResponse,
        tags=["items"],
        responses={
            404: {"description": "URL not found in store."},
            400: {"description": "No fields to update were provided."},
        },
    )
    def patch_item(
        req: UpdateItemRequest,
        orch: IngestionOrchestrator = Depends(get_orchestrator),
    ) -> UpdateItemResponse:
        if req.title is None and req.summary is None and req.category is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide at least one of: title, summary, category.",
            )
        try:
            updated = orch.update_item(
                req.url,
                title=req.title,
                summary=req.summary,
                category=req.category,
            )
        except Exception as exc:
            logger.exception("update_item crashed for %s", req.url)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Update failure: {type(exc).__name__}: {exc}",
            ) from exc
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No item found for url={req.url!r}",
            )
        return UpdateItemResponse(url=req.url, updated=True, item=updated)

    # ================================================ category management
    @app.patch(
        "/api/categories",
        response_model=CategoryBulkResponse,
        tags=["categories"],
        responses={400: {"description": "old_name and new_name must differ."}},
    )
    def rename_category(
        req: RenameCategoryRequest,
        orch: IngestionOrchestrator = Depends(get_orchestrator),
    ) -> CategoryBulkResponse:
        if req.old_name == req.new_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="old_name and new_name must differ.",
            )
        try:
            n = orch.rename_category(req.old_name, req.new_name)
        except Exception as exc:
            logger.exception("rename_category crashed (%r → %r)", req.old_name, req.new_name)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Rename failure: {type(exc).__name__}: {exc}",
            ) from exc
        return CategoryBulkResponse(affected=n)

    @app.delete(
        "/api/categories",
        response_model=CategoryBulkResponse,
        tags=["categories"],
    )
    def delete_category(
        req: DeleteCategoryRequest,
        orch: IngestionOrchestrator = Depends(get_orchestrator),
    ) -> CategoryBulkResponse:
        try:
            n = orch.delete_category(req.name)
        except Exception as exc:
            logger.exception("delete_category crashed for %r", req.name)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Delete failure: {type(exc).__name__}: {exc}",
            ) from exc
        return CategoryBulkResponse(affected=n)

    # Quiet uvicorn's per-request access log without losing app-level logs.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    return app


# Importable singleton for `uvicorn src.api.main:app`
app = build_app()
