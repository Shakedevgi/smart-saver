# 📑 SmartSaver — The AI-Powered Link Archiver for Social Media

> **"Because your 'Saved' folder on Instagram is where links go to die, and your TikTok bookmarks are a digital hoarder's paradise."** 💀

Welcome to **SmartSaver**, a next-generation link archiver and semantic bookmarking system that takes raw links from your favorite social media platforms (YouTube, Instagram, TikTok, and more) and uses local AI to extract, summarize, and categorize them in under a second — completely backgrounded, offline-first, and private.

No more scroll-paralysis. No more *"what was that cool coding video I saved three months ago?"*. Just share the link from your iPhone, and let local LLMs do the heavy lifting while you keep scrolling.

---

## 🚀 Key Features & UX Magic

- **⚡ Sub-second share-sheet dismissal.** Using FastAPI's native `BackgroundTasks`, the iOS Share Extension captures your shared URL, hands it to the server, and flashes a "Saved!" checkmark in **under 1 second**. The processing happens entirely in the background.
- **🧠 Local semantic analysis.** Powered by local AI models, the backend automatically transcribes video audio, reads text off the screen via OCR, and understands the underlying topic — all without leaving your machine.
- **🏷️ Dynamic categorization (anti-lazy LLM).** If a video fits your existing categories (e.g. *Programming*, *Travel*, *Personal Finance*), it goes there. If it's a completely new topic, the LLM dynamically invents a fresh category on the fly.
- **⚠️ Disambiguation UI.** If the local LLM feels torn or low-confidence, it tags the item with an orange **"Needs Disambiguation"** capsule and outlines the card in orange for your manual review.
- **📁 Smart category deletion & full CRUD.** Swipe-to-delete items, edit titles/summaries inline, add links manually with the `+` button, or delete categories with the option to safely move orphaned items to a "General" bucket instead of nuking them.

---

## 🛠️ The Tech Stack

SmartSaver bridges the gap between high-performance Python backend orchestration and native iOS system extensions:

### Backend (the heavy lifter)

- **FastAPI (Python)** — high-performance async API layer with native background-task execution.
- **ChromaDB** — vector database holding semantic embeddings for instant search and categorization.
- **Ollama (Llama 3 / Mistral)** — local LLM running completely offline on personal hardware.
- **Whisper (faster-whisper)** — audio transcription engine to extract speech from videos.
- **EasyOCR (MPS-accelerated)** — computer-vision layer to capture embedded text, graphics, and subtitles (crucial for Instagram Reels & TikToks). Uses Apple's Metal Performance Shaders for ~4× speedup on Apple Silicon.
- **yt-dlp** — advanced multimedia scraper for streaming media assets behind platform restriction walls.

### Frontend (the native experience)

- **SwiftUI & Swift** — clean, declarative UI with dynamic grids, semantic search, and pull-to-refresh.
- **iOS Share Extension (UIKit bridge)** — system-level interceptor for sharing directly from any host app (Safari, Instagram, TikTok).
- **XcodeGen** — generates an ephemeral `.xcodeproj` from a declarative `project.yml`, keeping the Git repo 100% clean of bloated binary project settings.

---

## 🔄 How It Works (the pipeline)

```
 ┌───────────────────────┐
 │  iPhone Share Sheet   │
 └───────────┬───────────┘
             │  (URL shared)
             ▼
 ┌───────────────────────┐
 │   FastAPI Endpoint    │ ──► 202 Accepted (instant)
 └───────────┬───────────┘
             │  (fires BackgroundTask)
             ▼
 ┌──────────────────────────────────┐
 │     Data Extraction Layer        │
 │  • Video parsing  (yt-dlp)       │
 │  • Speech-to-text (Whisper)      │
 │  • Visual text    (EasyOCR / MPS)│
 └───────────────┬──────────────────┘
                 ▼
 ┌──────────────────────────────────┐
 │  Local Ollama                    │
 │  (dynamic categorization +       │
 │   one-line summary + entities)   │
 └───────────────┬──────────────────┘
                 ▼
 ┌──────────────────────────────────┐
 │  ChromaDB                        │
 │  (status: processing → completed)│
 └──────────────────────────────────┘
```

---

## ⚠️ Known Limitations & Disclosures

### The Facebook Auth-Wall 🛑
Please note that **Facebook links (Posts, Reels, and Marketplace items) are currently not supported by the automated scraping pipeline**. 

Facebook employs aggressive, dynamically generated tracking parameters (e.g., `?mibextid=...`, `&rdid=...`) and enforces an immediate, strict HTTP redirection wall to a login prompt whenever an unauthenticated scraper tries to access their content. Because SmartSaver is dedicated to an **offline-first, privacy-respecting workflow**, we do not scrape behind user accounts or store session cookies.

### 💡 Our Solution: Manual Ingestion
To ensure you never lose important data, we implemented a **Manual Ingestion** fallback. If an automated pipeline fails (or if you are saving an unsupported platform), you can tap the **`+` (Add)** button in the app's navigation bar to manually paste the URL, type a custom title/summary, and assign a category. It bypasses the scrapers and commits straight to ChromaDB instantly.

---

## 🚦 Getting Started (local run guide)

Want to deploy SmartSaver on your own machine and test it on a physical iPhone? Follow this guide.

### Prerequisites

1. A Mac (Apple Silicon recommended for fast local LLM + MPS-accelerated OCR).
2. Xcode installed (with iOS 17+ simulators/SDKs).
3. [Ollama](https://ollama.com) installed and running locally with `llama3` pulled (`ollama pull llama3`).
4. Homebrew installed.
5. `xcodegen` from Homebrew: `brew install xcodegen`.

### 1. Backend setup

Clone the repository and spin up the Python environment:

```bash
git clone https://github.com/Shakedevgi/smart-saver.git
cd smart-saver

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. DevOps automation (Mac-to-iPhone live-sync)

Instead of manually hunting for IP addresses, run the custom developer orchestration script:

```bash
python run_dev.py
```

What this script does behind the scenes:

- Automatically detects your Mac's local Wi-Fi network IP (e.g. `192.168.1.145`).
- Regex-patches the Swift client constants (`NetworkManager.swift` and `ShareViewController.swift`) to target your Mac's IP instead of `localhost`.
- Triggers `xcodegen generate` to assemble a fresh `SmartSaver.xcodeproj`.
- Launches the FastAPI Uvicorn server bound to `0.0.0.0:8000` so your physical iPhone can reach it.

For Simulator-only development, pass `--simulator` to pin everything back to `127.0.0.1`.

### 3. 📱 Physical iPhone deployment

Because Apple values strict client sandboxing, deploying an app over a local network loopback requires a quick manual configuration inside Xcode:

1. Open the newly generated project file:

   ```bash
   open ios/SmartSaver.xcodeproj
   ```

2. **On your physical iPhone:** Settings → Privacy & Security → **Developer Mode** → toggle ON (accept the prompt to restart your device).

3. Connect your iPhone to your Mac via cable. Select **"Trust This Computer"** and enter your passcode.

4. **Important signing step (XcodeGen notice):**
   - In Xcode, select the main `SmartSaver` project root and navigate to **Signing & Capabilities**.
   - Under TARGETS, select your personal Apple ID account in the **Team** dropdown for **both** targets (`SmartSaver` and `ShareExtension`).
   - *Note:* Because XcodeGen dynamically regenerates the workspace, you may need to re-select your development team whenever you re-run `xcodegen generate`.
   - If you get a "Bundle Identifier already used" error, change the bundle suffix slightly (e.g. `com.yourname.smartsaver`).

5. In the Xcode scheme selector (top-left), choose your physical iPhone device and press **⌘R** to run.

6. Once installed, open your iPhone's Settings → General → **VPN & Device Management**, find your Apple ID under "Developer App", and tap **Trust**.

7. Open the app from your home screen, head over to TikTok or Instagram, and share your first link! 🎉

---

## 🧪 Testing

A full pytest-free smoke suite ships in `tests/test_smoke.py` — no dependencies beyond what's already in `requirements.txt`.

```bash
python tests/test_smoke.py
# 37/37 passed
```

The suite covers: URL classification, sanitization, the full ChromaDB round-trip, all four `/api/*` endpoints, the async background-task pipeline (placeholder → completed/failed lifecycle), manual ingestion via `POST /api/items`, and category management (rename / move-to-General / cascade-delete).

---

## 🔮 Future Roadmap

This project is actively developed. Upcoming features before App Store submission:

- [ ] **App Group** shared containers for full offline-caching when the server is unreachable.
- [ ] **Direct single-tap category reassignment** dropdowns inside the dashboard rows.
- [ ] **Push Notifications** to alert the user immediately when a complex background pipeline finishes analysis.
- [ ] **Cookie-pinning** for auth-walled sources (Facebook posts, private Instagram accounts).
- [ ] **Retry button** on red "Failed" rows — re-POST the same URL with one tap.

---

Developed by [Shaked Ivgi](https://github.com/Shakedevgi).
