# 📑 SmartSaver — AI-Powered Link Archiver

![Tests](https://github.com/Shakedevgi/smart-saver/actions/workflows/ci.yml/badge.svg)

> **"Because your 'Saved' folder on Instagram is where links go to die, and your TikTok bookmarks are a digital hoarder's paradise."** 

**SmartSaver** is a full-stack personal knowledge system: share any link from your iPhone or Android device, and a cloud AI pipeline extracts the content, transcribes any audio, reads on-screen text via OCR, summarises everything, and files it under a dynamically-assigned category — in under 20 seconds, while you keep scrolling.

The backend runs on **Google Cloud Run** — always alive, zero infrastructure to maintain.

<img width="18%" alt="MainScreen" src="https://github.com/user-attachments/assets/3077f9a9-66ed-4433-8eb4-1b3a91a1cb82" /> <img width="18%" alt="IGfilter" src="https://github.com/user-attachments/assets/c9a879b8-45f2-4d53-9465-d047788f7abf" />
<img width="18%" alt="fullshare" src="https://github.com/user-attachments/assets/d5e1b9dc-8de1-4e48-9bfa-1b4dbfcb24a0" />
<img width="18%" alt="Saving" src="https://github.com/user-attachments/assets/42950d05-a287-4a81-b45c-911b4389f117" />
<img width="18%" alt="afteradding" src="https://github.com/user-attachments/assets/d0ce8cfa-9995-438a-a7c6-3500f11ae7f9" />

---

## 📱 Platform Support

| Platform | Status | Notes |
|---|---|---|
| iOS (iPhone) | ✅ Production | SwiftUI app + Share Extension |
| Android | ✅ Production | Jetpack Compose app + Share Target |
| Backend (Cloud) | ✅ Production | FastAPI on Google Cloud Run |

---

## 🚀 Getting Started

### Prerequisites

- **Google Cloud** account with Cloud Run + Artifact Registry APIs enabled
- **Gemini API key** — create one at [aistudio.google.com](https://aistudio.google.com) (requires billing enabled)
- **Supabase** project with a `items` table and `pgvector` extension enabled
- **Python 3.11+** for local development / running tests
- **gcloud CLI** installed and authenticated

### 1. Clone and configure

```bash
git clone https://github.com/Shakedevgi/smart-saver.git
cd smart-saver
```

Required environment variables (set as Cloud Run secrets or a `.env` file for local dev):

```
SMART_SAVER_GEMINI_API_KEY=your_gemini_api_key
SMART_SAVER_SUPABASE_URL=https://xxxx.supabase.co
SMART_SAVER_SUPABASE_KEY=your_supabase_anon_or_service_key
```

### 2. Supabase schema (one-time)

Run this in the Supabase SQL editor:

```sql
create extension if not exists vector;

create table items (
  url         text primary key,
  status      text not null default 'processing',
  title       text,
  category    text,
  summary     text,
  source_type text,
  embedding   vector(768),
  metadata    jsonb,
  created_at  timestamptz default now()
);

create or replace function match_items(
  query_embedding vector(768),
  match_count     int default 10,
  filter_category text default null
)
returns setof items language plpgsql as $$
begin
  return query
  select * from items
  where status != 'processing'
    and (filter_category is null or category = filter_category)
  order by embedding <=> query_embedding
  limit match_count;
end;
$$;
```

### 3. Deploy to Cloud Run

```bash
# Build container image
gcloud builds submit \
  --tag europe-west1-docker.pkg.dev/<PROJECT>/cloud-run-source-deploy/smart-saver:latest \
  --project <PROJECT> --region europe-west1

# Deploy (keep one instance warm so background tasks aren't killed)
gcloud run deploy smart-saver \
  --image europe-west1-docker.pkg.dev/<PROJECT>/cloud-run-source-deploy/smart-saver:latest \
  --region europe-west1 \
  --min-instances 1 \
  --no-cpu-throttling \
  --set-env-vars SMART_SAVER_GEMINI_API_KEY=...,SMART_SAVER_SUPABASE_URL=...,SMART_SAVER_SUPABASE_KEY=... \
  --project <PROJECT>
```

`--min-instances=1 --no-cpu-throttling` is required: Cloud Run scales to 0 and throttles CPU after the 202 response, which would kill the still-running background pipeline.

### 4. Local development

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn src.api.main:app --reload  # runs on 127.0.0.1:8000
```

---

## ⚠️ Required: Add your backend URL to the mobile clients

After deploying to Cloud Run, get your service URL:

```bash
gcloud run services describe smart-saver --region <your-region> --format="value(status.url)"
```

Then replace `YOUR_CLOUD_RUN_URL_HERE` in these three files with your actual URL:

| File | Constant |
|------|----------|
| `ios/SmartSaver/Services/NetworkManager.swift` | `kDefaultAPIBaseURL` |
| `ios/ShareExtension/ShareViewController.swift` | `kIngestEndpoint` |
| `android/app/src/main/kotlin/com/shakedivgi/smartsaver/data/AppConfig.kt` | `API_BASE_URL` |

> **Do not commit your real URL.** The backend has no authentication — anyone with the URL can hit your endpoint and consume your Gemini API credits.

---

## 🍎 iOS Setup

### Build & deploy

```bash
brew install xcodegen ffmpeg
open ios/SmartSaver.xcodeproj
```

- Fill in `kDefaultAPIBaseURL` in `NetworkManager.swift` with your Cloud Run URL (see setup step above)
- Select your iPhone or Simulator in the Xcode scheme picker
- **⌘R** — Xcode automatically picks your registered personal team; no manual signing configuration needed
- First install: iPhone → Settings → General → **VPN & Device Management** → trust your Apple ID

### Enable Developer Mode on iPhone (one-time)

Settings → Privacy & Security → **Developer Mode** → ON → restart → confirm.

---

## 🤖 Android Setup

### Prerequisites

- **Android Studio 2024+** with Android SDK 34+
- **Java 17+** (Android Studio's bundled JBR works perfectly)

### Build from Android Studio

- Fill in `API_BASE_URL` in `AppConfig.kt` with your Cloud Run URL (see setup step above)
- Open the Android project in Android Studio — Gradle syncs automatically on first open
- Select your device in the device picker → **▶ Run**

### Build from the terminal

```bash
cd android

export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
export ANDROID_HOME="$HOME/Library/Android/sdk"

./gradlew assembleDebug --no-daemon

# Install + launch on a running emulator
$ANDROID_HOME/platform-tools/adb install -r app/build/outputs/apk/debug/app-debug.apk
$ANDROID_HOME/platform-tools/adb shell am start -n com.shakedivgi.smartsaver/.MainActivity
```

### Test the Android Share Target

1. Open **Chrome** inside the emulator → navigate to any URL
2. Tap ⋮ → **Share** → **Save to Smart Saver**
3. A bottom sheet appears with a spinner ("Saving to Smart Saver…")
4. On `202 Accepted` the sheet shows green "Saved!" and auto-dismisses in < 1 second
5. Open the SmartSaver app → pull to refresh → item appears with **Processing…** badge, then flips to its full card

---

## 🧪 Tests

```bash
make test
# 37/37 passed
```

Tests run automatically on every push via GitHub Actions (see the badge at the top).

Coverage: URL classification & sanitization · Supabase round-trip · semantic search & category filter · all `/api/*` endpoints · async pipeline lifecycle (`processing → completed / failed`) · manual ingestion · category bulk-rename / cascade-delete · background task failure handling.

---

## ✨ Features

| Feature | iOS | Android | Detail |
|---|---|---|---|
| ⚡ Sub-second share sheet | ✅ | ✅ | `POST /api/ingest` returns `202 Accepted` in <1 s. Heavy work runs in a Cloud Run background thread. |
| 🧠 Semantic search | ✅ | ✅ | Supabase pgvector + `gemini-embedding-001` (768-dim). Search your entire library with natural language. |
| 🏷️ Dynamic categorisation | ✅ | ✅ | Gemini 2.5 Flash reuses existing categories or invents a new one. No fixed taxonomy. |
| ⚠️ Disambiguation UI | ✅ | ✅ | Low-confidence items get an orange **"Needs Review"** badge for manual review. |
| 🌐 Source filter bar | ✅ | ✅ | One-tap pill filter: **All · Instagram · TikTok · YouTube · Article** — client-side, no extra network call. |
| 🕐 Chronological order | ✅ | ✅ | Browse view always shows newest saves at the top via `created_at` timestamp. |
| ✏️ Full CRUD | ✅ | ✅ | Swipe-to-delete, tap-to-edit (title/summary/category), add button for manual ingestion, smart category deletion. |
| 🎨 Premium dark UI | ✅ | ✅ | Midnight-blue gradient, electric-blue accent (#3E86F8), branded card borders. |
| 🔄 Status lifecycle | ✅ | ✅ | Every item transitions: `processing → completed / failed` with badge colours. |
| 🔁 Automatic retries | ✅ | ✅ | Gemini API 429 / 5xx errors retried up to 5× with exponential back-off via **Tenacity**. |
| 📂 Category management | ✅ | ✅ | Rename, delete, or move items to General — all synced to the backend. |

---

## 🛠️ Tech Stack

### Backend

| Layer | Technology |
|---|---|
| API | **FastAPI** + **uvicorn** (async, CORS, BackgroundTasks) |
| Hosting | **Google Cloud Run** — `min-instances=1`, `no-cpu-throttling` keeps background pipeline alive after 202 |
| Transcription | **Gemini 2.5 Flash** via Gemini File API — audio uploaded then transcribed in one API call |
| Analysis | **Gemini 2.5 Flash** — dynamic category + summary + key insights + entities (structured JSON via `response_schema`) |
| Embeddings | **gemini-embedding-001** — 768-dim vectors via direct REST call with `outputDimensionality: 768` |
| Vector DB | **Supabase** (PostgreSQL + `pgvector`) — `match_items()` RPC for semantic search |
| Video download | **yt-dlp** — `bestaudio` (for transcript) + `worstvideo[height<=360]` (for OCR) downloaded in parallel |
| Video OCR | **EasyOCR** (frame sampling via OpenCV) — detects on-screen text (place names, prices, captions) |
| Article extraction | **trafilatura** (primary) + BeautifulSoup fallback |
| Data models | **Pydantic v2** |
| Resilience | **Tenacity** — exponential back-off on 429/5xx; `JobStatus` state machine (`processing → completed / failed`) |

### iOS

| Layer | Technology |
|---|---|
| Main app | **SwiftUI** (iOS 17+), NavigationStack, dark theme |
| Share Extension | **UIKit** `UIViewController` — captures URL from any host app |
| Networking | `URLSession` async/await, `JSONDecoder(.convertFromSnakeCase)` |
| Project generation | **XcodeGen** — `project.yml` → `.xcodeproj`, signing auto-selected |

### Android

| Layer | Technology |
|---|---|
| Main app | **Jetpack Compose** + **Material3** — dark theme, midnight-blue gradient |
| Share Target | `Activity` with `ACTION_SEND` intent filter + translucent `ModalBottomSheet` |
| Networking | **OkHttp** + **Gson** (`LOWER_CASE_WITH_UNDERSCORES` field naming) |
| Architecture | **MVVM** — `ViewModel` + `StateFlow` + Kotlin coroutines |
| Build system | **Gradle Kotlin DSL** (`build.gradle.kts`) + Version Catalog (`libs.versions.toml`) |
| Min SDK | API 26 (Android 8.0) |
| Target SDK | API 36 |

---

## 🔄 Pipeline

```
iPhone / Android Share Sheet
       │  tap "Save to Smart Saver"
       ▼
iOS Share Extension  /  Android Share Activity
       │  POST /api/ingest  { url }
       ▼
Google Cloud Run — FastAPI
       │  202 Accepted → "Saved!" (< 1 s)
       │
       │  BackgroundTasks (runs after response, CPU always allocated)
       ▼
Extraction layer                          [status: processing]
   ├── ArticleExtractor   trafilatura → BS4 fallback
   └── VideoExtractor (parallel downloads)
         ├── yt-dlp bestaudio → Gemini File API upload → Gemini 2.5 Flash (transcript)
         └── yt-dlp low-res video → OpenCV frame sampling → EasyOCR (on-screen text)
       ▼
LLMAnalyzer (Gemini 2.5 Flash)
   • dynamic category  • summary  • key insights  • entities
   • structured JSON output enforced via response_schema
       ▼
VectorStoreManager (Supabase + pgvector)  [status: completed / failed]
   • gemini-embedding-001 → 768-dim vector
   • upsert by URL into `items` table
   • match_items() RPC for semantic search
       ▼
iOS Dashboard  /  Android Dashboard
   • newest-first chronological sort
   • source filter  (All / Instagram / TikTok / YouTube / Article)
   • semantic search across entire library
```

---

## ⚠️ Known Limitations

### Facebook
Facebook's aggressive anti-bot measures mean automated scraping of FB posts/reels is unreliable without auth cookies. Shared FB links are attempted through the standard pipeline; if they fail they land as red **"Failed"** rows. Use the **`+` manual ingestion** button as a fallback.

### Instagram & TikTok auth
Some IG Reels and TikTok videos require cookies for yt-dlp to download audio. Public content works; auth-walled content may fail.

### Gemini API rate limits
The pipeline retries on 429 errors with exponential back-off. Under heavy simultaneous share load you may see brief delays before an item completes.

---

## 🔮 Roadmap

- [ ] Server-sent events (SSE) to push live status updates to the mobile client (no pull-to-refresh needed)
- [ ] **Retry button** on red "Failed" rows — re-POST the same URL with one tap
- [ ] **Per-category item counts** shown on each category chip
- [ ] **App Group** shared container (iOS) so the Share Extension can cache categories offline
- [ ] Cookie passthrough (`--cookies-from-browser`) for auth-walled IG/TikTok content

---

Developed by [Shaked Ivgi](https://github.com/Shakedevgi).
