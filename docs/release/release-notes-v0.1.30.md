# Drum Sheet Capture v0.1.30

## What Changed

- Refreshed the desktop app icon with a cleaner Drum Sheet Capture visual identity.
- Rebuilt macOS and Windows icon assets used by Electron packaging.

## macOS Install

The current public macOS build is unsigned. On first install:

1. Open the DMG.
2. Drag `Drum Sheet Capture.app` to `Applications`.
3. Open Terminal and run:

```bash
xattr -dr com.apple.quarantine "/Applications/Drum Sheet Capture.app"
```

If Gatekeeper blocks the DMG before it opens, clear quarantine on the downloaded file first:

```bash
xattr -dr com.apple.quarantine "/path/to/Drum.Sheet.Capture-0.1.30-arm64.dmg"
```

Then open the app again.

## Known Limitation

- The macOS app is not Apple-signed or notarized. Public install instructions must continue to include the `xattr` workaround above.
- The Windows installer is not code-signed yet. SmartScreen or unknown publisher warnings are expected until Windows signing is added.
