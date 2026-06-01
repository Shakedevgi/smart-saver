# Smart Saver — iOS setup

Two ways to get this folder into a runnable Xcode project. Pick one.

---

## Path A (recommended): xcodegen

`xcodegen` reads `project.yml` (in this folder) and produces a complete
`SmartSaver.xcodeproj` with both the main app and the Share Extension
target wired up — bundle IDs, ATS exception, extension embedding, the
whole package. ~30 seconds end-to-end.

```bash
# 1. One-time install
brew install xcodegen

# 2. From this directory, generate the project
cd ios
xcodegen generate

# 3. Open it
open SmartSaver.xcodeproj
```

In Xcode:

1. Top-left scheme picker → **SmartSaver**
2. Device picker → an **iPhone Simulator** (e.g. iPhone 15 Pro, iOS 17+)
3. ⌘R to build and run

The Simulator shares your Mac's loopback, so it can reach the FastAPI
server at `http://127.0.0.1:8000` with no extra work — as long as the
server is running (`uvicorn src.api.main:app --reload` from the repo root).

### Re-generating after you add or rename Swift files

Every time you add a new file under `ios/SmartSaver/` or
`ios/ShareExtension/`, re-run `xcodegen generate`. The tool is
idempotent and preserves your scheme / device selection.

---

## Path B (manual, no extra tools): Xcode wizard

Use this if you can't or don't want to install xcodegen.

### B1. Create the app target

1. Xcode → **File → New → Project…**
2. iOS → **App** → Next
3. Settings:
   - **Product Name:** `SmartSaver`
   - **Team:** your personal team (free Apple ID is fine for Simulator)
   - **Organization Identifier:** `com.shakedivgi.smartsaver`
   - **Interface:** SwiftUI
   - **Language:** Swift
   - **Storage:** None
   - Uncheck "Include Tests"
4. **Save inside this `ios/` folder.** When Xcode asks where to put the
   project, navigate to `smart-saver/ios/` and confirm. It will create
   `ios/SmartSaver.xcodeproj` next to the source folders.
5. In the Project navigator, **delete** Xcode's auto-generated
   `SmartSaverApp.swift` and `ContentView.swift` (Move to Trash). We're
   replacing them with the ones already on disk.

### B2. Add the existing source files to the app target

1. In Finder, open `ios/SmartSaver/`.
2. Drag the **three subfolders** (`Models`, `Services`, `Views`) plus
   `SmartSaverApp.swift` onto the `SmartSaver` group in Xcode's
   Project navigator.
3. In the dialog that appears:
   - **Destination:** uncheck "Copy items if needed" (files already
     live in the right place)
   - **Added folders:** choose **Create groups**
   - **Add to targets:** check **SmartSaver** only

### B3. Allow http to localhost (ATS exception)

iOS blocks plain HTTP by default. To let the app talk to
`http://127.0.0.1:8000`, add **one** key to the SmartSaver target's
Info settings:

1. Select the project root → **SmartSaver** target → **Info** tab
2. Right-click → **Add Row** → key: `App Transport Security Settings`
3. Inside that dictionary, add: **`Allow Local Networking` = YES**

(Equivalent raw Info.plist: `NSAppTransportSecurity → NSAllowsLocalNetworking → true`.)

### B4. Add the Share Extension target

1. **File → New → Target…**
2. iOS → **Share Extension** → Next
3. Settings:
   - **Product Name:** `ShareExtension`
   - **Project:** SmartSaver
   - **Embed in Application:** SmartSaver
4. Xcode auto-generates `ShareExtension/` with `ShareViewController.swift`,
   `MainInterface.storyboard`, and `Info.plist`. **Delete** all three
   (Move to Trash) — we use a programmatic UI from disk instead.
5. Drag `ios/ShareExtension/ShareViewController.swift` onto the
   `ShareExtension` group. In the dialog, set **Add to targets:**
   `ShareExtension` only.

### B5. Configure the Share Extension Info.plist

The extension's Info.plist needs two things:

1. **ATS exception** (same key as B3):
   `NSAppTransportSecurity → NSAllowsLocalNetworking = true`
2. **Principal class** (so iOS knows which Swift class runs when the
   sheet appears). Either:
   - Set the **NSExtensionPrincipalClass** key under
     `NSExtension` to `$(PRODUCT_MODULE_NAME).ShareViewController`,
     OR
   - In the extension target → Build Settings → search "InfoPlist" →
     ensure the Info.plist file is the one Xcode generated, and edit it
     to remove `NSExtensionMainStoryboard` and add
     `NSExtensionPrincipalClass = $(PRODUCT_MODULE_NAME).ShareViewController`.

Also confirm the activation rule includes web URLs (Xcode's default
template does):

```xml
<key>NSExtensionAttributes</key>
<dict>
    <key>NSExtensionActivationRule</key>
    <dict>
        <key>NSExtensionActivationSupportsWebURLWithMaxCount</key>
        <integer>1</integer>
        <key>NSExtensionActivationSupportsText</key>
        <integer>1</integer>
    </dict>
</dict>
```

### B6. Build and run

1. Top-left scheme picker → **SmartSaver** (the app)
2. Device picker → iPhone Simulator (iOS 17+)
3. ⌘R

To test the Share Extension in the Simulator:

1. Open Safari inside the Simulator
2. Navigate to any URL (e.g. `https://en.wikipedia.org/wiki/SwiftUI`)
3. Tap the share icon → scroll the bottom row → tap **More**
4. Enable **Save to Smart Saver**
5. Back in the share sheet, tap **Save to Smart Saver**

You should see "Saving to Smart Saver…" → "Saved!" → dismiss, and the
backend logs should show a `/api/ingest` request.

---

## Physical device (over Wi-Fi)

The Simulator works with `127.0.0.1` because it shares your Mac's
loopback. A real iPhone does not — it must hit your Mac's LAN IP.

1. Find your Mac's IP: `ipconfig getifaddr en0` (typically `192.168.1.x`)
2. Start the server bound to all interfaces:
   ```bash
   ./venv/bin/uvicorn src.api.main:app --host 0.0.0.0 --port 8000
   ```
3. In `ios/SmartSaver/Services/NetworkManager.swift`, change
   `kDefaultAPIBaseURL` to `http://192.168.1.x:8000`.
4. In `ios/ShareExtension/ShareViewController.swift`, change
   `kIngestEndpoint` to `http://192.168.1.x:8000/api/ingest`.
5. Re-run `xcodegen generate` (if using Path A) and build to the device.

`NSAllowsLocalNetworking` covers LAN HTTP too, so no further ATS edits.

---

## Troubleshooting

- **"Could not connect to server"** in the app → uvicorn isn't running,
  or you're on a physical device hitting `127.0.0.1`. See above.
- **Extension doesn't appear in Share Sheet** → in the Simulator's
  Settings app → Safari → Extensions, or just toggle it on from the
  "More" sheet (B6 step 3).
- **`http://` request was blocked** → ATS exception not applied. Re-check
  B3 / B5 for the right target.
- **Xcode "No account for team"** → Xcode → Settings → Accounts → add your
  Apple ID, then re-select it under SmartSaver → Signing & Capabilities.
