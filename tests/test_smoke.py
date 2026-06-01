"""Smoke tests.

The first ~70 lines are pure-offline (no network, no ML weights). The
storage tests at the bottom hit a real ChromaDB collection in a tempdir
and use the bundled ONNX all-MiniLM-L6-v2 embedder — the first run on a
fresh machine will download ~80 MB into `~/.cache/onnx_models/`.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.schemas import (
    AnalysisResult,
    ArticleResult,
    ExtractedEntities,
    IngestionResult,
    OcrSegment,
    SearchHit,
    SourceType,
    VideoResult,
)
from src.utils.url_classifier import classify, sanitize_url


def test_url_classifier_article_default() -> None:
    assert classify("https://www.bbc.com/news/world-12345") is SourceType.ARTICLE
    assert classify("https://medium.com/@x/post-abcd") is SourceType.ARTICLE


def test_url_classifier_video_hosts() -> None:
    assert classify("https://www.youtube.com/watch?v=abc") is SourceType.VIDEO
    assert classify("https://youtu.be/abc") is SourceType.VIDEO
    assert classify("https://www.tiktok.com/@u/video/1234") is SourceType.VIDEO


def test_url_classifier_instagram_reel_is_video() -> None:
    assert classify("https://www.instagram.com/reel/abc/") is SourceType.VIDEO
    assert classify("https://instagram.com/p/abcdef/") is SourceType.VIDEO


def test_url_classifier_twitter_status_is_video() -> None:
    # Tweets often embed video; treat them as video so yt-dlp gets a shot.
    assert classify("https://x.com/user/status/123") is SourceType.VIDEO
    assert classify("https://twitter.com/user/status/123") is SourceType.VIDEO


def test_url_classifier_tiktok_all_url_shapes() -> None:
    """Step 9: every TikTok URL shape the share sheet emits must route
    to the yt-dlp video pipeline."""
    assert classify("https://www.tiktok.com/@user/video/12345") is SourceType.VIDEO
    assert classify("https://tiktok.com/@user/video/12345") is SourceType.VIDEO
    assert classify("https://m.tiktok.com/v/12345.html") is SourceType.VIDEO
    assert classify("https://vm.tiktok.com/ZS8YnAbcd/") is SourceType.VIDEO
    assert classify("https://vt.tiktok.com/ZS8YnAbcd/") is SourceType.VIDEO


def test_sanitize_url_strips_tracking_params() -> None:
    """Incoming URLs from the iOS share sheet are sanitized once at the
    API boundary; the canonical URL is what flows down to the
    orchestrator + Chroma."""
    # TikTok app deep-link with their share spam.
    raw = "https://www.tiktok.com/@user/video/12345?is_from_webapp=1&sender_device=mobile&share_app_id=1233&si=xxx"
    assert sanitize_url(raw) == "https://www.tiktok.com/@user/video/12345"

    # YouTube `si=…` strip but the meaningful `v=` survives.
    raw = "https://youtu.be/dQw4w9WgXcQ?si=somecode"
    assert sanitize_url(raw) == "https://youtu.be/dQw4w9WgXcQ"
    raw = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&si=somecode"
    assert sanitize_url(raw) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    # Generic utm_*
    raw = "https://example.com/post?utm_source=twitter&utm_medium=share"
    assert sanitize_url(raw) == "https://example.com/post"

    # No query → unchanged.
    assert sanitize_url("https://example.com/a/b") == "https://example.com/a/b"
    # Idempotent.
    once = sanitize_url("https://x.com/u/status/1?s=20&t=abc")
    assert sanitize_url(once) == once
    assert "s=20" not in once and "t=abc" not in once


def test_sanitize_url_preserves_meaningful_params() -> None:
    """Don't be over-aggressive: real content params must survive."""
    raw = "https://www.youtube.com/watch?v=12345&utm_source=spam"
    assert sanitize_url(raw) == "https://www.youtube.com/watch?v=12345"


def test_sanitize_url_strips_bare_trailing_question_mark() -> None:
    """Defensive: when *all* the query params are tracking and get
    stripped, the bare `?` separator left behind also needs to go —
    Some hosts reject the malformed `…/path/?` shape."""
    assert (
        sanitize_url("https://example.com/path/?")
        == "https://example.com/path/"
    )
    assert (
        sanitize_url("https://example.com/path/?utm_source=spam")
        == "https://example.com/path/"
    )
    # Idempotent.
    once = sanitize_url("https://example.com/path/?")
    assert sanitize_url(once) == once
    assert not once.endswith("?")


def test_url_classifier_unknown_url() -> None:
    assert classify("not-a-url") is SourceType.UNKNOWN
    assert classify("") is SourceType.UNKNOWN


def test_aggregated_text_article() -> None:
    result = IngestionResult(
        url="https://example.com/post",
        source_type=SourceType.ARTICLE,
        article=ArticleResult(
            url="https://example.com/post",
            title="Hello world",
            author="Ada",
            text="Body line one.\n\nBody line two.",
            word_count=6,
        ),
    )
    text = result.aggregated_text
    assert "# Hello world" in text
    assert "By Ada" in text
    assert "Body line one." in text


def test_aggregated_text_video_includes_all_sections() -> None:
    result = IngestionResult(
        url="https://youtube.com/watch?v=x",
        source_type=SourceType.VIDEO,
        video=VideoResult(
            url="https://youtube.com/watch?v=x",
            title="Apartment tour",
            uploader="RealtorBob",
            description="3BR in Tel Aviv, asking 4.2M",
            transcript="Welcome to this beautiful three bedroom apartment.",
            ocr_segments=[
                OcrSegment(timestamp_sec=2.0, text="4,200,000", confidence=0.9),
                OcrSegment(timestamp_sec=4.0, text="4,200,000", confidence=0.9),
                OcrSegment(timestamp_sec=6.0, text="Tel Aviv", confidence=0.8),
            ],
            ocr_text="4,200,000\nTel Aviv",
            frames_sampled=3,
        ),
    )
    text = result.aggregated_text
    assert "# Apartment tour" in text
    assert "By RealtorBob" in text
    assert "## Description / Caption" in text
    assert "3BR in Tel Aviv" in text
    assert "## Transcript" in text
    assert "Welcome to this beautiful" in text
    assert "## On-screen text" in text
    assert "4,200,000" in text


def test_analysis_result_round_trip_via_json() -> None:
    """Mimics what the LLM returns: a JSON string we round-trip into the model."""
    raw = """{
        "suggested_category": "Real Estate",
        "is_uncertain": true,
        "alternative_categories": ["Travel", "Finance"],
        "summary_one_liner": "Tour of a 3BR apartment in Tel Aviv listed at 4.2M ILS.",
        "key_insights": [
            "3 bedrooms, 95 sqm",
            "Listed at 4,200,000 ILS",
            "Walking distance to Dizengoff"
        ],
        "extracted_entities": {
            "price": "4,200,000 ILS",
            "location": "Tel Aviv",
            "technologies": [],
            "agent_phone": "+972-50-1234567"
        }
    }"""
    analysis = AnalysisResult.model_validate_json(raw)
    assert analysis.suggested_category == "Real Estate"
    assert analysis.is_uncertain is True
    assert "Travel" in analysis.alternative_categories
    assert analysis.extracted_entities.price == "4,200,000 ILS"
    assert analysis.extracted_entities.location == "Tel Aviv"
    # extra="allow" lets the LLM add ad-hoc keys without breaking the schema.
    extras = analysis.extracted_entities.model_dump()
    assert extras.get("agent_phone") == "+972-50-1234567"


def test_analysis_result_schema_has_required_fields() -> None:
    """The schema we hand to Ollama as `format=` must include both required keys."""
    schema = AnalysisResult.model_json_schema()
    required = set(schema.get("required", []))
    assert "suggested_category" in required
    assert "summary_one_liner" in required
    # And the nested ExtractedEntities schema must allow ad-hoc keys.
    ents_schema = ExtractedEntities.model_json_schema()
    assert ents_schema.get("additionalProperties") is not False


def test_ingestion_result_envelope_accepts_analysis() -> None:
    """Orchestrator returns an IngestionResult with an attached analysis."""
    result = IngestionResult(
        url="https://example.com/post",
        source_type=SourceType.ARTICLE,
        article=ArticleResult(url="https://example.com/post", title="t", text="some body"),
        analysis=AnalysisResult(
            suggested_category="Tech Tools",
            is_uncertain=False,
            alternative_categories=[],
            summary_one_liner="A short summary.",
            key_insights=["insight 1"],
            extracted_entities=ExtractedEntities(technologies=["FastAPI"]),
        ),
    )
    assert result.analysis is not None
    assert result.analysis.suggested_category == "Tech Tools"
    assert "FastAPI" in result.analysis.extracted_entities.technologies


# ===================================================================
# Storage tests — hit a real (tempdir-backed) Chroma collection.
# First run downloads ~80 MB of ONNX MiniLM weights, ~10 s on a clean machine.
# Subsequent runs are <1 s.
# ===================================================================

def _make_ingestion_item(
    url: str,
    title: str,
    body: str,
    category: str,
    summary: str,
    *,
    location: str | None = None,
    technologies: list[str] | None = None,
) -> IngestionResult:
    """Helper: build a complete IngestionResult that the store will accept."""
    return IngestionResult(
        url=url,
        source_type=SourceType.ARTICLE,
        article=ArticleResult(
            url=url,
            title=title,
            text=body,
            word_count=len(body.split()),
        ),
        analysis=AnalysisResult(
            suggested_category=category,
            is_uncertain=False,
            alternative_categories=[],
            summary_one_liner=summary,
            key_insights=[f"insight about {title}"],
            extracted_entities=ExtractedEntities(
                location=location,
                technologies=technologies or [],
            ),
        ),
    )


def test_vector_store_round_trip_search_and_categories() -> None:
    """add 3 items → semantic search returns the right top hit →
    get_all_categories returns the unique sorted set."""
    from src.storage import VectorStoreManager

    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStoreManager(path=tmp, collection_name="smoke_test")

        items = [
            _make_ingestion_item(
                url="https://example.com/fastapi",
                title="FastAPI guide",
                body=(
                    "FastAPI is a modern web framework for building HTTP APIs in "
                    "Python with type hints and Pydantic. Supports async, OpenAPI, "
                    "dependency injection, websockets."
                ),
                category="Tech Tools",
                summary="Python web framework with type-safe APIs and OpenAPI docs.",
                technologies=["FastAPI", "Pydantic", "Uvicorn"],
            ),
            _make_ingestion_item(
                url="https://example.com/hanoi",
                title="Weekend in Hanoi",
                body=(
                    "A travel guide to Hanoi covering street food, the Old Quarter, "
                    "Hoan Kiem Lake at sunrise, and a day trip to Ha Long Bay's "
                    "limestone karsts."
                ),
                category="Travel",
                summary="Long-weekend itinerary for Hanoi and Ha Long Bay.",
                location="Hanoi",
            ),
            _make_ingestion_item(
                url="https://example.com/index-funds",
                title="Index funds 101",
                body=(
                    "Index funds track a market benchmark like the S&P 500 with low "
                    "fees, making them a core building block of long-term investing "
                    "strategies and retirement portfolios."
                ),
                category="Finance",
                summary="Low-fee index funds as the core of long-term investing.",
            ),
        ]

        for item in items:
            assert store.add_item(item.url, item) is True

        assert store.count() == 3

        # ---- semantic search: tech query should pull FastAPI first
        hits = store.search_items("python web framework with type hints", limit=3)
        assert len(hits) >= 1
        assert hits[0].url == "https://example.com/fastapi"
        assert hits[0].category == "Tech Tools"
        assert "FastAPI" in hits[0].document
        assert isinstance(hits[0].distance, float)
        assert isinstance(hits[0], SearchHit)

        # ---- semantic search: travel query should pull Hanoi first
        hits = store.search_items("vietnam itinerary and limestone karst landscapes", limit=3)
        assert hits[0].url == "https://example.com/hanoi"
        assert hits[0].category == "Travel"

        # ---- category filter narrows the result set
        finance_hits = store.search_items("anything", limit=5, category="Finance")
        assert all(h.category == "Finance" for h in finance_hits)
        assert len(finance_hits) == 1

        # ---- get_all_categories
        cats = store.get_all_categories()
        assert cats == ["Finance", "Tech Tools", "Travel"]

        # ---- metadata round-trip: technologies pipe-joined + entities_json full
        hit = store.get_by_url("https://example.com/fastapi")
        assert hit is not None
        assert hit.category == "Tech Tools"
        assert "FastAPI" in hit.metadata["technologies"]  # pipe-joined string
        import json as _json
        ents_back = _json.loads(hit.metadata["entities_json"])
        assert ents_back["technologies"] == ["FastAPI", "Pydantic", "Uvicorn"]


def test_vector_store_upsert_is_idempotent_by_url() -> None:
    """Re-adding the same URL replaces the row instead of duplicating it."""
    from src.storage import VectorStoreManager

    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStoreManager(path=tmp, collection_name="smoke_test_idem")

        v1 = _make_ingestion_item(
            url="https://example.com/x",
            title="Title v1",
            body="body version one",
            category="CatA",
            summary="summary v1",
        )
        v2 = _make_ingestion_item(
            url="https://example.com/x",
            title="Title v2",
            body="body version two with more content",
            category="CatB",
            summary="summary v2",
        )

        store.add_item(v1.url, v1)
        store.add_item(v2.url, v2)

        assert store.count() == 1
        hit = store.get_by_url("https://example.com/x")
        assert hit is not None
        assert hit.category == "CatB"
        assert hit.summary == "summary v2"
        # And only the new category survives in the cross-store view.
        assert store.get_all_categories() == ["CatB"]


def test_vector_store_refuses_to_store_items_without_analysis() -> None:
    """add_item must no-op for items the LLM hasn't analyzed yet."""
    from src.storage import VectorStoreManager

    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStoreManager(path=tmp, collection_name="smoke_test_noanalysis")
        unanalyzed = IngestionResult(
            url="https://example.com/no-analysis",
            source_type=SourceType.ARTICLE,
            article=ArticleResult(url="https://example.com/no-analysis", title="t", text="some body"),
            analysis=None,
        )
        assert store.add_item(unanalyzed.url, unanalyzed) is False
        assert store.count() == 0


# ===================================================================
# API integration tests — uses FastAPI's TestClient with an injected
# orchestrator (tempdir store + fake LLM). No Ollama, no network.
# ===================================================================

def _make_api_client(tmp_chroma_path: str, *, spy_background: list | None = None):
    """Build a TestClient whose orchestrator uses a tempdir-backed store and
    a fake LLMAnalyzer that returns a canned AnalysisResult.

    Returns (client, store) so tests can poke the store directly.

    `spy_background` (optional): if provided, the orchestrator's
    `process_in_background` is replaced with a spy that appends each call
    into this list. We do this so tests can assert the BackgroundTasks
    plumbing fires without actually running yt-dlp / Whisper / Ollama.
    """
    from fastapi.testclient import TestClient

    from src.api.main import app, get_orchestrator
    from src.orchestrator import IngestionOrchestrator
    from src.storage import VectorStoreManager

    class _FakeLLM:
        """Stand-in for LLMAnalyzer that derives a deterministic result from
        the ingestion text. Lets the API ingest endpoint be exercised end-to-end
        without requiring Ollama to be running."""

        def analyze(self, ingestion, existing_categories=None):
            text = ingestion.aggregated_text.lower()
            if "vietnam" in text or "ha long" in text:
                cat = "Travel"
            elif "fastapi" in text or "python" in text:
                cat = "Tech Tools"
            else:
                cat = "Misc"
            return AnalysisResult(
                suggested_category=cat,
                is_uncertain=False,
                alternative_categories=[],
                summary_one_liner=f"Fake summary for {ingestion.url}",
                key_insights=["fake insight 1", "fake insight 2"],
                extracted_entities=ExtractedEntities(),
            )

    test_store = VectorStoreManager(path=tmp_chroma_path, collection_name="api_smoke_test")
    test_orch = IngestionOrchestrator(llm_analyzer=_FakeLLM(), vector_store=test_store)

    if spy_background is not None:
        def _spy(url, **kwargs):
            spy_background.append((url, kwargs))
        test_orch.process_in_background = _spy  # type: ignore[method-assign]

    app.dependency_overrides[get_orchestrator] = lambda: test_orch
    client = TestClient(app)
    return client, test_store


def test_api_categories_endpoint_empty_store() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _make_api_client(tmp)
        try:
            res = client.get("/api/categories")
            assert res.status_code == 200
            assert res.json() == {"categories": []}
        finally:
            client.app.dependency_overrides.clear()


def test_api_search_returns_hits_from_seeded_store() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client, store = _make_api_client(tmp)
        try:
            store.add_item(
                "https://example.com/hanoi",
                _make_ingestion_item(
                    url="https://example.com/hanoi",
                    title="Weekend in Hanoi",
                    body="Travel guide for Hanoi, Vietnam — street food, Old Quarter, Ha Long Bay.",
                    category="Travel",
                    summary="Hanoi long-weekend itinerary.",
                    location="Hanoi",
                ),
            )
            store.add_item(
                "https://example.com/fastapi",
                _make_ingestion_item(
                    url="https://example.com/fastapi",
                    title="FastAPI",
                    body="Python web framework with type hints and Pydantic.",
                    category="Tech Tools",
                    summary="Type-safe Python APIs.",
                    technologies=["FastAPI", "Pydantic"],
                ),
            )

            res = client.post("/api/search", json={"query": "vietnam travel itinerary", "limit": 5})
            assert res.status_code == 200
            payload = res.json()
            assert payload["query"] == "vietnam travel itinerary"
            assert len(payload["hits"]) >= 1
            assert payload["hits"][0]["url"] == "https://example.com/hanoi"
            assert payload["hits"][0]["category"] == "Travel"

            # Category filter narrows the result set.
            res = client.post("/api/search", json={"query": "anything", "category": "Tech Tools"})
            assert res.status_code == 200
            hits = res.json()["hits"]
            assert all(h["category"] == "Tech Tools" for h in hits)

            # Categories endpoint reflects both seeded items.
            res = client.get("/api/categories")
            assert res.status_code == 200
            assert sorted(res.json()["categories"]) == ["Tech Tools", "Travel"]
        finally:
            client.app.dependency_overrides.clear()


def test_api_ingest_bad_url_returns_400() -> None:
    """A URL the classifier can't parse must map to HTTP 400, not 500."""
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _make_api_client(tmp)
        try:
            res = client.post("/api/ingest", json={"url": "not-a-url", "store": False})
            assert res.status_code == 400
            assert "classif" in res.json()["detail"].lower() or "url" in res.json()["detail"].lower()
        finally:
            client.app.dependency_overrides.clear()


def test_api_ingest_validation_error_returns_422() -> None:
    """Pydantic rejects missing `url` → FastAPI maps to 422."""
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _make_api_client(tmp)
        try:
            res = client.post("/api/ingest", json={})
            assert res.status_code == 422
        finally:
            client.app.dependency_overrides.clear()


def test_api_ingest_returns_202_with_placeholder_and_schedules_background() -> None:
    """The async refactor: /api/ingest returns 202 + placeholder JSON in
    <1 s, persists a `status=processing` row, and schedules the heavy
    pipeline as a background task."""
    with tempfile.TemporaryDirectory() as tmp:
        spy: list = []
        client, store = _make_api_client(tmp, spy_background=spy)
        try:
            url = "https://example.com/some-article"
            res = client.post("/api/ingest", json={"url": url})

            assert res.status_code == 202
            payload = res.json()
            assert payload["url"] == url
            assert payload["source_type"] == "article"
            assert payload["status"] == "processing"
            assert payload["analysis"] is None  # not yet — that's the BG task's job

            # Placeholder row is in the store, status == "processing".
            hit = store.get_by_url(url)
            assert hit is not None
            assert hit.metadata["status"] == "processing"
            assert hit.metadata["category"] == "Processing"

            # And the background task was scheduled — TestClient runs it
            # synchronously after the response, so spy is populated by now.
            assert len(spy) == 1
            scheduled_url, scheduled_kwargs = spy[0]
            assert scheduled_url == url
            assert scheduled_kwargs["analyze"] is True
            assert scheduled_kwargs["store"] is True
        finally:
            client.app.dependency_overrides.clear()


def test_api_ingest_placeholder_hides_from_categories() -> None:
    """A `Processing` placeholder must NOT show up in /api/categories — the
    iOS dashboard would otherwise display a synthetic category that
    disappears when the pipeline completes."""
    with tempfile.TemporaryDirectory() as tmp:
        spy: list = []
        client, store = _make_api_client(tmp, spy_background=spy)
        try:
            client.post("/api/ingest", json={"url": "https://example.com/x"})
            res = client.get("/api/categories")
            assert res.status_code == 200
            assert res.json() == {"categories": []}
        finally:
            client.app.dependency_overrides.clear()


def test_vector_store_add_placeholder_then_mark_failed() -> None:
    """Storage round-trip for the async lifecycle:
       add_placeholder → status=processing → mark_failed → status=failed."""
    from src.schemas import SourceType
    from src.storage import VectorStoreManager

    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStoreManager(path=tmp, collection_name="async_lifecycle")

        url = "https://example.com/pending"
        assert store.add_placeholder(url, SourceType.ARTICLE) is True

        hit = store.get_by_url(url)
        assert hit is not None
        assert hit.metadata["status"] == "processing"
        assert hit.metadata["category"] == "Processing"
        assert store.count() == 1
        # Placeholder doesn't pollute the category list.
        assert store.get_all_categories() == []

        # Mark as failed.
        assert store.mark_failed(url, "yt-dlp 403 from instagram") is True
        hit = store.get_by_url(url)
        assert hit is not None
        assert hit.metadata["status"] == "failed"
        assert "yt-dlp 403" in hit.metadata["summary"]


def test_vector_store_completed_replaces_placeholder() -> None:
    """Once the background pipeline finishes, calling add_item on the same
    URL must promote the row from `processing` to `completed`."""
    from src.schemas import SourceType
    from src.storage import VectorStoreManager

    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStoreManager(path=tmp, collection_name="async_promote")
        url = "https://example.com/promote"
        store.add_placeholder(url, SourceType.ARTICLE)
        assert store.get_by_url(url).metadata["status"] == "processing"

        # Simulate the background task completing.
        result = _make_ingestion_item(
            url=url, title="Real Title",
            body="Some real extracted content here.",
            category="Tech Tools", summary="A real summary now.",
        )
        store.add_item(url, result)

        hit = store.get_by_url(url)
        assert hit is not None
        assert hit.metadata["status"] == "completed"
        assert hit.metadata["category"] == "Tech Tools"
        # No duplicate — upsert kept the same id.
        assert store.count() == 1
        # Category now visible.
        assert store.get_all_categories() == ["Tech Tools"]


# ===================================================================
# Item + category management (DELETE / PATCH)
# ===================================================================

def _seed_management_store(store) -> None:
    """Three items across two categories so the management tests have
    something realistic to mutate."""
    for url, title, body, cat, summary in [
        ("https://example.com/fastapi", "FastAPI", "Python web framework with type hints.",
         "Tech Tools", "Type-safe Python APIs."),
        ("https://example.com/django", "Django", "Python full-stack web framework with ORM.",
         "Tech Tools", "Batteries-included Python framework."),
        ("https://example.com/hanoi", "Hanoi guide", "Vietnam street food and Ha Long Bay.",
         "Travel", "Hanoi long-weekend itinerary."),
    ]:
        store.add_item(url, _make_ingestion_item(
            url=url, title=title, body=body, category=cat, summary=summary,
        ))


def test_vector_store_delete_item_and_404_on_missing() -> None:
    from src.storage import VectorStoreManager
    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStoreManager(path=tmp, collection_name="mgmt_delete")
        _seed_management_store(store)
        assert store.count() == 3

        assert store.delete_item("https://example.com/fastapi") is True
        assert store.count() == 2
        assert store.get_by_url("https://example.com/fastapi") is None

        # Idempotent: deleting again returns False instead of raising.
        assert store.delete_item("https://example.com/fastapi") is False
        assert store.delete_item("https://example.com/does-not-exist") is False


def test_vector_store_update_item_patches_fields_in_place() -> None:
    from src.storage import VectorStoreManager
    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStoreManager(path=tmp, collection_name="mgmt_patch")
        _seed_management_store(store)

        updated = store.update_item(
            "https://example.com/django",
            title="Django (renamed)",
            category="Web Frameworks",
        )
        assert updated is not None
        assert updated.metadata["title"] == "Django (renamed)"
        assert updated.metadata["category"] == "Web Frameworks"
        # Untouched field stayed put.
        assert updated.metadata["summary"] == "Batteries-included Python framework."

        # Round-trips on a fresh read.
        re_read = store.get_by_url("https://example.com/django")
        assert re_read.metadata["category"] == "Web Frameworks"

        # Missing URL → None.
        assert store.update_item("https://example.com/missing", title="x") is None


def test_vector_store_rename_and_delete_category_bulk() -> None:
    from src.storage import VectorStoreManager
    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStoreManager(path=tmp, collection_name="mgmt_categories")
        _seed_management_store(store)

        # Rename "Tech Tools" → "Programming" across both Python rows.
        moved = store.rename_category("Tech Tools", "Programming")
        assert moved == 2
        cats = store.get_all_categories()
        assert "Tech Tools" not in cats
        assert "Programming" in cats
        assert "Travel" in cats

        # No-op when names match.
        assert store.rename_category("Programming", "Programming") == 0

        # Delete the whole "Programming" category.
        removed = store.delete_category("Programming")
        assert removed == 2
        assert store.count() == 1
        assert store.get_all_categories() == ["Travel"]

        # Empty / no-op cases.
        assert store.delete_category("Programming") == 0
        assert store.delete_category("") == 0


def test_api_delete_item_endpoint_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        spy: list = []
        client, store = _make_api_client(tmp, spy_background=spy)
        try:
            _seed_management_store(store)

            res = client.request("DELETE", "/api/items",
                                 json={"url": "https://example.com/django"})
            assert res.status_code == 200
            assert res.json() == {"url": "https://example.com/django", "deleted": True}
            assert store.get_by_url("https://example.com/django") is None

            # Second delete → 404.
            res = client.request("DELETE", "/api/items",
                                 json={"url": "https://example.com/django"})
            assert res.status_code == 404
        finally:
            client.app.dependency_overrides.clear()


def test_api_patch_item_endpoint_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        spy: list = []
        client, store = _make_api_client(tmp, spy_background=spy)
        try:
            _seed_management_store(store)

            res = client.patch("/api/items", json={
                "url": "https://example.com/fastapi",
                "summary": "Type-safe Python APIs with Pydantic.",
                "category": "Programming",
            })
            assert res.status_code == 200
            payload = res.json()
            assert payload["updated"] is True
            assert payload["item"]["category"] == "Programming"

            # Title was not in the request → stayed unchanged.
            hit = store.get_by_url("https://example.com/fastapi")
            assert hit.metadata["title"] == "FastAPI"
            assert hit.metadata["category"] == "Programming"
            assert hit.metadata["summary"] == "Type-safe Python APIs with Pydantic."

            # 400 when nothing to patch.
            res = client.patch("/api/items", json={"url": "https://example.com/fastapi"})
            assert res.status_code == 400

            # 404 on missing URL.
            res = client.patch("/api/items", json={
                "url": "https://example.com/does-not-exist", "title": "x",
            })
            assert res.status_code == 404
        finally:
            client.app.dependency_overrides.clear()


def test_api_category_rename_and_delete_endpoints() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        spy: list = []
        client, store = _make_api_client(tmp, spy_background=spy)
        try:
            _seed_management_store(store)

            # Rename Tech Tools → Programming (affects 2 rows).
            res = client.patch("/api/categories",
                               json={"old_name": "Tech Tools", "new_name": "Programming"})
            assert res.status_code == 200
            assert res.json() == {"affected": 2}

            cats = client.get("/api/categories").json()["categories"]
            assert sorted(cats) == ["Programming", "Travel"]

            # 400 when old == new.
            res = client.patch("/api/categories",
                               json={"old_name": "Programming", "new_name": "Programming"})
            assert res.status_code == 400

            # Delete Programming.
            res = client.request("DELETE", "/api/categories",
                                 json={"name": "Programming"})
            assert res.status_code == 200
            assert res.json() == {"affected": 2}
            assert store.count() == 1
            assert client.get("/api/categories").json()["categories"] == ["Travel"]
        finally:
            client.app.dependency_overrides.clear()


def test_process_in_background_flips_processing_to_failed_on_empty_extract() -> None:
    """The bug that left FB rows hanging: extractor returns no content,
    add_item silently refuses, placeholder stays in `processing` forever.
    The hardened orchestrator must catch this and call mark_failed."""
    from src.orchestrator import IngestionOrchestrator
    from src.schemas import SourceType
    from src.storage import VectorStoreManager

    class _EmptyExtractor:
        """Returns a VideoResult with no title, no transcript, no OCR —
        i.e. aggregated_text is empty. Mirrors the real yt-dlp-failed
        case where the extractor logs an error but doesn't raise."""
        def extract(self, url: str):
            from src.schemas import VideoResult
            r = VideoResult(url=url)
            r.metadata["error"] = "yt_dlp_failed"
            return r

    class _NoopLLM:
        """The real LLMAnalyzer returns an empty-input fallback (not an
        exception) when text is empty — we mirror that so the test
        exercises the *extractor_error detection* branch specifically,
        not the generic crash branch (which has its own test below)."""
        def analyze(self, ingestion, existing_categories=None):
            return AnalysisResult(
                suggested_category="Uncategorized",
                is_uncertain=True,
                alternative_categories=[],
                summary_one_liner="Empty",
                key_insights=[],
                extracted_entities=ExtractedEntities(),
            )

    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStoreManager(path=tmp, collection_name="empty_extract")
        orch = IngestionOrchestrator(
            video_extractor=_EmptyExtractor(),
            llm_analyzer=_NoopLLM(),
            vector_store=store,
        )

        url = "https://www.youtube.com/watch?v=abc123"
        store.add_placeholder(url, SourceType.VIDEO)
        assert store.get_by_url(url).metadata["status"] == "processing"

        orch.process_in_background(url, analyze=True, store=True)

        hit = store.get_by_url(url)
        assert hit is not None
        assert hit.metadata["status"] == "failed"
        # The reason surfaces in the summary so the user can see *why*.
        summary = hit.metadata["summary"]
        assert "yt_dlp_failed" in summary or "extractor" in summary, summary


def test_process_in_background_flips_to_failed_on_unhandled_exception() -> None:
    """If the pipeline raises *anything*, the row must end up failed —
    never silently stuck in processing."""
    from src.orchestrator import IngestionOrchestrator
    from src.schemas import SourceType
    from src.storage import VectorStoreManager

    class _CrashingExtractor:
        def extract(self, url: str):
            raise RuntimeError("simulated yt-dlp crash")

    class _FakeLLM:
        def analyze(self, ingestion, existing_categories=None):
            raise AssertionError("Should not reach LLM after extractor crash")

    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStoreManager(path=tmp, collection_name="crash_path")
        orch = IngestionOrchestrator(
            video_extractor=_CrashingExtractor(),
            llm_analyzer=_FakeLLM(),
            vector_store=store,
        )

        url = "https://www.youtube.com/watch?v=12345"
        store.add_placeholder(url, SourceType.VIDEO)

        # Must NOT propagate the RuntimeError out of process_in_background.
        orch.process_in_background(url, analyze=True, store=True)

        hit = store.get_by_url(url)
        assert hit is not None
        assert hit.metadata["status"] == "failed"
        assert "simulated yt-dlp crash" in hit.metadata["summary"]


def test_api_create_manual_item_round_trip() -> None:
    """Step 11: POST /api/items inserts a fully-specified row directly
    as status=completed, bypassing extractor + LLM."""
    with tempfile.TemporaryDirectory() as tmp:
        spy: list = []
        client, store = _make_api_client(tmp, spy_background=spy)
        try:
            res = client.post("/api/items", json={
                "url": "https://example.com/manual-1",
                "title": "Manual entry",
                "summary": "I made this by hand.",
                "category": "Reading List",
            })
            assert res.status_code == 201, res.text
            payload = res.json()
            assert payload["status"] == "completed"
            assert payload["analysis"]["suggested_category"] == "Reading List"
            assert payload["analysis"]["is_uncertain"] is False

            # Row lives in the store, status=completed, category honored.
            hit = store.get_by_url("https://example.com/manual-1")
            assert hit is not None
            assert hit.metadata["status"] == "completed"
            assert hit.metadata["category"] == "Reading List"
            assert hit.metadata["title"] == "Manual entry"

            # The new category is visible to /api/categories.
            cats = client.get("/api/categories").json()["categories"]
            assert "Reading List" in cats

            # Background task pipeline must NOT have been invoked.
            assert spy == []
        finally:
            client.app.dependency_overrides.clear()


def test_api_create_manual_item_validates_required_fields() -> None:
    """Missing title / category / url → 422 (Pydantic) or 400 (sanitize)."""
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _make_api_client(tmp)
        try:
            # Missing title.
            res = client.post("/api/items", json={
                "url": "https://example.com/x", "category": "Cat", "summary": "",
            })
            assert res.status_code == 422
            # Empty url string fails Pydantic's min_length=1.
            res = client.post("/api/items", json={
                "url": "", "title": "T", "category": "C",
            })
            assert res.status_code == 422
        finally:
            client.app.dependency_overrides.clear()


def test_smart_category_delete_move_to_general_via_rename() -> None:
    """Step 11 smart-delete: "Move to General" reuses the existing
    PATCH /api/categories rename. Items keep their data but the
    category flips to General; the old category disappears."""
    with tempfile.TemporaryDirectory() as tmp:
        spy: list = []
        client, store = _make_api_client(tmp, spy_background=spy)
        try:
            _seed_management_store(store)  # 3 items across Tech Tools + Travel
            assert sorted(store.get_all_categories()) == ["Tech Tools", "Travel"]

            res = client.patch("/api/categories", json={
                "old_name": "Tech Tools", "new_name": "General",
            })
            assert res.status_code == 200
            assert res.json() == {"affected": 2}

            # Items are still there — only the category metadata changed.
            assert store.count() == 3
            cats = client.get("/api/categories").json()["categories"]
            assert "Tech Tools" not in cats
            assert "General" in cats
            assert "Travel" in cats
            # The two Tech Tools rows now answer to General.
            fastapi_hit = store.get_by_url("https://example.com/fastapi")
            assert fastapi_hit.metadata["category"] == "General"
        finally:
            client.app.dependency_overrides.clear()


def test_api_health_returns_item_count() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client, store = _make_api_client(tmp)
        try:
            store.add_item(
                "https://example.com/x",
                _make_ingestion_item(
                    url="https://example.com/x",
                    title="t", body="some content here", category="Misc", summary="s",
                ),
            )
            res = client.get("/api/health")
            assert res.status_code == 200
            body = res.json()
            assert body["status"] == "ok"
            assert body["items_indexed"] == 1
        finally:
            client.app.dependency_overrides.clear()


if __name__ == "__main__":
    # Run with `python tests/test_smoke.py` — no pytest dependency required.
    import inspect
    tests = [
        (name, fn)
        for name, fn in globals().items()
        if name.startswith("test_") and inspect.isfunction(fn)
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {name}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
