# Smart Saver — Project Memory Bank

> Read this file first in any new session. It is the single source of truth for
> project status, architecture, conventions, and outstanding work. Update it
> whenever you finish or re-scope a step.

---

## 1. Project Vision

Smart Saver is an iOS app + Share Extension that lets a user share any link
(article, LinkedIn/Instagram post, YouTube video, Reel, TikTok, …) from their
phone into a personal "second-brain" archive. The backend:

1. Ingests the link.
2. Extracts every piece of usable text — body copy, captions, audio transcript,
   on-screen OCR text.
3. Runs the aggregated text through a **local LLM** for summarisation and
   auto-categorisation (e.g. Real Estate, Tech Tools, Finance, Travel).
4. Stores the embedding + metadata in a **Vector DB** (ChromaDB) so the user
   can later search semantically across everything they ever saved.

---

## 2. High-Level Architecture

```
┌────────────────┐    ┌────────────────────┐    ┌─────────────────┐    ┌──────────────┐
│ iOS App +      │ →  │ FastAPI Backend    │ →  │ Local LLM       │ →  │ ChromaDB     │
│ Share Ext.     │    │ (Step 4: live)     │    │ (summary+tags)  │    │ (vector DB)  │
│ (Step 5: live) │    │                    │    │                 │    │              │
└────────────────┘    └────────────────────┘    └─────────────────┘    └──────────────┘
                              │
                              ▼
                       ┌─────────────────────────────────┐
                       │  Ingestion Pipeline  (Step 1)   │
                       │  ─────────────────────────────  │
                       │  Orchestrator                   │
                       │    ├── ArticleExtractor         │
                       │    │     trafilatura + BS4      │
                       │    └── VideoExtractor           │
                       │          yt-dlp → audio → ASR   │
                       │          yt-dlp → video → OCR   │
                       └─────────────────────────────────┘
                                       │
                                       ▼
                       ┌─────────────────────────────────┐
                       │  Analysis Layer  (Step 2)       │
                       │  ─────────────────────────────  │
                       │  LLMAnalyzer (local Ollama)     │
                       │    • dynamic category (reuse    │
                       │      existing or invent new)    │
                       │    • is_uncertain + alts        │
                       │    • one-liner + key insights   │
                       │    • extracted entities         │
                       │  Output: AnalysisResult JSON    │
                       │  Schema enforced via Ollama     │
                       │  `format=<json_schema>`         │
                       └─────────────────────────────────┘
                                       │
                                       ▼
                       ┌─────────────────────────────────┐
                       │  Vector Storage  (Step 3)       │
                       │  ─────────────────────────────  │
                       │  VectorStoreManager (ChromaDB)  │
                       │    • persistent at data/chroma  │
                       │    • upsert by URL              │
                       │    • doc = aggregated_text      │
                       │    • metadata = flattened       │
                       │      AnalysisResult fields      │
                       │  Embedder: ONNX MiniLM (default)│
                       │           / Ollama (configurable)│
                       │  Feedback loop: get_all_         │
                       │  categories() auto-fed to LLM   │
                       │  on the next ingest             │
                       └─────────────────────────────────┘
                                       │
                                       ▼
                       ┌─────────────────────────────────┐
                       │  HTTP API  (Step 4 + Step 6)    │
                       │  ─────────────────────────────  │
                       │  FastAPI (uvicorn) + CORS       │
                       │  POST /api/ingest → 202 +       │
                       │       BackgroundTasks (Step 6)  │
                       │  POST /api/search               │
                       │  GET  /api/categories           │
                       │  GET  /api/health               │
                       │  Lifespan-built singleton       │
                       │  IngestionOrchestrator          │
                       │  Status: processing/completed/  │
                       │          failed (Step 6)        │
                       └─────────────────────────────────┘
```

---

## 3. Active Tech Stack

| Layer             | Choice                              | Why                                    |
|-------------------|-------------------------------------|----------------------------------------|
| Language          | Python 3.14                         | Already provisioned in `./venv`        |
| Article extract   | `trafilatura` (primary) + `bs4`     | Best-in-class boilerplate removal      |
| Video metadata    | `yt-dlp`                            | Supports YT, IG, TikTok, X, FB, …      |
| ASR (transcribe)  | `faster-whisper` (`base` by default)| CPU-friendly, runs on Apple Silicon    |
| Frame sampling    | `opencv-python`                     | Read every N-th second                 |
| OCR               | `easyocr`                           | No external tesseract dependency       |
| Data models       | `pydantic` v2                       | Strict typing, JSON-ready              |
| CLI               | `typer` + `rich`                    | Friendly DX                            |
| Logging           | stdlib `logging` (configured once)  | Zero extra deps                        |
| Local LLM         | `ollama` daemon + `ollama` Py SDK   | Structured outputs via `format=schema` |
| Default LLM model | `llama3` (8B Q4_0) — overridable    | Already pulled locally                 |
| Vector DB         | `chromadb` (PersistentClient)       | Persists at `data/chroma/`             |
| Default embedder  | ONNX `all-MiniLM-L6-v2` (bundled)   | ~80 MB; auto-downloaded on first use   |
| Alt embedder      | `OllamaEmbeddingFunction`           | `embedding_backend="ollama"` + pull model |
| Web API           | `fastapi` + `uvicorn` + `CORSMiddleware` | Three `/api/*` endpoints + /health |
| iOS app           | SwiftUI on iOS 17+                  | Source under `ios/SmartSaver/`         |
| iOS share ext.    | UIKit `UIViewController`            | Source under `ios/ShareExtension/`     |
| iOS project gen   | `xcodegen` (optional)               | `cd ios && xcodegen generate`          |

System deps: **`ffmpeg`** (required by yt-dlp for audio extraction) — verified
present at `/opt/homebrew/bin/ffmpeg`.

---

## 4. Folder & File Structure

```
smart-saver/
├── claude.md                       ← you are here
├── requirements.txt                ← pinned-ish deps
├── .gitignore
├── cli.py                          ← `python cli.py <url>` entry point
├── venv/                           ← project virtualenv (pre-existing)
├── data/
│   └── tmp/                        ← scratch dir for downloaded audio/video
├── src/
│   ├── __init__.py
│   ├── config.py                   ← Pydantic Settings (paths, model sizes, Ollama, …)
│   ├── logger.py                   ← `get_logger(name)` helper
│   ├── schemas.py                  ← ArticleResult / VideoResult / AnalysisResult /
│   │                                 ExtractedEntities / IngestionResult
│   ├── orchestrator.py             ← IngestionOrchestrator: extract → analyze
│   ├── utils/
│   │   ├── __init__.py
│   │   └── url_classifier.py       ← classify(url) → SourceType
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── base.py                 ← BaseExtractor ABC
│   │   ├── article.py              ← ArticleExtractor
│   │   └── video.py                ← VideoExtractor (yt-dlp + ASR + OCR)
│   ├── analyzers/
│   │   ├── __init__.py
│   │   └── llm_analyzer.py         ← LLMAnalyzer (Ollama + structured outputs)
│   ├── storage/
│   │   ├── __init__.py
│   │   └── vector_store.py         ← VectorStoreManager (ChromaDB persistent)
│   └── api/
│       ├── __init__.py
│       └── main.py                 ← FastAPI app, routes, CORS, lifespan
├── ios/                            ← Step 5: SwiftUI client + Share Extension
│   ├── SETUP.md                    ← detailed Xcode setup (xcodegen + manual)
│   ├── project.yml                 ← xcodegen spec (app + extension targets)
│   ├── SmartSaver/                 ← main app target sources
│   │   ├── SmartSaverApp.swift
│   │   ├── Models/APIModels.swift
│   │   ├── Services/NetworkManager.swift
│   │   └── Views/
│   │       ├── ContentView.swift   ← dashboard + .searchable
│   │       ├── CategoryCard.swift
│   │       └── SearchResultRow.swift
│   └── ShareExtension/             ← Share Extension target sources
│       └── ShareViewController.swift
└── tests/
    └── test_smoke.py               ← offline smoke tests
```

---

## 5. Conventions

- **Type hints everywhere.** `from __future__ import annotations` at top of
  every module. Public functions/methods get explicit return types.
- **Errors fail loud, not silent.** Every extractor wraps the actual work in
  try/except, logs with `logger.exception`, and returns a result with an
  `error` field populated rather than raising up to the CLI. The CLI decides
  whether to print or re-raise.
- **No model loading at import time.** `faster-whisper` and `easyocr` are
  heavy; they are imported and instantiated lazily inside
  `VideoExtractor._transcribe` / `_ocr_frames` so an article-only run stays
  fast.
- **All paths through `config.Settings`.** Never hard-code `/tmp/...`.
- **`logger = get_logger(__name__)`** at the top of each module.

---

## 6. Step 1 — Data Ingestion Pipeline

### Status: ✅ Implemented (2026-06-01) — bugfixed (2026-06-01)

### Bugfix log (2026-06-01)

Two issues surfaced on the first live YouTube run; both fixed in
`src/extractors/video.py`:

1. **OpenCV failed to open `video.f251.webm`.** Root cause: `_find_file`
   sorted `glob("video.*")` alphabetically and picked the intermediate webm
   stream that yt-dlp left behind, instead of the merged `video.mp4`. Fix:
   (a) tightened the yt-dlp format selector to prefer mp4+m4a streams,
   (b) added an `FFmpegVideoConvertor` post-processor as a safety net so the
   final container is always mp4, (c) added an `allowed_extensions`
   whitelist to `_find_file` so it only ever returns `.mp4/.m4v/.mov/.mkv`
   for the video file and `.mp3/.m4a/.wav/.aac/.opus` for the audio file.
2. **Whisper VAD removed 100% of the audio** (`VAD filter removed 03:33`).
   Root cause: `vad_filter=True` was too aggressive on tracks with heavy
   music/beats and on quiet speech sections. Fix: `vad_filter=False` in
   `_transcribe`. The extra ASR cost on silence is negligible.

Verified on `https://www.youtube.com/watch?v=dQw4w9WgXcQ`:
transcript 1,637 chars, 21 frames sampled (OpenCV opened the mp4 cleanly),
0 OCR segments — expected, the music video has no on-screen text.

What works end-to-end:

- Orchestrator classifies a URL as `article` or `video` and dispatches.
- `ArticleExtractor` returns `{title, author, publish_date, text, metadata}`
  via trafilatura, with a BeautifulSoup `<p>`-tag fallback if trafilatura
  returns nothing.
- `VideoExtractor` returns `{title, uploader, description, duration,
  transcript, ocr_text, ocr_segments, …}`:
  - yt-dlp pulls metadata + downloads bestaudio (mp3 via ffmpeg) and a low-res
    mp4 into `data/tmp/<uuid>/`.
  - `faster-whisper` transcribes the audio (default `base` model, CPU, int8).
  - OpenCV samples one frame every `FRAME_SAMPLE_INTERVAL_SEC` seconds (default
    2 s) and feeds them to `easyocr`; duplicate OCR lines are de-duplicated
    while preserving order.
  - Temp directory is removed in a `finally` block.
- `IngestionResult.aggregated_text` builds the LLM-ready blob:
  `TITLE → DESCRIPTION/CAPTION → BODY/TRANSCRIPT → ON-SCREEN TEXT`.
- CLI: `python cli.py <url>` prints a pretty Rich panel; `--json` dumps the
  full Pydantic model.

### How to run the first test

```bash
# 1. activate the existing venv
source venv/bin/activate

# 2. article test (fast, ~5 s)
python cli.py "https://www.bbc.com/news/world-66743328"

# 3. video test (slower — first run downloads the Whisper + EasyOCR models)
python cli.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# optional flags
python cli.py <url> --json                          # raw JSON
python cli.py <url> --whisper-model tiny            # faster, less accurate
python cli.py <url> --frame-interval 4              # sample every 4 s
python cli.py <url> --ocr-lang en --ocr-lang he     # multi-language OCR
```

### What needs to be done next

- **Step 3 — Vector storage.** `src/storage/vector_store.py` around ChromaDB:
  embed `aggregated_text`, upsert with the metadata payload + the
  `AnalysisResult` fields for category/tag filtering.
- **Step 4 — FastAPI server.** `POST /ingest` accepting `{url, existing_categories?}`,
  returning the full pipeline result. Re-use `IngestionOrchestrator` directly.
- **Step 5 — iOS Share Extension.** Sends `{url}` to `/ingest`. When the
  response has `analysis.is_uncertain=true`, surface a category picker over
  `analysis.alternative_categories` before saving.

### Known limitations to revisit

- Instagram / TikTok / X often require auth cookies; yt-dlp may 401. We will
  add a `--cookies-from-browser` passthrough when this becomes a real blocker.
- Newspaper3k was intentionally **not** used — frequently breaks on Python
  3.13+; trafilatura is the modern equivalent.
- Whisper runs on CPU by default. We can flip `WHISPER_DEVICE=metal` once we
  validate the wheel supports it.

---

## 6.5 Step 2 — Dynamic LLM Analysis Layer

### Status: ✅ Implemented (2026-06-01)

### Design — dynamic categorization, not fixed taxonomy

Smart Saver explicitly **rejects a hardcoded category list**. Categories are
emergent: each new item is shown to the LLM together with the user's
already-accepted categories, and the model chooses one of three behaviors:

| Situation                                | Behavior                                  |
|------------------------------------------|-------------------------------------------|
| Item clearly matches an existing label   | Reuse it verbatim                         |
| Nothing fits                             | Invent a new short Title-Case label       |
| Item plausibly fits 2+ labels OR low conf| `is_uncertain=true` + populate alts list  |

The third branch is what makes the system feel intelligent on the iOS
side — the Share Extension can prompt the user to disambiguate using
`analysis.alternative_categories` instead of silently picking wrong.

### How structured output is enforced

`LLMAnalyzer` passes the Pydantic-generated JSON schema to Ollama's
`format=<schema>` parameter (Ollama ≥ 0.5). The model is constrained at
sampling time to emit JSON that validates against `AnalysisResult`. We
still call `AnalysisResult.model_validate_json()` defensively and have a
forgiving-retry path that extracts `{...}` substrings if the model wraps
its answer in any prose.

### `AnalysisResult` schema (src/schemas.py)

```python
class AnalysisResult:
    suggested_category: str                # the chosen / invented label
    is_uncertain: bool                     # True ⇒ ask the user
    alternative_categories: list[str]      # populated only if uncertain
    summary_one_liner: str                 # ≤ 30 words, no filler
    key_insights: list[str]                # 3–7 short bullets
    extracted_entities: ExtractedEntities  # price / location / technologies +
                                           #   ad-hoc keys via extra="allow"
```

### Config (src/config.py — env-prefix `SMART_SAVER_`)

| Setting               | Default                       | Notes                              |
|-----------------------|-------------------------------|------------------------------------|
| `ollama_host`         | `http://localhost:11434`      | Local Ollama daemon                |
| `ollama_model`        | `llama3`                      | Already pulled locally             |
| `ollama_temperature`  | `0.2`                         | Low → deterministic JSON           |
| `ollama_num_ctx`      | `None`                        | Let Ollama default                 |
| `llm_max_input_chars` | `12000`                       | Hard cap before send               |
| `ollama_request_timeout_sec` | `120.0`                | Whole-call timeout                 |

### How to run

```bash
# Prereq: Ollama daemon up and model pulled (one-time)
ollama pull llama3

# Default: extract + analyze with whatever model is in settings
python cli.py "https://en.wikipedia.org/wiki/FastAPI"

# Reuse existing user categories (repeat the flag)
python cli.py "<url>" --category "Tech Tools" --category "Career Advice"

# Try a different / smaller model
python cli.py "<url>" --ollama-model llama3.2

# Extraction only (skip the LLM)
python cli.py "<url>" --no-analyze

# JSON pipeline output (for the future FastAPI route)
python cli.py "<url>" --json
```

### Live runs (2026-06-01) — verified behavior

| Input                                                | Existing cats           | Result                                                                                          |
|------------------------------------------------------|-------------------------|-------------------------------------------------------------------------------------------------|
| `wikipedia.org/wiki/FastAPI`                         | (none)                  | Invented `"Programming"`; technologies = [FastAPI, Pydantic, Starlette, Uvicorn]                 |
| `wikipedia.org/wiki/FastAPI`                         | Tech Tools, Career Advice, Finance | Correctly reused `"Tech Tools"` (no near-duplicate invented)                          |
| Offline schema round-trip with `is_uncertain=true`   | n/a                     | All fields incl. ad-hoc extras (`agent_phone`) parse and survive `extra="allow"`                |

### Prompt v2 (2026-06-01) — in-context bias fix

Earlier wording said "PREFER reusing one of these labels" which primed
small local models (Llama 3 8B) to lazy-match new content into whatever
happened to be in `existing_categories`. A gym reel kept landing under
`Travel` simply because `Travel` was on the list.

Three structural changes to `src/analyzers/llm_analyzer.py`:

1. **Reframed `existing_categories` as a near-duplicate avoidance reference,
   NOT a constraint.** New default behavior: invent a new specific label.
   Reuse only when the existing label is an *obvious synonym* of what the
   model would have picked on its own.
2. **Reordered the user prompt: content FIRST, reference list LAST.** The
   model commits to a Step-A label from the content before being shown
   the existing list — reduces anchoring on whatever was at the top of
   the prompt.
3. **Added a 4-step decision procedure + anti-bias rules + 3 few-shot
   examples** showing right-to-invent, right-to-reuse, and
   right-to-flag-uncertain cases. Generic fallbacks ("Misc", "Other",
   "General", "Uncategorized", "Stuff", "Random") are explicitly forbidden.

Live verification (2026-06-01, llama3 8B, same `existing_categories`
that previously caused lazy-matching):

| Content                                              | Existing cats             | Old (lazy)        | New (specific)             |
|------------------------------------------------------|---------------------------|-------------------|----------------------------|
| Home ab/core workout reel                            | Programming, Travel       | → Travel          | **→ Fitness** ✓           |
| 10-min pasta carbonara recipe                        | Programming, Travel       | → Travel          | **→ Recipes** ✓           |
| FastAPI + Pydantic tutorial                          | Tech Tools, Travel        | → Tech Tools      | **→ Tech Tools** ✓ (reuse) |
| Engineer-quits-Google-for-startup story              | Tech Tools, Career Advice | → Career Advice   | **→ Startup Stories** ✓ (invented specific) |

All 22 smoke tests still pass (the change is prompt-only — schemas and
storage paths are untouched).

### What needs to be done next (revised)

- **Step 5 — iOS Share Extension.** Renders the disambiguation prompt when
  `analysis.is_uncertain` is true.

---

## 6.6 Step 3 — Vector Storage (ChromaDB)

### Status: ✅ Implemented (2026-06-01)

### Design — the feedback loop

The store is more than a persistence sink; it is the **memory** that closes
the loop on dynamic categorization from Step 2.

```
   ingest URL
       │
       ▼
   extract  (Step 1)
       │
       ▼
   analyze  (Step 2)  ◄────── existing_categories
       │                      from get_all_categories()
       │                      (auto-pulled by orchestrator)
       ▼
   store    (Step 3) ─────────► data/chroma/  (persistent)
```

The next time the user shares an item, `IngestionOrchestrator.ingest()`
calls `VectorStoreManager.get_all_categories()` and passes the result to
`LLMAnalyzer.analyze()`, so the LLM is shown every accepted label and
prefers reusing them over inventing near-duplicates. This is what makes
the dynamic taxonomy converge over time instead of fragmenting.

### Metadata schema (flat, Chroma-safe)

Chroma metadata values must be `str | int | float | bool`. The store
flattens `IngestionResult` + `AnalysisResult` into these keys:

| Key                       | Type | Source                                       |
|---------------------------|------|----------------------------------------------|
| `url`                     | str  | item URL (also the doc ID)                   |
| `source_type`             | str  | `"article"` / `"video"`                      |
| `title`                   | str  | article.title or video.title                 |
| `category`                | str  | `analysis.suggested_category`                |
| `is_uncertain`            | bool | `analysis.is_uncertain`                      |
| `alternative_categories`  | str  | pipe-joined `analysis.alternative_categories`|
| `summary`                 | str  | `analysis.summary_one_liner`                 |
| `key_insights`            | str  | JSON-encoded list                            |
| `price`                   | str  | `analysis.extracted_entities.price`          |
| `location`                | str  | `analysis.extracted_entities.location`       |
| `technologies`            | str  | pipe-joined list (for human display)         |
| `entities_json`           | str  | full JSON dump (round-trips ad-hoc keys)     |
| `ingested_at`             | str  | ISO-8601 UTC timestamp                       |

The doc text (what gets embedded) is `IngestionResult.aggregated_text`.

### Public API surface

```python
store = VectorStoreManager()                # default path/collection from settings
store.add_item(url, ingestion_result)       # upsert by URL (idempotent)
store.search_items(query, limit=5,
                   category="Tech Tools")   # semantic search + optional filter
store.get_all_categories()                  # sorted unique set
store.get_by_url(url)                       # exact lookup
store.count()                               # number of indexed items
```

### Config (src/config.py — env-prefix `SMART_SAVER_`)

| Setting               | Default                       | Notes                              |
|-----------------------|-------------------------------|------------------------------------|
| `chroma_path`         | `<project>/data/chroma`       | PersistentClient path              |
| `chroma_collection`   | `smart_saver_items`           | One collection per app             |
| `embedding_backend`   | `"default"`                   | or `"ollama"`                      |
| `ollama_embed_model`  | `nomic-embed-text`            | only used when backend = "ollama"  |
| `chroma_telemetry`    | `False`                       | anonymized telemetry off           |

### CLI (refactored into sub-commands)

```bash
# Step 1+2+3 — extract, analyze, store
python cli.py ingest "<url>"
python cli.py ingest "<url>" --no-store          # transient run, don't persist
python cli.py ingest "<url>" --category "Travel" # override the auto-pulled list
python cli.py ingest "<url>" --json              # full pipeline JSON

# Step 3 — semantic search
python cli.py search "vietnam nature and waterfalls"
python cli.py search "python web frameworks" --limit 3
python cli.py search "anything" --category "Programming"
python cli.py search "..." --json

# Step 3 — known categories
python cli.py categories
python cli.py categories --json
```

NOTE: the bare `python cli.py <url>` form from Step 1/2 no longer works —
ingestion now lives under the `ingest` sub-command. Update any external
scripts accordingly.

### Live verification (2026-06-01)

Three Wikipedia ingests in a fresh store:

| Order | URL                  | Categories auto-fed       | LLM result                            |
|-------|----------------------|---------------------------|---------------------------------------|
| 1     | FastAPI              | (empty — store cold)      | Invented `Programming` (new)          |
| 2     | Ha Long Bay          | `['Programming']`         | Invented `Travel` (new, no match)     |
| 3     | Django (web fwk)     | `['Programming','Travel']`| **Reused `Programming`** ✓ no dup     |

Search results (excerpts):

```
search "python web frameworks with type hints"  →  Django  (0.494)
                                                   FastAPI (0.546)
                                                   Ha Long (1.095, way down)

search "vietnam nature and waterfalls"          →  Ha Long Bay first (0.698)

search "anything" --category Programming        →  only Django + FastAPI

categories                                      →  ['Programming', 'Travel']
```

### Tests (tests/test_smoke.py — 13/13 pass)

- `test_vector_store_round_trip_search_and_categories` — 3 items, semantic
  search ranks the right item first, category filter narrows the set,
  `get_all_categories` returns the sorted unique list, metadata
  round-trips (incl. `entities_json`).
- `test_vector_store_upsert_is_idempotent_by_url` — re-adding the same
  URL replaces the row instead of duplicating it.
- `test_vector_store_refuses_to_store_items_without_analysis` —
  `add_item` returns False for items the LLM hasn't analyzed yet.

First run on a clean machine downloads ~80 MB of ONNX MiniLM weights into
`~/.cache/chroma/onnx_models/`; subsequent runs complete in well under a
second.

---

## 6.7 Step 4 — FastAPI HTTP server

### Status: ✅ Implemented (2026-06-01)

The server is a thin REST layer over `IngestionOrchestrator` — no business
logic lives in the API module. A single orchestrator is built in the
`lifespan` startup handler and reused across requests; its internal
`LLMAnalyzer` and `VectorStoreManager` stay lazy so the Chroma collection
and Ollama HTTP session open on first use, not on import.

### Run it

```bash
# Recommended for iOS Simulator (loopback)
uvicorn src.api.main:app --reload

# Bind to LAN for a physical iOS device on the same WiFi
uvicorn src.api.main:app --host 0.0.0.0 --port 8000

# Or, equivalently, via environment override + the bundled defaults:
SMART_SAVER_API_HOST=0.0.0.0 SMART_SAVER_API_PORT=8000 \
    uvicorn src.api.main:app
```

Interactive Swagger UI lives at `http://<host>:<port>/docs`,
ReDoc at `/redoc`, raw OpenAPI at `/openapi.json`.

### Endpoint contracts

| Method | Path              | Request body                                                | Response                                  | Notable codes                                  |
|--------|-------------------|-------------------------------------------------------------|-------------------------------------------|------------------------------------------------|
| GET    | `/api/health`     | —                                                           | `{status: "ok", items_indexed: int}`      | 200                                            |
| POST   | `/api/ingest`     | `{url, analyze=true, store=true, existing_categories?[]}`   | full `IngestionResult` incl. `aggregated_text` | 200 / 400 unsupported URL / 422 body / 500   |
| POST   | `/api/search`     | `{query, limit=5, category?}`                               | `{query, category, hits: SearchHit[]}`    | 200 / 422 / 500                                |
| GET    | `/api/categories` | —                                                           | `{categories: string[]}`                  | 200 / 500                                      |

`SearchHit` carries `{url, distance, document, category, summary, metadata}`
where `metadata` is the same flat dict described in §6.6.

CORS: `allow_origins=settings.api_cors_origins` (default `["*"]`),
`allow_methods=["*"]`, `allow_headers=["*"]`, `allow_credentials=False`
(spec-correct alongside the `*` origin).

### Error mapping

| Cause                                              | HTTP status                |
|----------------------------------------------------|----------------------------|
| Missing / wrong-type request body field            | 422 Unprocessable Entity   |
| URL the classifier can't parse / unsupported       | 400 Bad Request            |
| Empty `url` string                                 | 400 Bad Request            |
| Extraction failure (network etc.)                  | 200 with `error` field set |
| LLM / Chroma exception                             | 500 Internal Server Error  |

The extraction-error case stays 200 deliberately — the iOS client may
still want to display the title/metadata even when the body fetch failed.

### Live verification (2026-06-01)

```
GET  /api/health                       → 200 {"status":"ok","items_indexed":3}
GET  /api/categories                   → 200 {"categories":["Programming","Travel"]}
POST /api/search "vietnam nature…"     → 200 Ha Long Bay first (dist 0.698)
POST /api/search +category=Programming → 200 only FastAPI + Django returned
POST /api/ingest {url:"not-a-url"}     → 400 (classifier rejected)
POST /api/ingest {}                    → 422 (pydantic validation)
POST /api/ingest wiki/Vietnam          → 200, LLM auto-reused "Travel", store 3→4
```

### Tests (tests/test_smoke.py — 18/18 pass)

API tests run via `fastapi.testclient.TestClient` against the real app
with `app.dependency_overrides[get_orchestrator]` swapped in to inject a
tempdir-backed store and a fake `_FakeLLM`. **No Ollama, no network.**

- `test_api_categories_endpoint_empty_store`
- `test_api_search_returns_hits_from_seeded_store` (incl. category filter)
- `test_api_ingest_bad_url_returns_400`
- `test_api_ingest_validation_error_returns_422`
- `test_api_health_returns_item_count`

### Config (src/config.py — env-prefix `SMART_SAVER_`)

| Setting              | Default                | Notes                                     |
|----------------------|------------------------|-------------------------------------------|
| `api_host`           | `127.0.0.1`            | Set to `0.0.0.0` for LAN / physical device |
| `api_port`           | `8000`                 |                                           |
| `api_cors_origins`   | `["*"]`                | One entry per allowed origin              |

### What needs to be done next

- **Auth / multi-user.** Currently single-user, no auth. Pre-shared bearer
  token is the lightest first step when this leaves the local machine.

---

## 6.8 Step 5 — iOS SwiftUI client + Share Extension

### Status: ✅ Source written (2026-06-01) — pending user-run Xcode build

All Swift sources for the iOS layer live under `ios/`. The actual
`.xcodeproj` is **not** committed; it is generated locally via
`xcodegen` from `ios/project.yml` (Path A) or built manually via the
Xcode wizard (Path B). See `ios/SETUP.md` for the full walk-through.

### Two artifacts ship inside `ios/`

| Target           | Type                | Bundle ID                                       | Role                                                                                           |
|------------------|---------------------|-------------------------------------------------|------------------------------------------------------------------------------------------------|
| `SmartSaver`     | iOS app (SwiftUI)   | `com.shakedivgi.smartsaver`                     | Dashboard: category grid + `.searchable` semantic search + Rich result rows w/ uncertainty UI |
| `ShareExtension` | iOS app-extension   | `com.shakedivgi.smartsaver.ShareExtension`      | Captures the shared URL from any host app, POSTs to `/api/ingest`, dismisses                  |

Both targets get the `NSAllowsLocalNetworking` ATS exception (set in
`project.yml`), which lets them call plain HTTP against `127.0.0.1` /
LAN / `.local` hosts without disabling app-wide ATS.

### Network contract

`NetworkManager.swift` is configured via `JSONDecoder(.convertFromSnakeCase)`
and `JSONEncoder(.convertToSnakeCase)`, so all Swift structs use idiomatic
camelCase (`isUncertain`, `itemsIndexed`, `existingCategories`, …) while
the wire format stays snake_case to match the Pydantic API models. The
Swift `HitMetadata` struct mirrors the flat metadata schema defined in
§6.6 — pipe-joined `alternativeCategories` and `technologies` are exposed
via the `…List` computed properties.

### Dynamic-categorisation UX (closes the loop on Step 2)

The iOS layer is what makes the `is_uncertain` flag user-actionable:

- `SearchResultRow` renders an **orange "Needs Disambiguation" capsule**
  badge AND outlines the whole card in orange whenever the server
  returned `metadata.is_uncertain == true`. The user sees these
  immediately and can tap into them to fix the category by hand.
- The Share Extension does **not** prompt at save time (would slow the
  share sheet to a crawl); it lets the LLM commit a best guess and
  surfaces uncertainty later, in the dashboard. This keeps shares
  one-tap-fast while preserving the disambiguation contract.

### How the user runs it (after `ios/SETUP.md` is followed)

```bash
# Terminal A — backend
./venv/bin/uvicorn src.api.main:app --reload         # 127.0.0.1:8000

# Terminal B — generate Xcode project (one-time / on file additions)
brew install xcodegen                                # one-time
cd ios && xcodegen generate
open SmartSaver.xcodeproj

# In Xcode:
#   scheme = SmartSaver
#   device = any iPhone Simulator (iOS 17+)
#   ⌘R
```

To test the Share Extension end-to-end inside the Simulator:
Safari → any URL → share icon → **Save to Smart Saver** → watch the
backend logs for an `/api/ingest` hit, then refresh the SmartSaver app
to see the new item.

### Physical device gotcha

`127.0.0.1` works only because the iOS Simulator shares the Mac's
loopback. On a real iPhone you must:

1. Bind the server to all interfaces: `uvicorn … --host 0.0.0.0`
2. Change `kDefaultAPIBaseURL` in `NetworkManager.swift` AND
   `kIngestEndpoint` in `ShareViewController.swift` to the Mac's LAN
   IP (`ipconfig getifaddr en0`).
3. Re-`xcodegen generate` and re-deploy.

`NSAllowsLocalNetworking` already covers LAN HTTP — no further ATS edits.

### What needs to be done next

- **Disambiguation flow.** Tap on an orange "Needs Disambiguation" row
  → open a sheet that PATCHes the corrected category back to a future
  `PATCH /api/items/{url}` endpoint. (Backend endpoint doesn't exist
  yet; the badge currently informs but doesn't act.)
- **App Group container** so the extension can share state with the
  app (e.g. cached categories, pending uploads when the server is down).

---

## 6.9 Step 6 — Async ingest via FastAPI BackgroundTasks

### Status: ✅ Implemented (2026-06-01)

### Why

Synchronous `/api/ingest` blocked the iOS Share Sheet for up to ~120 s
on a video (yt-dlp download + Whisper transcription + EasyOCR per
frame). That violates Apple's Share Extension UX expectations and
makes the app feel broken. Step 6 keeps the full pipeline intact — we
still extract video, audio, AND on-screen text via EasyOCR (which is
the whole point for Instagram Reels) — but moves it off the request
thread.

### Architecture

```
Client (iOS Share Ext.)
   │
   │ POST /api/ingest  { url, analyze, store, existing_categories? }
   ▼
FastAPI route ─────────────────────────────────────────────┐
   │                                                       │
   │ 1. classify(url)                                      │
   │    └─ UNKNOWN → 400 (fast-fail)                       │
   │                                                       │
   │ 2. orch.create_placeholder(url, source_type)          │
   │    └─ writes Chroma row with status="processing"      │
   │                                                       │
   │ 3. background_tasks.add_task(                         │
   │       orch.process_in_background, url, …              │
   │    )                                                  │
   │                                                       │
   │ 4. return placeholder (HTTP 202 Accepted)             │
   └───────────────────────────────────────────────────────┘
            │
            ▼ (Starlette runs background tasks after the response)
   orchestrator.process_in_background(url):
      try:    ingest()   # extract → analyze → store (upsert, status="completed")
      except: store.mark_failed(url, reason)
```

Total wall-clock time from share tap to "Saved!" pill on iOS:
**~600 ms** (network round-trip + placeholder write), regardless of
how long the heavy pipeline takes.

### Status lifecycle

| Value         | Set by                              | Visible on iOS as                     |
|---------------|-------------------------------------|---------------------------------------|
| `"processing"`| `add_placeholder` (immediate)       | Yellow "Processing…" pulsing pill + yellow card outline |
| `"completed"` | `add_item` after background success | Normal row (category + tags + summary) |
| `"failed"`    | `mark_failed` after BG exception    | Red "Failed" pill + red card outline + error string in `summary` |

Both `add_placeholder` and `add_item` upsert by URL, so the same
Chroma row transitions in-place — no duplicates accumulate.

### What got changed

| File                                     | Change                                                                           |
|------------------------------------------|----------------------------------------------------------------------------------|
| `src/schemas.py`                         | `IngestionResult.status: str = "completed"` field                                |
| `src/storage/vector_store.py`            | `add_placeholder`, `mark_failed`; `status` in metadata; `get_all_categories` filters out `processing` rows |
| `src/orchestrator.py`                    | `create_placeholder`, `process_in_background` (never raises — wraps `mark_failed` on error) |
| `src/api/main.py`                        | `/api/ingest` returns 202, accepts `BackgroundTasks`, schedules heavy work       |
| `ios/SmartSaver/Models/APIModels.swift`  | `HitMetadata.status: String?`                                                    |
| `ios/SmartSaver/Views/SearchResultRow.swift` | `ProcessingBadge` (pulse) + `FailedBadge`; coloured card outline picks up `status`/`isUncertain` |

### Tests (tests/test_smoke.py — 22/22 pass)

- `test_api_ingest_returns_202_with_placeholder_and_schedules_background` —
  asserts 202 + placeholder JSON shape + spy confirms BG task fired.
- `test_api_ingest_placeholder_hides_from_categories` — synthetic
  `"Processing"` category never leaks into `/api/categories`.
- `test_vector_store_add_placeholder_then_mark_failed` — storage
  lifecycle: processing → failed, summary carries the error.
- `test_vector_store_completed_replaces_placeholder` — `add_item`
  promotes a placeholder to `completed` without duplicating the row.

Spy pattern: in tests, `IngestionOrchestrator.process_in_background`
is monkeypatched on the test instance so the BG task is observable
without actually running yt-dlp / Whisper / Ollama / network.

### Concurrency notes

- `LLMAnalyzer` uses `ollama.Client` (httpx under the hood) — thread-safe.
- `VectorStoreManager` wraps a `PersistentClient` — its `Collection`
  operations are thread-safe within a process.
- `VideoExtractor` creates a fresh `uuid`-named temp dir per call, so
  concurrent video downloads cannot collide.
- `WhisperModel` and `easyocr.Reader` are loaded *per-call* inside
  `VideoExtractor`. Under high concurrent share rate this re-pays the
  ~10 s warmup. Future optimisation: cache them at module scope.

---

## 6.15 Step 11 — FB cleanup, manual ingestion, smart category deletion

### Status: ✅ Implemented + xcodebuild-verified (2026-06-01)

### 1. Facebook scraping path removed

Anonymous FB scraping was never reliable and the URL shapes kept
shifting (Steps 8 / 9 / 10 each chased a different breakage). Step 11
takes the whole path out:

| File                                  | What was removed                                                                                        |
|---------------------------------------|---------------------------------------------------------------------------------------------------------|
| `src/utils/url_classifier.py`         | `facebook.com` entry from `_MIXED_HOST_VIDEO_PATTERNS`; `fb.watch` from `_VIDEO_HOSTS`; FB-only tracking params (`mibextid`, `rdid`, `_rdr`, `fbclid`, `ref_*`) from `_TRACKING_PARAMS` |
| `src/extractors/article.py`           | `_parse_og_tags()` helper; the og-tag fallback strategy in `extract()`; the `Sec-Fetch-*` / `Upgrade-Insecure-Requests` browser-mimicry headers added specifically for FB |
| `tests/test_smoke.py`                 | All FB-targeted tests; the og-tag test; sanitize tests that asserted FB-specific params |

Shared FB links now fall through to the article extractor, which will
either succeed (rare, og-tag-driven sites without anti-bot) or surface
as a clean **red "Failed"** row in the iOS UI thanks to the Step 9
hardened pipeline. No more silent stuck-Processing.

The `sanitize_url` function itself stays — it's still useful for
stripping universal tracking params (`utm_*`, `gclid`, `igshid`,
`si`, `share_app_id`, etc.).

### 2. Manual ingestion — POST /api/items

A new dedicated route for "I want to save this thing myself, skip the
extractor". Use cases: auth-walled sources, scratch-pad links the user
wants searchable, items copy-pasted from places the share extension
can't reach.

```
POST /api/items                 status: 201 Created
  body: { url, title, summary, category }
  returns: full IngestionResult with status="completed"
```

Implementation:

- `IngestionOrchestrator.create_manual_item(url, *, title, summary, category)` builds a synthetic `IngestionResult` (ArticleResult body + AnalysisResult carrying the user-chosen category) and calls `store.add_item`
- Extractor and LLM are **never invoked** — the row lands at `status="completed"` immediately, no background task scheduled
- Embedded document for search = `title + summary`, so the row is semantically discoverable from the dashboard
- `sanitize_url` runs at the boundary so this share-sheet-canonical id de-dupes against future shares of the same link

### 3. Manual ingestion — iOS

A `+` button in the navigation bar's **leading** position. Tapping
opens `AddItemSheet`:

```
┌──────────────────────────────────┐
│ Cancel        Add Item      Save │
│                                  │
│ Link                             │
│  ┌────────────────────────────┐  │
│  │ https://…                  │  │
│  └────────────────────────────┘  │
│  Plain `example.com/foo` works…  │
│                                  │
│ Title                            │
│  ┌────────────────────────────┐  │
│  │ What is this?              │  │
│  └────────────────────────────┘  │
│                                  │
│ Summary                          │
│  ┌────────────────────────────┐  │
│  │ Why this matters…          │  │
│  └────────────────────────────┘  │
│                                  │
│ Category                         │
│  [Existing category ▼]           │
│  (or "New category…" → field)    │
└──────────────────────────────────┘
```

UX details:

- URL field auto-prepends `https://` if the user types a bare host
- Category picker shows every existing category + a "New category…"
  option that reveals a custom-text field
- Save button stays disabled until `url`, `title`, `category` are all
  non-empty
- On save, `DashboardViewModel.addManualItem(_:)` POSTs to
  `/api/items` then calls `refresh()` so the new row + new category
  chip appear instantly

### 4. Smart category deletion

Replaced the single-button delete alert with a `.confirmationDialog`
offering three outcomes:

```
Delete "Tech Tools"?
─────────────────────────────────────
 Move items to General
 Delete all content       (destructive)
 Cancel
─────────────────────────────────────
"Items in 'Tech Tools' can be moved
 to a General bucket, or deleted along
 with the category."
```

- **Move items to General** → calls existing `PATCH /api/categories`
  with `new_name="General"`. The bulk-rename is atomic — items keep
  all their other metadata (title, summary, embedding) and only their
  `category` field flips. The old category disappears from
  `/api/categories` since no rows match it any more.
- **Delete all content** → calls existing `DELETE /api/categories`
  which cascades (every row whose category matches gets removed).
- **Cancel** → no-op.

No new backend endpoints needed for this — `PATCH` + `DELETE` on
`/api/categories` from §6.11 already cover both outcomes.

### Files touched

| File                                                | Change |
|-----------------------------------------------------|--------|
| `src/utils/url_classifier.py`                       | FB regex + FB-only tracking params removed |
| `src/extractors/article.py`                         | og-tag fallback + Sec-Fetch headers removed; simpler header set |
| `src/orchestrator.py`                               | New `create_manual_item()` method |
| `src/api/main.py`                                   | New `POST /api/items` endpoint + `ManualItemRequest` model |
| `ios/SmartSaver/Models/APIModels.swift`             | New `ManualItemRequest` Codable struct |
| `ios/SmartSaver/Services/NetworkManager.swift`      | New `createManualItem(...)` async method |
| `ios/SmartSaver/Views/AddItemSheet.swift` (new)     | Sheet for the `+` button |
| `ios/SmartSaver/Views/ContentView.swift`            | `+` toolbar button; `addManualItem` + `moveCategoryToGeneral` VM methods; 3-button `confirmationDialog` for delete |

### Tests (tests/test_smoke.py — 37/37 pass)

Three new tests for Step 11:

- `test_api_create_manual_item_round_trip` — POST /api/items returns
  201, row at status="completed", category visible, **background task
  spy is empty** (confirms extractor / LLM bypass)
- `test_api_create_manual_item_validates_required_fields` — missing
  title / empty URL / etc. → 422
- `test_smart_category_delete_move_to_general_via_rename` — PATCH
  with `new_name="General"` moves 2 items, count stays at 3, old
  category disappears from `/api/categories`

Also: two orchestrator-failure tests previously used FB URLs that no
longer classify as VIDEO; switched to YouTube URLs since they test
the orchestrator's failure handling, not FB specifically.

### Verified

- `python tests/test_smoke.py` → 37/37 passed
- `xcodebuild … -destination "generic/platform=iOS Simulator" build` → BUILD SUCCEEDED

### What needs to be done next

- **Optional**: a `General` category default-icon (`folder.fill` or
  similar) so the smart-delete move feels less like an internal label
  and more like a curated bucket.
- **Optional**: undo banner after "Move to General" — a 5-second
  Snackbar that re-renames the items back if the user changes their
  mind. Trivially implementable now that the backend operation is
  atomic and reversible.

---

## 6.14 Step 10 — Bare-`?` URL fix + new FB `/share/<id>/` routing

### Status: ✅ Implemented + tests pass (2026-06-01)

Live bug report from the user's log showed two FB URLs returning 400
Bad Request:

```
HTTPError: 400 Client Error: Bad Request for url:
    https://www.facebook.com/share/1BHD8k4Bah/
HTTPError: 400 Client Error: Bad Request for url:
    https://www.facebook.com/share/p/18ZQaWYLjS/
```

### Bug A — bare `?` left at end of URL

The iOS share-sheet emits FB URLs like
`https://www.facebook.com/share/<id>/?mibextid=…`. `sanitize_url`
correctly stripped `mibextid` but then short-circuited:

```python
if not parsed.query:
    return url           # ← returns the original string, bare `?` and all
```

…leaving the URL as `…/share/<id>/?`. FB's parser 400s on that exact
shape.

Fix: always re-emit through `urlunparse`, which drops the orphan `?`
when query is empty. Now:

```
https://www.facebook.com/share/1BHD8k4Bah/?      → https://www.facebook.com/share/1BHD8k4Bah/
https://www.facebook.com/share/v/abc/?mibextid=x → https://www.facebook.com/share/v/abc/
```

### Bug B — new FB `/share/<id>/` share format

FB's iOS app stopped emitting the explicit `/share/v/<id>/` /
`/share/r/<id>/` markers and now ships bare `/share/<id>/` URLs that
HTTP-redirect to either a video or a post. My regex required the
`[vr]` subpath, so these landed in `ArticleExtractor` → 400.

Fix: regex now matches `/share/(?!p/)[^/]+/` — every share path
**except** `/share/p/`. yt-dlp gets the first shot at following the
redirect; `/share/p/` (the explicit text-post wrapper) still routes to
the article path.

```
/share/<random-id>/   → VIDEO   (new — was ARTICLE before)
/share/v/<id>/        → VIDEO   (unchanged)
/share/r/<id>/        → VIDEO   (unchanged)
/share/p/<id>/        → ARTICLE (unchanged — explicit text marker)
```

### Bonus — full modern-Chrome header set

`ArticleExtractor._fetch_html` now sends the complete request-header
set a real Chrome navigation produces: `Accept`, `Accept-Language`,
`Accept-Encoding`, `Upgrade-Insecure-Requests`, `Sec-Fetch-Dest`,
`Sec-Fetch-Mode`, `Sec-Fetch-Site`, `Sec-Fetch-User`, `Cache-Control`.
Facebook's bot filter specifically checks `Sec-Fetch-*` to verify the
request looks like a real navigation, so adding them measurably
reduces the 400 rate on text posts.

### Files touched

| File | Change |
|---|---|
| `src/utils/url_classifier.py` | `sanitize_url` always re-emits via `urlunparse`; FB regex uses `(?!p/)[^/]+/` negative lookahead |
| `src/extractors/article.py` | Full modern-Chrome header set |

### Tests (tests/test_smoke.py — 40/40 pass)

- `test_sanitize_url_strips_bare_trailing_question_mark` — regression
  for Bug A
- `test_classifier_routes_new_fb_share_id_format_to_video` — regression
  for Bug B, covers `/share/<id>/`, `/share/<id>/?`, `/share/p/<id>/`,
  `/share/v/<id>/`, `/share/r/<id>/`

### Limitation that remains

`/share/p/<id>/` is correctly classified as ARTICLE but FB still
returns 400 for anonymous reads of many text posts. Without auth
cookies we cannot pull the body. The new headers help on some posts;
others stay walled off and end up as red "Failed" rows — which is the
correct behavior (no more silent stuck-processing rows; the user sees
the failure with the reason in the summary).

Future work: a `cookies-from-browser` flag in `run_dev.py` that pipes
Safari/Chrome cookies into `requests` would unlock auth-walled posts
for the local dev box. Out of scope today.

### Verified

- `python tests/test_smoke.py` → 40/40 passed
- `xcodegen generate` → project rebuilt (no Swift changes needed)

---

## 6.13 Step 9 — Stuck-Processing fix, inline category buttons, TikTok lock-in

### Status: ✅ Implemented + xcodebuild-verified (2026-06-01)

### Bug 1 — FB rows stuck in "Processing" forever (root cause + fix)

The real bug, traced end-to-end:

1. iOS Share Sheet POSTs a FB URL → `/api/ingest`
2. Placeholder row written with `status="processing"`, 202 returned
3. Background task runs `IngestionOrchestrator.ingest()`
4. `VideoExtractor.extract()` calls yt-dlp → yt-dlp fails (auth wall /
   tracking-param confusion) → returns a `VideoResult` with
   `metadata["error"]="yt_dlp_failed"` **but does not raise**
5. `LLMAnalyzer.analyze()` is called on empty content; it returns the
   "no usable text" `_EMPTY_INPUT_FALLBACK` (not an exception)
6. Back in `ingest()`, `add_item()` is called — and refuses, because
   `aggregated_text` is empty
7. `ingest()` returns normally. `process_in_background` sees no
   exception, no `result.error` on the envelope, calls neither
   `add_item` (already refused) nor `mark_failed`
8. **Row stays at `status="processing"` forever.**

Three layers of fix:

| Layer | Change |
|-------|--------|
| `sanitize_url()` | Strip `mibextid`, `fbclid`, `igshid`, `si`, `utm_*`, `share_app_id`, `is_from_webapp`, etc. *before* the URL hits the classifier or yt-dlp. The same FB reel from FB Web, FB Mobile, and the iOS share-sheet now collapse onto one canonical id. |
| Classifier | `/share/v/`, `/share/r/` → VIDEO; `/share/p/` stays ARTICLE. TikTok hosts (`tiktok.com`, `vm.tiktok.com`, `vt.tiktok.com`) explicitly in `_VIDEO_HOSTS`. |
| `process_in_background` | **Empty-result detection**: if `aggregated_text` is empty, call `mark_failed`. **Extractor-error surface**: if `result.video.metadata["error"]` or `result.article.metadata["error"]` is set, call `mark_failed`. **Outer `except BaseException`** covers any crash (including SIGTERM / KeyboardInterrupt). **`finally` guard** double-checks the row's status and force-flips any leftover `processing` row to `failed` — so this class of bug can never recur even if a future code path skips a branch. |

Result: a placeholder is now **guaranteed** to transition out of
`processing` to either `completed` or `failed` before the background
task returns. The iOS UI flips the row to a red "Failed" badge with
the reason in the `summary` field instead of spinning forever.

### Bug 2 — Category long-press misattribution replaced with explicit buttons

The long-press / `.contextMenu` approach is gone for good. CategoryCard
now renders inline pencil + trash icon buttons on the trailing edge:

```
┌───────────────────────────────────────────────────┐
│ 🏠  Real Estate          [3]    [✏️]  [🗑️]      │   ← per category
└───────────────────────────────────────────────────┘
```

Implementation details that prevent the original hit-test bug:

- Card body uses `.onTapGesture` for select-filter (no outer `Button`
  wrapping the whole cell)
- Pencil / trash are independent `Button(.plain)` views; their tap
  consumes the gesture and never bubbles up to the outer card tap
- Each closure captures `cat` literally at construction time
- No grid-level `.contextMenu`, no `LazyVGrid` gesture-attribution
  fragility

### Edit category — sheet with SF Symbol picker

Rename moved from an alert into a full `EditCategorySheet`:

- Text field for new name (rename fires `PATCH /api/categories`)
- 30-symbol curated SF Symbol palette ('tag.fill', 'house.fill',
  'hammer.fill', 'figure.run', 'rocket.fill', etc.)
- "Use default icon" button to clear an override
- Per-category icon stored in `UserDefaults` via `CategoryIconStore`
  (`@MainActor final class CategoryIconStore: ObservableObject`)
- On rename, the override migrates with the category — your custom
  icon follows the new name automatically

The backend stays oblivious — it only stores category names. Icon
customisation is purely local-device state.

### Files touched

| File                                                       | What changed |
|------------------------------------------------------------|--------------|
| `src/utils/url_classifier.py`                              | New `sanitize_url()`; FB `/share/[vr]/` patterns; `vt.tiktok.com` |
| `src/api/main.py`                                          | `sanitize_url()` called at the request boundary |
| `src/orchestrator.py`                                      | `process_in_background` hardened — empty-result detection, extractor-error surface, `except BaseException`, `finally` force-fail guard, `_mark_failed_safely` helper |
| `ios/SmartSaver/Services/CategoryIconStore.swift` (new)    | `ObservableObject` persisting icon overrides in UserDefaults |
| `ios/SmartSaver/Views/CategoryCard.swift`                  | Drops contextMenu, uses `.onTapGesture` + inline pencil/trash Buttons; reads custom SF Symbol from icon store |
| `ios/SmartSaver/Views/EditCategorySheet.swift` (new)       | Sheet with TextField + 30-symbol palette |
| `ios/SmartSaver/Views/ContentView.swift`                   | Drops rename alert; `editingCategory: EditingCategory?` drives the sheet; injects `iconStore` via `.environmentObject` |

### Tests (tests/test_smoke.py — 38/38 pass)

Seven new tests:

- `test_url_classifier_facebook_share_wrapper`
- `test_url_classifier_tiktok_all_url_shapes`
- `test_sanitize_url_strips_tracking_params`
- `test_sanitize_url_preserves_meaningful_params`
- `test_classifier_is_robust_to_tracking_params_on_facebook`
- `test_process_in_background_flips_processing_to_failed_on_empty_extract`
- `test_process_in_background_flips_to_failed_on_unhandled_exception`

The last two are the regression tests for the stuck-Processing bug —
they inject a fake video extractor (one returns empty, one raises) and
assert the placeholder row ends in `status="failed"` either way.

### Verified at build time

```
xcodebuild -project ios/SmartSaver.xcodeproj -scheme SmartSaver \
           -sdk iphonesimulator -destination "generic/platform=iOS Simulator" build
** BUILD SUCCEEDED **
```

### What needs to be done next

- **Stuck-row recovery on app start.** If the server crashed
  mid-pipeline before Step 9, there may be old rows still showing
  `processing`. A startup hook in `IngestionOrchestrator.__init__`
  could sweep them to `failed` on boot.
- **Retry button on Failed rows.** Tap a red row → re-POST to
  `/api/ingest` with the same URL. Trivial UI add now that the
  endpoint is idempotent on URL.

---

## 6.12 Step 8 — Category long-press fix + Facebook ingestion

### Status: ✅ Implemented + xcodebuild-verified (2026-06-01)

### Bug 1 — Category long-press targeting the wrong cell

Symptom (reported by the user): long-pressing any category card opened a
context menu that operated on a *different* (typically the last-rendered)
card, not the one being held.

Root cause: the `.contextMenu` was attached as a modifier on the
`ForEach` iteration body, outside `CategoryCard`'s own view tree. Inside
a `LazyVGrid`, SwiftUI's hit-testing for `.contextMenu` modifiers
attached at the iteration scope sometimes attributes the gesture to a
neighbour cell — it's a known fragility of grid-level modifiers.

Fix: moved the `.contextMenu` **inside** `CategoryCard.body`. The card
now accepts optional `onRename` / `onDelete` callbacks; ContentView
passes per-iteration closures that capture `cat` literally at the
moment the cell is constructed. Also added
`.contentShape(RoundedRectangle…)` so the long-press hit-region is
locked to the cell's visible rectangle before `.contextMenu` attaches.

### Bug 2 — Facebook share-sheet posts came back empty

Two improvements landed for Facebook (and any host that does the same
"Redirecting…" interstitial trick):

**URL classifier (`src/utils/url_classifier.py`):**
- New regex covers `/watch`, `/reel`, `/reels`, `/videos/<id>`,
  `/video/<id>`, and `/<user>/videos/<id>` — all → `SourceType.VIDEO`,
  so they go through `yt-dlp + Whisper + EasyOCR(MPS)`.
- Posts and profile pages (`/<user>`, `/<user>/posts/<id>`) stay on
  `SourceType.ARTICLE`.
- `_normalize_host` now strips `m.`, `mobile.`, `web.` in addition to
  `www.` so `m.facebook.com` classifies identically to `facebook.com`.

**ArticleExtractor (`src/extractors/article.py`):**
- Default `http_user_agent` upgraded to a modern Chrome string (Chrome
  131 on macOS). FB downgrades responses for anything that looks like a
  bot, and our previous "SmartSaver/0.1" UA was tripping that filter.
- Added `Accept-Language: en-US,en;q=0.9` + the full `Accept:` header
  so the response matches what a real browser would receive.
- **New og-tag fallback strategy.** The extract pipeline is now:
    1. Trafilatura (best for real articles)
    2. **Open Graph meta tags** — works when the body is JS-rendered
       or behind a paywall; FB / IG / X / most CMSes always leave
       `og:title`, `og:description`, `og:image`, `og:site_name`
       readable for crawlers.
    3. BeautifulSoup paragraph join (last-ditch)
- The chosen strategy is recorded in `result.metadata["extractor"]`:
  `"trafilatura"`, `"og_tags"`, or `"beautifulsoup_fallback"`.

### What Facebook URLs do now

| URL shape                                          | Routed to | Pipeline                              |
|----------------------------------------------------|-----------|---------------------------------------|
| `facebook.com/watch/?v=…`, `/reel/…`, `/reels/…`   | VIDEO     | yt-dlp + Whisper + EasyOCR(MPS)       |
| `facebook.com/<user>/videos/…`, `/video/…`         | VIDEO     | yt-dlp + Whisper + EasyOCR(MPS)       |
| `fb.watch/<id>`                                    | VIDEO     | yt-dlp + Whisper + EasyOCR(MPS)       |
| `facebook.com/<user>/posts/…`, `/<user>`           | ARTICLE   | trafilatura → og-tags → BS4           |
| `m.facebook.com/…`, `mobile.facebook.com/…`        | (matches the same patterns above after normalization) |

### Tests (tests/test_smoke.py — 31/31 pass)

Three new tests:
- `test_url_classifier_facebook_videos_and_reels` — covers `/watch`,
  `/reel`, `/reels`, `/<user>/videos/`, `/<user>/video/`, `fb.watch`,
  and the `m.` mobile prefix
- `test_url_classifier_facebook_text_post_is_article` — `/posts/` and
  profile pages do NOT route to VIDEO
- `test_article_extractor_og_tag_fallback` — synthetic FB-like HTML
  with no body but populated og: tags round-trips into title +
  description + site_name + image

### Verified at build time

```
xcodebuild -project ios/SmartSaver.xcodeproj -scheme SmartSaver \
           -sdk iphonesimulator -destination "generic/platform=iOS Simulator" build
** BUILD SUCCEEDED **
```

### What needs to be done next

- **Instagram authenticated extraction.** yt-dlp 403s for many IG
  reels because we don't pass cookies. `--cookies-from-browser` would
  fix that for the local dev box.
- **TikTok parity.** TikTok works for yt-dlp metadata but the OCR
  pipeline often hits watermarked frames. Tightening the OCR
  min-confidence and adding a watermark-text deny-list would help.

---

## 6.11 Step 7 — Branding, "All" fix, item & category management

### Status: ✅ Implemented + xcodebuild-verified (2026-06-01)

### What landed in this step

| Layer | Files                                                                 | What it does |
|-------|-----------------------------------------------------------------------|--------------|
| Icon  | `tools/make_app_icon.py`, `ios/SmartSaver/Assets.xcassets/…`          | Generates the 1024×1024 PNG: solid white `bookmark.fill` silhouette on a deep-navy → vibrant-azure vertical gradient with off-center radial glow + soft drop shadow. Single-size AppIcon format (Xcode 14+). |
| Brand | `ContentView.swift` (`BookmarkLogo` + `Brand`)                        | SwiftUI re-creation of the icon (matching gradient + bookmark glyph) anchors the dashboard header. |
| Backend | `src/storage/vector_store.py`, `src/orchestrator.py`, `src/api/main.py` | 4 new operations: `delete_item`, `update_item`, `rename_category`, `delete_category`. |
| iOS   | `APIModels.swift`, `NetworkManager.swift`                             | Codable types + async wrappers for the 4 new endpoints. |
| iOS   | `ContentView.swift` (full rewrite), `CategoryCard.swift`, `EditItemSheet.swift` | List-based dashboard with swipe-to-delete, tap-to-edit, context menus, count chip on "All". |

### Backend — new endpoints

| Method | Path              | Body                                | Response                          | Codes |
|--------|-------------------|-------------------------------------|-----------------------------------|-------|
| DELETE | `/api/items`      | `{url}`                             | `{url, deleted: bool}`            | 200 / 404 / 500 |
| PATCH  | `/api/items`      | `{url, title?, summary?, category?}`| `{url, updated: bool, item: SearchHit?}` | 200 / 400 (no fields) / 404 / 500 |
| PATCH  | `/api/categories` | `{old_name, new_name}`              | `{affected: int}`                 | 200 / 400 (same names) / 500 |
| DELETE | `/api/categories` | `{name}`                            | `{affected: int}`                 | 200 / 500 |

Both `/api/items` routes operate on the URL-keyed Chroma row. `PATCH`
never re-embeds — only metadata is rewritten, search relevance stays
stable. `update_item` returns the post-mutation `SearchHit` so the iOS
client can patch its visible row without a re-fetch.

Category operations are bulk-update / bulk-delete by exact-string match
against the metadata `category` field. Rename moves N rows; delete
removes N rows.

### iOS — UI workflow

**Branding header** anchors the dashboard:
```
+-----------------------------+
| [📑] Smart Saver            |
|      Your second brain…     |
+-----------------------------+
```
The bookmark tile uses the same gradient as the home-screen icon
(`Brand.logoGradient`), giving the app a consistent identity from
icon → splash → in-app header.

**"All" fix** — the All chip now:
- shows a count chip with `vm.itemsIndexed` on its trailing edge
- on tap, runs `selectCategory(nil)` which fetches the whole library
  via a `everything`/`category=nil` probe at `limit=100`
  (previously this cleared the list, which is what the user reported)

**Swipe gestures** on each result row:
- **Trailing swipe** → red **Delete** button → optimistic `DELETE /api/items`
- **Leading swipe** → blue **Edit** button → opens the edit sheet
- Both work via `.swipeActions(...)` — requires the row to be in a `List`,
  which is why ContentView was restructured away from ScrollView+LazyVStack.

**Tap a row** → opens `EditItemSheet` with:
- Title (`TextField`, 1-3 line auto-grow)
- Summary (`TextField` axis=.vertical, 2-8 lines)
- Category (`Picker` over existing categories, plus a "Custom…" slot
  that reveals a TextField for inventing a new category)
- "Open in Safari" link + the URL displayed in monospaced caption
- Save → `PATCH /api/items` with only the fields that actually changed

**Long-press a CategoryCard** → context menu:
- **Rename** → SwiftUI alert with TextField → `PATCH /api/categories`
- **Delete category** → confirmation alert → `DELETE /api/categories`

**Optimistic UI everywhere** — delete drops the row from `hits`
immediately and decrements `itemsIndexed`; failure rolls back via
`refresh()`. Saves patch the row in place using the response's
`item` field so no extra fetch is needed.

### Tests (tests/test_smoke.py — 28/28 pass)

The six new tests cover both the storage layer and the HTTP surface:

- `test_vector_store_delete_item_and_404_on_missing`
- `test_vector_store_update_item_patches_fields_in_place`
- `test_vector_store_rename_and_delete_category_bulk`
- `test_api_delete_item_endpoint_round_trip`
- `test_api_patch_item_endpoint_round_trip`
- `test_api_category_rename_and_delete_endpoints`

All round-trip through the real `VectorStoreManager` in a tempdir, so
the persistence + bulk-update logic is covered end-to-end.

### Verified at build time

```
xcodebuild -project ios/SmartSaver.xcodeproj -scheme SmartSaver \
           -sdk iphonesimulator -destination "generic/platform=iOS Simulator" build
** BUILD SUCCEEDED **
```

### What needs to be done next

- **Per-category counts** — currently only "All" shows a count. Easy
  win: add `GET /api/categories?with_counts=true` returning
  `[{name, count}]` and render the chip on every CategoryCard.
- **Undo for delete** — single-tap restore via a Toast banner is the
  standard mobile pattern. Today a wrong swipe means re-ingesting.
- **In-place category move on long-press of a row** — context menu →
  "Move to category" → quick picker without opening the full edit sheet.

---

## 6.10 Step 6 (cont.) — `run_dev.py` + physical iPhone deployment

### `run_dev.py` — one-shot dev orchestrator

```bash
# Default — physical iPhone over Wi-Fi
python run_dev.py
#   • detects the Mac's LAN IP (UDP-socket trick)
#   • regex-patches the two Swift constants:
#       ios/SmartSaver/Services/NetworkManager.swift  → kDefaultAPIBaseURL
#       ios/ShareExtension/ShareViewController.swift  → kIngestEndpoint
#   • runs `xcodegen generate` (if anything actually changed)
#   • starts uvicorn bound to 0.0.0.0:8000

# Simulator mode (loopback only)
python run_dev.py --simulator

# Patch + xcodegen, don't start the server
python run_dev.py --no-server

# Different port
python run_dev.py --port 8123
```

The Mac's LAN IP can change when you join a different Wi-Fi or your
router re-issues a DHCP lease — just re-run `python run_dev.py`. The
script is idempotent and skips xcodegen when no Swift change happened.

### Physical iPhone setup (one-time)

**On the iPhone:**
1. Settings → Privacy & Security → **Developer Mode** → **ON**
   - iOS restarts; after the restart, accept the prompt to confirm
2. Plug iPhone into the Mac via USB-C/Lightning
3. iPhone asks **"Trust This Computer?"** → **Trust** → enter passcode
4. Stay on the same Wi-Fi network as the Mac

**On the Mac, in Xcode:**
1. Open `ios/SmartSaver.xcodeproj`
2. Top bar device picker → select your iPhone (no longer says
   "Simulator")
3. Project navigator → `SmartSaver` target → **Signing & Capabilities**
   - Team: pick your personal team (free Apple ID works — Xcode →
     Settings → Accounts to add it)
   - Bundle Identifier may already collide if multiple people use the
     same one — change the suffix (e.g.
     `com.shakedivgi.smartsaver.<your-initials>`)
   - Do the same for the `ShareExtension` target (its Bundle ID must
     stay a child of the app's, e.g. `…ShareExtension`)
4. **Product → Clean Build Folder** (⇧⌘K)
5. **⌘R** → Xcode builds, installs onto the iPhone, launches

**First-time trust dance on the iPhone:**
- iOS shows **"Untrusted Developer"** when the app first launches
- On iPhone → Settings → General → **VPN & Device Management** →
  tap your Apple ID under "Developer App" → **Trust "Apple ID …"**
- Confirm the dialog
- Re-launch the app from the home screen

### End-to-end share test (physical device)

1. **On the Mac:** `python run_dev.py` (leave terminal running)
2. **On the iPhone:** open Safari → any URL → tap share icon →
   scroll the bottom row → **More** → toggle "Save to Smart Saver" ON
   (one-time per app install)
3. Tap **Save to Smart Saver**
4. Expected: spinner → "Saved!" green flash → sheet dismisses, all in
   **under 1 second** (no longer the 30-120 s freeze)
5. Open the SmartSaver app → pull-to-refresh → the new item shows
   with a yellow **Processing…** pulsing badge for a few seconds, then
   pull-to-refresh again to see it flip to a real category with full
   summary + tags

If the spinner hangs > 10 s: the iPhone can't reach the Mac. Check:
- `python run_dev.py` is still printing logs (server up)
- iPhone and Mac on the same Wi-Fi SSID
- Mac firewall (System Settings → Network → Firewall) is OFF or
  allows incoming connections on port 8000

### Switching back to the Simulator

```bash
python run_dev.py --simulator
# This reverts both Swift constants to http://127.0.0.1:8000,
# runs xcodegen, and starts uvicorn on loopback.
# Then ⌘R in Xcode against a Simulator destination.
```

### What needs to be done next

- **Server-sent events (SSE) for status updates.** Today the iOS
  client must pull-to-refresh to learn a placeholder became
  `completed`. An SSE stream on `GET /api/events` would push the
  status flip immediately.
- **Worker isolation.** Heavy ingests share the uvicorn process with
  fast endpoints (`/api/search`, `/api/categories`). Under heavy
  share load this could starve reads. Move background tasks to a
  dedicated process / queue (Celery / arq / RQ).
- **Auth.** Currently anyone on the LAN can hit `/api/ingest`. A
  pre-shared bearer token in `Authorization:` is the smallest first
  step.

---

## 7. Update protocol

When you (future Claude or future me) finish a meaningful chunk of work:

1. Bump the **Status** line under the relevant step.
2. Move done items out of "What needs to be done next".
3. Add new files to the **Folder & File Structure** tree.
4. If a convention changed, edit Section 5 — do not leave stale rules.
