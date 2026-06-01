"""Top-level dispatch — given a URL, return a populated `IngestionResult`."""

from __future__ import annotations

from src.analyzers import LLMAnalyzer
from src.extractors import ArticleExtractor, VideoExtractor
from src.logger import get_logger
from src.schemas import (
    AnalysisResult,
    ArticleResult,
    ExtractedEntities,
    IngestionResult,
    SourceType,
)
from src.storage import VectorStoreManager
from src.utils.url_classifier import classify

logger = get_logger(__name__)


class IngestionOrchestrator:
    """Single entry-point used by the CLI today and the FastAPI route later.

    Wiring policy:
      - extractors and the LLM analyzer are always built (lazily for the LLM
        and store to avoid paying their startup cost when the caller opts out)
      - when `analyze=True` and the caller does not pass `existing_categories`,
        we auto-pull the user's accepted categories from the vector store so
        the LLM prefers reusing them over inventing near-duplicates
      - when `store=True` and the run produced an `AnalysisResult`, the result
        is upserted into the vector store keyed by URL
    """

    def __init__(
        self,
        article_extractor: ArticleExtractor | None = None,
        video_extractor: VideoExtractor | None = None,
        llm_analyzer: LLMAnalyzer | None = None,
        vector_store: VectorStoreManager | None = None,
    ) -> None:
        self._article = article_extractor or ArticleExtractor()
        self._video = video_extractor or VideoExtractor()
        self._llm: LLMAnalyzer | None = llm_analyzer
        self._store: VectorStoreManager | None = vector_store

    def ingest(
        self,
        url: str,
        *,
        analyze: bool = True,
        store: bool = True,
        existing_categories: list[str] | None = None,
    ) -> IngestionResult:
        logger.info("Ingesting %s (analyze=%s store=%s)", url, analyze, store)
        source_type = classify(url)

        if source_type is SourceType.VIDEO:
            video = self._video.extract(url)
            result = IngestionResult(url=url, source_type=source_type, video=video)
        elif source_type is SourceType.ARTICLE:
            article = self._article.extract(url)
            result = IngestionResult(url=url, source_type=source_type, article=article)
        else:
            return IngestionResult(
                url=url,
                source_type=SourceType.UNKNOWN,
                error=f"Could not classify URL: {url}",
            )

        if analyze:
            cats = existing_categories
            if cats is None and store:
                cats = self._get_or_make_store().get_all_categories()
                if cats:
                    logger.info("Auto-fed %d existing categories to LLM: %s", len(cats), cats)
            result.analysis = self._get_or_make_llm().analyze(
                result, existing_categories=cats,
            )

        if store and result.analysis is not None:
            self._get_or_make_store().add_item(url, result)

        return result

    # =============================================== async / background API
    def create_placeholder(
        self,
        url: str,
        source_type: SourceType,
        *,
        store: bool = True,
    ) -> IngestionResult:
        """Build the `IngestionResult` we return from `POST /api/ingest`
        immediately (status="processing") and, when `store=True`, persist a
        placeholder row in the vector store so the iOS client sees the item
        right away. The full pipeline runs separately via
        `process_in_background`.
        """
        if store:
            self._get_or_make_store().add_placeholder(url, source_type)
        return IngestionResult(
            url=url,
            source_type=source_type,
            status="processing",
        )

    def process_in_background(
        self,
        url: str,
        *,
        analyze: bool = True,
        store: bool = True,
        existing_categories: list[str] | None = None,
    ) -> None:
        """The heavy pipeline. Designed to run inside FastAPI's
        `BackgroundTasks` after a 202 has already been returned.

        **Invariant**: this function NEVER returns leaving a row in
        `status="processing"`. The placeholder must transition to either
        `completed` (success) or `failed` (anything else) before we
        unwind. Three concentric layers guarantee that:

          1. Hard-fail cases (classify=UNKNOWN, extraction error,
             empty aggregated_text, missing analysis) explicitly call
             `mark_failed` before returning.
          2. An outer `except BaseException` catches anything the
             pipeline raises (network timeouts, yt-dlp crashes,
             Ollama disconnects, KeyboardInterrupt, etc.) and routes
             it through `mark_failed`.
          3. A `finally` guard double-checks the row's status one more
             time and force-flips any leftover `processing` row to
             `failed` — covers the "we somehow returned without
             marking" class of bug that caused FB items to hang.
        """
        completed = False
        try:
            try:
                result = self.ingest(
                    url,
                    analyze=analyze,
                    store=store,
                    existing_categories=existing_categories,
                )
            except BaseException as exc:
                self._mark_failed_safely(url, store, f"{type(exc).__name__}: {exc}")
                logger.exception("Background ingest raised for %s", url)
                return

            # ----- Hard-fail cases reported via the result envelope -----
            if result.source_type is SourceType.UNKNOWN or result.error:
                reason = result.error or f"unsupported_source_type:{result.source_type.value}"
                self._mark_failed_safely(url, store, reason)
                logger.warning("Background ingest soft-failed for %s: %s", url, reason)
                return

            # The extractor's own metadata.error (e.g. yt_dlp_failed)
            # doesn't raise to the orchestrator. Surface it explicitly.
            extractor_error = (
                (result.video and result.video.metadata.get("error"))
                or (result.article and result.article.metadata.get("error"))
            )
            if extractor_error:
                self._mark_failed_safely(url, store, f"extractor:{extractor_error}")
                logger.warning("Background ingest extractor error for %s: %s", url, extractor_error)
                return

            # Empty content — yt-dlp / trafilatura returned nothing
            # usable. Without this check, add_item silently refuses
            # and the placeholder stays in `processing` forever.
            if not result.aggregated_text.strip():
                self._mark_failed_safely(url, store, "extraction returned no content")
                logger.warning("Background ingest produced empty text for %s", url)
                return

            # Analysis was requested but didn't attach — LLM failure.
            if analyze and result.analysis is None:
                self._mark_failed_safely(url, store, "analysis_missing")
                logger.warning("Background ingest missing analysis for %s", url)
                return

            # ----- Happy path -----
            cat = result.analysis.suggested_category if result.analysis else "(no analysis)"
            logger.info("Background ingest done for %s → category=%s", url, cat)
            completed = True

        except BaseException as exc:
            # Last-ditch — should be unreachable if the inner handlers ran.
            self._mark_failed_safely(url, store, f"{type(exc).__name__}: {exc}")
            logger.exception("Outer guard fired for %s", url)
        finally:
            # Backstop invariant: if we somehow exited without either
            # completing or failing the row, flip it to failed here so
            # the iOS UI never shows a stuck-forever placeholder.
            if not completed and store:
                self._force_fail_if_still_processing(url)

    # ---------------------------------------------------------------- helpers
    def _mark_failed_safely(self, url: str, store: bool, reason: str) -> None:
        if not store:
            return
        try:
            self._get_or_make_store().mark_failed(url, reason)
        except Exception:
            logger.exception("mark_failed itself raised for %s", url)

    def _force_fail_if_still_processing(self, url: str) -> None:
        try:
            hit = self._get_or_make_store().get_by_url(url)
        except Exception:
            logger.exception("get_by_url failed in finally guard for %s", url)
            return
        if hit is not None and hit.metadata.get("status") == "processing":
            logger.warning(
                "Finally-guard tripped for %s — row still in 'processing'; force-failing.",
                url,
            )
            self._mark_failed_safely(url, True, "pipeline ended without completion")

    # -------- search / metadata pass-throughs so the CLI does not need to
    # know about the storage module directly.
    def search(self, query: str, limit: int = 5, category: str | None = None):
        return self._get_or_make_store().search_items(query, limit=limit, category=category)

    def list_categories(self) -> list[str]:
        return self._get_or_make_store().get_all_categories()

    def create_manual_item(
        self,
        url: str,
        *,
        title: str,
        summary: str,
        category: str,
    ) -> IngestionResult:
        """Insert a fully-specified item directly into the vector store,
        bypassing the extractor + LLM analyzer entirely.

        Used by the iOS "+" button when the user wants to add a saved
        link by hand — typically because the source is behind auth or
        the auto-extract pipeline isn't going to give a clean result.

        The row lands at `status="completed"` immediately. The embedded
        document is `title + summary` so it's searchable; the metadata
        carries the user-chosen category as-is (no LLM "uncertain"
        smoothing — the user already decided).
        """
        # Classify the URL anyway so the row's source_type metadata is
        # accurate ("article" vs "video"). UNKNOWN URLs default to
        # ARTICLE because the user explicitly chose to save this thing.
        source_type = classify(url)
        if source_type is SourceType.UNKNOWN:
            source_type = SourceType.ARTICLE

        # Build the synthetic envelope. `text` carries the summary so
        # aggregated_text is non-empty (add_item refuses empty rows).
        body = summary.strip() or title.strip()
        article = ArticleResult(
            url=url,
            title=title.strip(),
            text=body,
            word_count=len(body.split()),
        )
        analysis = AnalysisResult(
            suggested_category=category.strip(),
            is_uncertain=False,
            alternative_categories=[],
            summary_one_liner=summary.strip() or title.strip(),
            key_insights=[],
            extracted_entities=ExtractedEntities(),
        )
        result = IngestionResult(
            url=url,
            source_type=source_type,
            article=article,
            analysis=analysis,
            status="completed",
        )
        self._get_or_make_store().add_item(url, result)
        logger.info(
            "Manual item created: url=%s category=%r title=%r",
            url, category, title,
        )
        return result

    def delete_item(self, url: str) -> bool:
        return self._get_or_make_store().delete_item(url)

    def update_item(
        self,
        url: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        category: str | None = None,
    ):
        return self._get_or_make_store().update_item(
            url, title=title, summary=summary, category=category,
        )

    def rename_category(self, old_name: str, new_name: str) -> int:
        return self._get_or_make_store().rename_category(old_name, new_name)

    def delete_category(self, name: str) -> int:
        return self._get_or_make_store().delete_category(name)

    # ----------------------------------------------------------------- internals
    def _get_or_make_llm(self) -> LLMAnalyzer:
        if self._llm is None:
            self._llm = LLMAnalyzer()
        return self._llm

    def _get_or_make_store(self) -> VectorStoreManager:
        if self._store is None:
            self._store = VectorStoreManager()
        return self._store
