"""Smart Saver — local development orchestrator.

Default mode (physical iPhone over Wi-Fi):
    python run_dev.py
        - detects the Mac's LAN IP
        - rewrites the two `http://...:8000` constants in
          ios/SmartSaver/Services/NetworkManager.swift and
          ios/ShareExtension/ShareViewController.swift
        - runs `xcodegen generate` so Xcode picks up the change
        - starts uvicorn bound to 0.0.0.0:8000

Simulator mode:
    python run_dev.py --simulator
        - same flow, but pins the Swift constants back to 127.0.0.1 and
          starts uvicorn on 127.0.0.1 only.

Patch-only (skip the server):
    python run_dev.py --no-server

Usage notes:
- After running this script, ALWAYS rebuild from Xcode (⌘B / ⌘R) so the
  new IP is compiled into the iOS binary.
- Re-run any time your Mac's LAN IP changes (e.g. you switch Wi-Fi).
"""

from __future__ import annotations

import argparse
import re
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IOS_DIR = ROOT / "ios"
SWIFT_FILES_TO_PATCH = [
    IOS_DIR / "SmartSaver" / "Services" / "NetworkManager.swift",
    IOS_DIR / "ShareExtension" / "ShareViewController.swift",
]

# Matches an http(s) URL up through the port. Captures `http://host:port`,
# leaves any trailing path (`/api/ingest`) untouched.
URL_PORT_PATTERN = re.compile(r"http://[A-Za-z0-9\.\-]+:\d+")

DEFAULT_PORT = 8000


# ============================================================ IP detection
def detect_lan_ip() -> str:
    """Resolve the local IP the Mac would use to reach the wider network.

    Opens a UDP socket to a non-routable address — nothing is sent, but
    the kernel still picks the source IP for the route. Returns 127.0.0.1
    if nothing works (e.g. Wi-Fi off).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# ============================================================ Swift patcher
def patch_swift_url(path: Path, new_host_port: str) -> bool:
    """Replace `http://host:port` with the new value everywhere in `path`.
    Returns True if the file changed."""
    if not path.exists():
        print(f"  ! skipping (not found): {path}")
        return False
    original = path.read_text()
    updated = URL_PORT_PATTERN.sub(new_host_port, original)
    if updated == original:
        print(f"  · already correct: {path.relative_to(ROOT)}")
        return False
    path.write_text(updated)
    print(f"  ✓ patched: {path.relative_to(ROOT)}")
    return True


# ============================================================ xcodegen
def run_xcodegen() -> None:
    print("→ Regenerating Xcode project (xcodegen)…")
    try:
        subprocess.run(
            ["xcodegen", "generate"],
            cwd=IOS_DIR,
            check=True,
        )
    except FileNotFoundError:
        sys.exit(
            "\n!! `xcodegen` not on PATH. Install once with:\n"
            "     brew install xcodegen\n"
        )
    except subprocess.CalledProcessError as exc:
        sys.exit(f"\n!! xcodegen failed (exit {exc.returncode}). See output above.")


# ============================================================ uvicorn
def run_uvicorn(host: str, port: int) -> None:
    print(f"→ Starting uvicorn on http://{host}:{port} …")
    print("   Ctrl-C to stop.\n")
    cmd = [
        sys.executable, "-m", "uvicorn",
        "src.api.main:app",
        "--host", host,
        "--port", str(port),
        "--reload",
        # Critical: restrict the file-watcher to the Python source tree.
        # Default watches the CWD, which means every Chroma sqlite write
        # under data/chroma/ AND every Swift / xcodegen edit under ios/
        # triggers a reload. That tears down the in-memory Chroma client
        # while a request is in flight and crashes with
        # `'RustBindingsAPI' object has no attribute 'bindings'`.
        "--reload-dir", str(ROOT / "src"),
    ]
    try:
        subprocess.run(cmd, cwd=ROOT, check=False)
    except KeyboardInterrupt:
        print("\n→ uvicorn stopped.")


# ============================================================ entry point
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect the Mac's LAN IP, patch the iOS Swift constants, "
                    "regenerate the Xcode project, and start the FastAPI server.",
    )
    parser.add_argument(
        "--simulator", action="store_true",
        help="Use 127.0.0.1 instead of the LAN IP (iOS Simulator mode).",
    )
    parser.add_argument(
        "--no-server", action="store_true",
        help="Skip starting uvicorn; just patch + regenerate.",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"Port to bind (default {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--no-xcodegen", action="store_true",
        help="Skip the xcodegen regeneration step.",
    )
    args = parser.parse_args()

    ip = "127.0.0.1" if args.simulator else detect_lan_ip()
    bind_host = "127.0.0.1" if args.simulator else "0.0.0.0"
    new_host_port = f"http://{ip}:{args.port}"

    mode = "Simulator (loopback)" if args.simulator else "Physical device (LAN)"
    print("=" * 60)
    print(f"  Smart Saver dev orchestrator — mode: {mode}")
    print(f"  Reachable iOS-side URL : {new_host_port}")
    print(f"  uvicorn bind           : {bind_host}:{args.port}")
    print("=" * 60)

    print("\n→ Patching iOS Swift constants…")
    any_changed = False
    for swift_path in SWIFT_FILES_TO_PATCH:
        if patch_swift_url(swift_path, new_host_port):
            any_changed = True

    if not args.no_xcodegen:
        if any_changed:
            run_xcodegen()
        else:
            print("→ No Swift changes — skipping xcodegen.")

    print()
    if not args.simulator:
        print("Tip — on your iPhone:")
        print("  1. Settings → Privacy & Security → Developer Mode → ON, restart.")
        print("  2. Plug iPhone into the Mac; trust the computer if prompted.")
        print("  3. In Xcode → device picker → select your iPhone → ⌘R.")
        print("  4. iPhone may ask to trust the developer (Settings → General →")
        print("     VPN & Device Management → trust your Apple ID).")
        print()

    if args.no_server:
        print("→ --no-server given; not starting uvicorn.")
        return

    run_uvicorn(bind_host, args.port)


if __name__ == "__main__":
    main()
