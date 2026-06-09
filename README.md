python run_dev.py --android-emulator or Android device, and a local AI pipeline extracts the content, transcribes any audio, reads on-screen text via OCR, summarises everything, and files it under a dynamically-assigned category — in the background, privately, while you keep scrolling.

The server runs on your Mac (or any machine), tunnelled to the public internet via **ngrok** so both mobile clients work on cellular anywhere in the world.

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
| Backend (Mac) | ✅ Production | FastAPI + ChromaDB + Ollama |

---

## 🚀 Getting Started

### Prerequisites

- **Mac** (Apple Silicon recommended — faster Whisper + EasyOCR)
- **Python 3.11+** and a virtual environment
- **Ollama** — install from [ollama.com](https://ollama.com), then `ollama pull llama3`
- **ngrok** — install from [ngrok.com/download](https://ngrok.com/download), then authenticate once:
  ```bash
  ngrok config add-authtoken <your-token>   # token at dashboard.ngrok.com
  ```

### 1. Python backend

```bash
git clone https://github.com/Shakedevgi/smart-saver.git
cd smart-saver

make setup       # creates venv + installs all dependencies
```

Or manually:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Start the dev orchestrator

```bash
make dev              # ngrok tunnel — works on cellular everywhere
make dev-local        # LAN Wi-Fi fallback (same network only)
make dev-sim          # iOS Simulator (loopback, 127.0.0.1)

# Android Emulator (patches AppConfig.kt to 10.0.2.2)
python run_dev.py --android-emulator
```

`make dev` / `run_dev.py` does everything in one command:

1. Starts (or reuses) an ngrok tunnel on port 8000
2. Patches `NetworkManager.swift`, `ShareViewController.swift` **and** `AppConfig.kt` with the public URL
3. Runs `xcodegen generate` if any Swift constants changed
4. Starts uvicorn bound to `0.0.0.0:8000`

Optional Android build flag:
```bash
python run_dev.py --android-emulator --android-build   # also runs gradlew assembleDebug
```

### 3. Static ngrok domain (one-time, highly recommended)

ngrok's free plan gives you **one permanent static domain** — claim it at `dashboard.ngrok.com/domains`. Once you have it, update the `launch_ngrok()` call in `run_dev.py`:

```python
["ngrok", "http", "--domain=your-domain.ngrok-free.app", str(port)]
```

Run `python run_dev.py --no-server --no-xcodegen` once to patch the permanent URL into the Swift **and** Kotlin files, rebuild both apps. You never need to rebuild because of a URL change again.

---

## 🍎 iOS Setup

### Build & deploy

```bash
brew install xcodegen ffmpeg
open ios/SmartSaver.xcodeproj
```

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

```bash
# 1. Start the backend pointing at the emulator loopback address
python run_dev.py --android-emulator

# 2. Open the Android project in Android Studio
open -a "Android Studio" android/
```

- Android Studio syncs Gradle automatically on first open
- Select your emulator in the device picker → **▶ Run**

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

### Physical Android device (LAN)

```bash
python run_dev.py --local    # patches AppConfig.kt to your Mac's LAN IP
```

Then build and deploy from Android Studio with your physical device selected.

---

## 🖥️ Keep the server running while away

For the app to work on cellular you just need your Mac running the server at home:

```bash
# Prevent the Mac from sleeping (run before make dev)
caffeinate -i make dev
```

System Settings → Battery → Options → **"Prevent automatic sleeping on power adapter when display is off"** → ON.

The ngrok tunnel (static domain) stays alive as long as the script runs. Both iOS and Android apps work from anywhere — cellular, different Wi-Fi, abroad — with zero extra setup.

---

## 🧪 Tests

```bash
make test
# 37/37 passed
```

Tests run automatically on every push via GitHub Actions (see the badge at the top).

Coverage: URL classification & sanitization · ChromaDB round-trip · semantic search & category filter · all `/api/*` endpoints · async pipeline lifecycle (`processing → completed / failed`) · manual ingestion · category bulk-rename / cascade-delete · background task failure handling.

---

## ✨ Features

| Feature | iOS | Android | Detail |
|---|---|---|---|
| ⚡ Sub-second share sheet | ✅ | ✅ | `POST /api/ingest` returns `202 Accepted` in <1 s. Heavy work runs in a background thread. |
| 🧠 Local semantic search | ✅ | ✅ | ChromaDB + ONNX MiniLM embeddings. Search your entire library with natural language. |
| 🏷️ Dynamic categorisation | ✅ | ✅ | The LLM reuses existing categories or invents a new one. No fixed taxonomy. |
| ⚠️ Disambiguation UI | ✅ | ✅ | Low-confidence items get an orange **"Needs Review"** badge for manual review. |
| 🌐 Source filter bar | ✅ | ✅ | One-tap pill filter: **All · Instagram · TikTok · YouTube · Article** — client-side, no extra network call. |
| 🕐 Chronological order | ✅ | ✅ | Browse view always shows newest saves at the top via `created_at` Unix timestamp. |
| ✏️ Full CRUD | ✅ | ✅ | Swipe-to-delete, tap-to-edit (title/summary/category), add button for manual ingestion, smart category deletion. |
| 🎨 Premium dark UI | ✅ | ✅ | Midnight-blue gradient, electric-blue accent (#3E86F8), branded card borders. |
| 🔄 Status lifecycle | ✅ | ✅ | Every item transitions through a 4-stage state machine: `pending → extracting → analyzing → completed / failed` with badge colours. |
| 🔁 Automatic retries | ✅ | ✅ | Transient network failures (DNS hiccups, Ollama loading) are retried up to 3× with exponential back-off via **Tenacity**. |
| 📂 Category management | ✅ | ✅ | Rename, delete, or move items to General — all synced to the backend. |

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
| Resilience | **Tenacity** — exponential back-off retries on HTTP fetch and Ollama calls; `JobStatus` state machine (`pending → extracting → analyzing → completed / failed`) |
| Tunnel | **ngrok** — permanent static domain, works on cellular |

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
ngrok tunnel (HTTPS, public internet)
       │  your-domain.ngrok-free.app
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
   state machine: pending → extracting → analyzing → completed / failed
   retries: Tenacity exponential back-off on network + Ollama errors
       │
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

### Whisper device
Whisper runs on CPU by default. `WHISPER_DEVICE=metal` is available for Apple Silicon but requires validating the wheel version.

---

## 🔮 Roadmap

- [ ] Server-sent events (SSE) to push `processing → completed` status updates in real time (no pull-to-refresh needed)
- [ ] **Retry button** on red "Failed" rows — re-POST the same URL with one tap
- [ ] **Per-category item counts** shown on each category chip
- [ ] **App Group** shared container (iOS) so the Share Extension can cache categories offline
- [ ] Cookie passthrough (`--cookies-from-browser`) for auth-walled IG/TikTok content
- [ ] Worker isolation — move heavy ingests to a dedicated process so `/api/search` is never starved

---

Developed by [Shaked Ivgi](https://github.com/Shakedevgi).
