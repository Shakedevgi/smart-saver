# 📑 SmartSaver — AI-Powered Link Archiver

> **"Because your 'Saved' folder on Instagram is where links go to die, and your TikTok bookmarks are a digital hoarder's paradise."** 💀

**SmartSaver** is a full-stack personal knowledge system: share any link from your iPhone, and a local AI pipeline extracts the content, transcribes any audio, reads on-screen text via OCR, summarises everything, and files it under a dynamically-assigned category — in the background, privately, while you keep scrolling.

The server runs on your Mac (or any machine), tunnelled to the public internet via **ngrok** so the iOS app works on cellular anywhere in the world.

<img width="18%" alt="MainScreen" src="https://github.com/user-attachments/assets/3077f9a9-66ed-4433-8eb4-1b3a91a1cb82" /> <img width="18%" alt="IGfilter" src="https://github.com/user-attachments/assets/c9a879b8-45f2-4d53-9465-d047788f7abf" />
<img width="18%" alt="fullshare" src="https://github.com/user-attachments/assets/d5e1b9dc-8de1-4e48-9bfa-1b4dbfcb24a0" />
<img width="18%" alt="Saving" src="https://github.com/user-attachments/assets/42950d05-a287-4a81-b45c-911b4389f117" />
<img width="18%" alt="afteradding" src="https://github.com/user-attachments/assets/d0ce8cfa-9995-438a-a7c6-3500f11ae7f9" />

## 🚀 Getting Started

### Prerequisites

- **Mac** (Apple Silicon recommended — faster Whisper + EasyOCR)
- **Xcode** with iOS 17+ SDK
- **Homebrew** — `brew install xcodegen ffmpeg`
- **Ollama** — install from [ollama.com](https://ollama.com), then `ollama pull llama3`
- **ngrok** — install from [ngrok.com/download](https://ngrok.com/download), then authenticate once:
  ```bash
  ngrok config add-authtoken <your-token>   # token at dashboard.ngrok.com
  ```

### 1. Python backend

```bash
git clone https://github.com/Shakedevgi/smart-saver.git
cd smart-saver

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Start the dev orchestrator

```bash
python run_dev.py          # ngrok default — works on cellular everywhere
python run_dev.py --local  # LAN Wi-Fi fallback (same network only)
python run_dev.py --simulator  # iOS Simulator (loopback)
```

`run_dev.py` does everything in one command:

1. Starts (or reuses) an ngrok tunnel on port 8000
2. Patches `NetworkManager.swift` and `ShareViewController.swift` with the public URL
3. Runs `xcodegen generate` if any Swift constants changed
4. Starts uvicorn bound to `0.0.0.0:8000`

### 3. Static ngrok domain (one-time, highly recommended)

ngrok's free plan gives you **one permanent static domain** — claim it at `dashboard.ngrok.com/domains`. Once you have it, update the `launch_ngrok()` call in `run_dev.py`:

```python
["ngrok", "http", "--domain=your-domain.ngrok-free.app", str(port)]
```

Run `python run_dev.py --no-server --no-xcodegen` once to patch the permanent URL into the Swift files, rebuild in Xcode, and deploy to your phone. You never need to rebuild because of a URL change again.

### 4. iOS build & deploy

```bash
open ios/SmartSaver.xcodeproj
```

- Select your iPhone (connect it to the mac for the first time set up) or Simulator in the Xcode scheme picker
- **⌘R** — Xcode automatically picks your registered personal team; no manual signing configuration needed
- First install: iPhone → Settings → General → **VPN & Device Management** → trust your Apple ID

### 5. Enable Developer Mode on iPhone (one-time)

Settings → Privacy & Security → **Developer Mode** → ON → restart → confirm.

---

## 🖥️ Keep the server running while away

For the app to work on cellular you just need your Mac running the server at home:

```bash
# Prevent the Mac from sleeping (run before python run_dev.py)
caffeinate -i python run_dev.py
```

System Settings → Battery → Options → **"Prevent automatic sleeping on power adapter when display is off"** → ON.

The ngrok tunnel (static domain) stays alive as long as the script runs. The iOS app works from anywhere — cellular, different Wi-Fi, abroad — with zero extra setup.

---

## 🧪 Tests

```bash
source venv/bin/activate
python tests/test_smoke.py
# 37/37 passed
```

Coverage: URL classification & sanitization · ChromaDB round-trip · semantic search & category filter · all `/api/*` endpoints · async pipeline lifecycle (`processing → completed / failed`) · manual ingestion · category bulk-rename / cascade-delete · background task failure handling.

---

## ✨ Features

| Feature | Detail |
|---|---|
| ⚡ Sub-second share sheet | `POST /api/ingest` returns `202 Accepted` in <1 s. Heavy work runs in a real OS thread so the event loop never blocks. |
| 🧠 Local semantic search | ChromaDB + ONNX MiniLM embeddings. Search your entire library with natural language. |
| 🏷️ Dynamic categorisation | The LLM reuses existing categories or invents a new one. No fixed taxonomy. Anti-lazy prompt engineering prevents lazy matching. |
| ⚠️ Disambiguation UI | Low-confidence items get an orange **"Needs Disambiguation"** badge and card outline for manual review. |
| 🌐 Source filter bar | One-tap pill filter: **All · Instagram · TikTok · YouTube · Article** — client-side, no extra network call. |
| 🕐 Chronological order | Browse view always shows newest saves at the top via `created_at` Unix timestamp. |
| ✏️ Full CRUD | Swipe-to-delete, tap-to-edit (title/summary/category), `+` button for manual ingestion, smart category deletion (move to General or cascade-delete). |
| 🎨 Premium dark UI | Midnight-blue gradient background, electric-blue accent (#3E86F8), branded card borders, crisp white typography. |
| 🔄 Status lifecycle | Every item transitions `processing → completed / failed` with matching badge colours (yellow pulse → normal / red). |

---

## 🛠️ Tech Stack

### Backend

| Layer | Technology |
|---|---|
| API | **FastAPI** + **uvicorn** (async, CORS, BackgroundTasks) |
| Background tasks | `asyncio.to_thread` — runs Whisper/EasyOCR in the OS thread pool so the event loop stays free |
| Vector DB | **ChromaDB** (persistent, `data/chroma/`) |
| Embeddings | ONNX `all-MiniLM-L6-v2` (bundled, ~80 MB, no extra deps) |
| Local LLM | **Ollama** + `llama3` — structured output via `format=<json_schema>` |
| Article extraction | **trafilatura** (primary) + BeautifulSoup fallback |
| Video metadata | **yt-dlp** (YouTube, TikTok, Instagram, X, …) |
| Audio transcription | **faster-whisper** (`base` model, CPU / Apple Silicon) |
| Video OCR | **EasyOCR** (frame sampling via OpenCV) |
| Data models | **Pydantic v2** |
| Tunnel | **ngrok** — permanent static domain, works on cellular |

### iOS

| Layer | Technology |
|---|---|
| Main app | **SwiftUI** (iOS 17+), NavigationStack, dark theme |
| Share Extension | **UIKit** `UIViewController` — captures URL from any host app |
| Networking | `URLSession` async/await, `JSONDecoder(.convertFromSnakeCase)` |
| Project generation | **XcodeGen** — `project.yml` → `.xcodeproj`, signing auto-selected |

---

## 🔄 Pipeline

```
iPhone Share Sheet
       │  tap "Save to Smart Saver"
       ▼
iOS Share Extension
       │  POST /api/ingest  { url }
       ▼
ngrok tunnel (HTTPS, public internet)
       │  cryptic-attire-statute.ngrok-free.dev
       ▼
FastAPI  →  202 Accepted  →  "Saved!" (< 1 s)
       │
       │  asyncio.to_thread (non-blocking)
       ▼
Extraction layer
   ├── ArticleExtractor   trafilatura → BS4 fallback
   └── VideoExtractor     yt-dlp → faster-whisper → EasyOCR
       │
       ▼
LLMAnalyzer (Ollama / llama3)
   • dynamic category  • summary  • key insights  • entities
       │
       ▼
VectorStoreManager (ChromaDB)
   status: processing → completed / failed
       │
       ▼
iOS Dashboard
   • newest-first chronological sort
   • source filter  (All / Instagram / TikTok / YouTube / Article)
   • semantic search across entire library
```

---


## ⚠️ Known Limitations

### Facebook
Facebook's aggressive anti-bot measures (tracking redirects, login walls) mean automated scraping of FB posts/reels is unreliable without auth cookies. Shared FB links are attempted through the standard pipeline; if they fail they land as red **"Failed"** rows. Use the **`+` manual ingestion** button as a fallback — paste the URL, add a title and summary, pick a category, done.

### Instagram & TikTok auth
Some IG Reels and TikTok videos require cookies for yt-dlp to download audio. Public content works; auth-walled content may fail.

### Whisper device
Whisper runs on CPU by default. `WHISPER_DEVICE=metal` is available for Apple Silicon but requires validating the wheel version.

---

## 🔮 Roadmap

- [ ] Server-sent events (SSE) to push `processing → completed` status updates to the iOS dashboard in real time (no pull-to-refresh needed)
- [ ] **Retry button** on red "Failed" rows — re-POST the same URL with one tap
- [ ] **Per-category item counts** shown on each category chip
- [ ] **App Group** shared container so the Share Extension can cache categories offline
- [ ] Cookie passthrough (`--cookies-from-browser`) for auth-walled IG/TikTok content
- [ ] Worker isolation — move heavy ingests to a dedicated process so `/api/search` and `/api/categories` are never starved

---

Developed by [Shaked Ivgi](https://github.com/Shakedevgi).
