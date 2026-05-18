# Drum Sheet Capture v0.1.29

## What Changed

- Renderer v2 is now the primary desktop experience, with the legacy renderer kept only as a fallback path.
- Score export is more reliable: PDF output keeps higher fidelity, document header metadata is reused consistently, and export confirmation protects final file metadata.
- Capture and review flows now guard against unsafe ROI selections, suspicious capture quality, duplicate finalize work, and review/export reentry edge cases.
- YouTube and local media handling now preserves source identity better, including titles, archive entries, preview cache keys, and prepared-source progress.
- Release packaging is more robust across macOS and Windows, including frozen backend runtime checks, packaged smoke tests, CI test isolation, Windows asar asset path handling, and packaged runtime smoke coverage for bundled ffmpeg/ffprobe paths.

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
xattr -dr com.apple.quarantine "/path/to/Drum.Sheet.Capture-0.1.29-arm64.dmg"
```

Then open the app again.

## Known Limitation

- The macOS app is not Apple-signed or notarized. Public install instructions must continue to include the `xattr` workaround above.
- The Windows installer is not code-signed yet. SmartScreen or unknown publisher warnings are expected until Windows signing is added.
