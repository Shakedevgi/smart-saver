"""Smart Saver — local development orchestrator.

Default — ngrok (global HTTPS, works on cellular):
    python run_dev.py
        - launches ngrok on port 8000 (or reuses a running tunnel)
        - extracts the public https://<id>.ngrok-free.app URL
        - patches NetworkManager.swift + ShareViewController.swift
        - runs `xcodegen generate`
        - starts uvicorn bound to 0.0.0.0:8000

LAN Wi-Fi fallback (same network only):
    python run_dev.py --local
        - detects the Mac's Wi-Fi IP via UDP-socket trick
        - same patch / regenerate / server flow

iOS Simulator mode (loopback only):
    python run_dev.py --simulator
        - pins both Swift constants to http://127.0.0.1:8000
        - starts uvicorn on 127.0.0.1

Patch + regenerate only (skip the server):
    python run_dev.py --no-server

After any mode switch always rebuild from Xcode (⌘B / ⌘R) so the
patched URL is compiled into the binary.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT        = Path(__file__).resolve().parent
IOS_DIR     = ROOT / "ios"
ANDROID_DIR = ROOT / "android"

SWIFT_FILES_TO_PATCH = [
    IOS_DIR / "SmartSaver"     / "Services" / "NetworkManager.swift",
    IOS_DIR / "ShareExtension" / "ShareViewController.swift",
]

ANDROID_FILES_TO_PATCH = [
    ANDROID_DIR / "app" / "src" / "main" / "kotlin"
    / "com" / "shakedivgi" / "smartsaver" / "data" / "AppConfig.kt",
]

# Matches the base-URL portion of both forms we ever write:
#   http://10.0.0.17:8000           (LAN / loopback — has port)
#   https://xxxx.ngrok-free.app     (ngrok — no port)
# Leaving any path suffix (/api/ingest) in place.
URL_BASE_PATTERN = re.compile(r"https?://[A-Za-z0-9.\-]+(?::\d+)?")

DEFAULT_PORT  = 8000
NGROK_API_URL = "http://127.0.0.1:4040/api/tunnels"


# ──────────────────────────────────────────────── helpers

def detect_lan_ip() -> str:
    """Return the Mac's outbound LAN IP (or 127.0.0.1 if unreachable)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _query_ngrok() -> str | None:
    """Ask the ngrok local API for the active HTTPS tunnel URL.
    Returns None if ngrok isn't running or no HTTPS tunnel exists yet.
    """
    try:
        with urllib.request.urlopen(NGROK_API_URL, timeout=3) as resp:
            data = json.loads(resp.read())
        for tunnel in data.get("tunnels", []):
            if tunnel.get("proto") == "https":
                return tunnel["public_url"]
    except Exception:
        pass
    return None


def launch_ngrok(port: int) -> str:
    """Ensure an ngrok HTTP tunnel on *port* is running and return its HTTPS URL.

    If ngrok is already running (any prior invocation, or the user started it
    manually), we simply reuse the existing tunnel — no second process.
    """
    existing = _query_ngrok()
    if existing:
        print(f"  · ngrok already running  →  {existing}")
        return existing

    print("  → Starting ngrok tunnel…")
    try:
        subprocess.Popen(
            ["ngrok", "http", f"--domain=cryptic-attire-statute.ngrok-free.dev", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        sys.exit(
            "\n!! `ngrok` not found on PATH.\n"
            "   Install : https://ngrok.com/download\n"
            "   Auth    : ngrok config add-authtoken <your-token>\n"
        )

    # ngrok negotiates the tunnel asynchronously; poll until it's ready.
    for attempt in range(1, 21):
        time.sleep(1)
        url = _query_ngrok()
        if url:
            print(f"  ✓ ngrok tunnel ready  →  {url}")
            return url
        if attempt % 5 == 0:
            print(f"  … still waiting ({attempt}s)")

    sys.exit(
        "!! ngrok did not produce a tunnel within 20 seconds.\n"
        "   Verify: ngrok is installed, authenticated (`ngrok config add-authtoken`),\n"
        "   and you have no active tunnel limit reached on the free plan.\n"
    )


def patch_swift_url(path: Path, new_base_url: str) -> bool:
    """Substitute the base-URL in *path* with *new_base_url*.
    Returns True if the file was modified.
    """
    if not path.exists():
        print(f"  ! skipping (not found): {path}")
        return False
    original = path.read_text()
    updated  = URL_BASE_PATTERN.sub(new_base_url, original)
    if updated == original:
        print(f"  · already correct: {path.relative_to(ROOT)}")
        return False
    path.write_text(updated)
    print(f"  ✓ patched: {path.relative_to(ROOT)}")
    return True


def run_xcodegen() -> None:
    print("→ Regenerating Xcode project (xcodegen)…")
    try:
        subprocess.run(["xcodegen", "generate"], cwd=IOS_DIR, check=True)
    except FileNotFoundError:
        sys.exit(
            "\n!! `xcodegen` not on PATH. Install once with:\n"
            "     brew install xcodegen\n"
        )
    except subprocess.CalledProcessError as exc:
        sys.exit(f"\n!! xcodegen failed (exit {exc.returncode}). See output above.")


def run_android_build() -> None:
    """Run ./gradlew assembleDebug in android/. Sets ANDROID_HOME if not already set."""
    gradlew = ANDROID_DIR / "gradlew"
    if not gradlew.exists():
        print("  ! android/gradlew not found — skipping Android build.")
        return
    print("→ Building Android debug APK (./gradlew assembleDebug)…")
    env = {**subprocess.os.environ}
    if not env.get("ANDROID_HOME"):
        env["ANDROID_HOME"] = str(Path.home() / "Library" / "Android" / "sdk")
    if not env.get("JAVA_HOME"):
        studio_jbr = Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home")
        if studio_jbr.exists():
            env["JAVA_HOME"] = str(studio_jbr)
    try:
        subprocess.run(
            [str(gradlew), "assembleDebug", "--no-daemon"],
            cwd=ANDROID_DIR,
            env=env,
            check=True,
        )
        apk = ANDROID_DIR / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
        print(f"  ✓ APK built → {apk.relative_to(ROOT)}")
    except subprocess.CalledProcessError as exc:
        print(f"  ! Android build failed (exit {exc.returncode}). See output above.")


def run_uvicorn(host: str, port: int) -> None:
    print(f"→ Starting uvicorn on {host}:{port} …")
    print("   Ctrl-C to stop.\n")
    cmd = [
        sys.executable, "-m", "uvicorn",
        "src.api.main:app",
        "--host", host,
        "--port", str(port),
        "--reload",
        # Restrict the file-watcher to src/ only: Chroma sqlite writes and
        # Swift edits under ios/ would otherwise trigger constant reloads.
        "--reload-dir", str(ROOT / "src"),
    ]
    try:
        subprocess.run(cmd, cwd=ROOT, check=False)
    except KeyboardInterrupt:
        print("\n→ uvicorn stopped.")


# ──────────────────────────────────────────────── entry point

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Patch iOS Swift URL constants, regenerate the Xcode project, "
            "and start the FastAPI server.\n\n"
            "Default mode uses ngrok for a global HTTPS tunnel (works on cellular).\n"
            "Use --local for LAN Wi-Fi, --simulator for the iOS Simulator."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--local", action="store_true",
        help="Use the Mac's LAN IP (same Wi-Fi required). Skips ngrok.",
    )
    mode_group.add_argument(
        "--simulator", action="store_true",
        help="Use http://127.0.0.1 (iOS Simulator / loopback). Skips ngrok.",
    )
    mode_group.add_argument(
        "--android-emulator", action="store_true",
        help="Use http://10.0.2.2:8000 (Android Emulator → host loopback). Skips ngrok.",
    )

    parser.add_argument(
        "--no-server", action="store_true",
        help="Patch + regenerate only; do not start uvicorn.",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"Server port (default {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--no-xcodegen", action="store_true",
        help="Skip the xcodegen regeneration step.",
    )
    parser.add_argument(
        "--android-build", action="store_true",
        help="Run ./gradlew assembleDebug in android/ after patching.",
    )
    args = parser.parse_args()

    # ── resolve mode ─────────────────────────────────────────────────────────
    if args.simulator:
        mode_label  = "Simulator (loopback)"
        new_base_url = f"http://127.0.0.1:{args.port}"
        bind_host   = "127.0.0.1"

    elif args.android_emulator:
        mode_label  = "Android Emulator (10.0.2.2 → host loopback)"
        new_base_url = f"http://10.0.2.2:{args.port}"
        bind_host   = "127.0.0.1"

    elif args.local:
        mode_label  = "Physical device — LAN Wi-Fi"
        ip           = detect_lan_ip()
        new_base_url = f"http://{ip}:{args.port}"
        bind_host   = "0.0.0.0"

    else:
        mode_label  = "Ngrok — public HTTPS / cellular"
        bind_host   = "0.0.0.0"
        print("→ Resolving ngrok tunnel…")
        new_base_url = launch_ngrok(args.port)

    # ── banner ────────────────────────────────────────────────────────────────
    print("=" * 60)
    print(f"  Smart Saver dev orchestrator")
    print(f"  Mode            : {mode_label}")
    print(f"  iOS/Android URL : {new_base_url}")
    print(f"  Server bind     : {bind_host}:{args.port}")
    print("=" * 60)

    # ── patch Swift constants ─────────────────────────────────────────────────
    print("\n→ Patching iOS Swift constants…")
    any_changed = any(
        patch_swift_url(p, new_base_url) for p in SWIFT_FILES_TO_PATCH
    )

    # ── patch Android Kotlin constants ────────────────────────────────────────
    print("\n→ Patching Android Kotlin constants…")
    any(patch_swift_url(p, new_base_url) for p in ANDROID_FILES_TO_PATCH)

    # ── optional Android build ────────────────────────────────────────────────
    if args.android_build:
        run_android_build()

    # ── xcodegen ──────────────────────────────────────────────────────────────
    if not args.no_xcodegen:
        if any_changed:
            run_xcodegen()
        else:
            print("→ No Swift changes — skipping xcodegen.")

    # ── tips ──────────────────────────────────────────────────────────────────
    print()
    if args.simulator:
        print("Tip: select an iOS 17+ Simulator in Xcode, then ⌘R.")
        print("     For Android Emulator, use --android-emulator instead.")
    elif getattr(args, 'android_emulator', False):
        print("Tip: start an Android Emulator in Android Studio, then run/install the APK.")
        print(f"  Server reachable from emulator at: {new_base_url}")
    elif args.local:
        print("Tip: your iPhone and Mac must be on the same Wi-Fi network.")
        print(f"  Server reachable at: {new_base_url}")
    else:
        print("Tip: the ngrok tunnel works on cellular OR Wi-Fi.")
        print(f"  Public URL: {new_base_url}")
        print("  Keep this terminal open — the tunnel closes when you Ctrl-C.")
    print()

    if args.no_server:
        print("→ --no-server given; not starting uvicorn.")
        return

    run_uvicorn(bind_host, args.port)


if __name__ == "__main__":
    main()
