# Drum Sheet Capture v0.1.27

## What Changed

- Public release packages now include the frozen backend runtime, so end users do not need a separate Python install.
- Review export and the redesigned desktop shell now stay aligned, so the capture-to-review flow is easier to follow.
- Local job state now recovers cleanly after restarts instead of disappearing silently.

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
xattr -dr com.apple.quarantine "/path/to/Drum.Sheet.Capture-0.1.27-arm64.dmg"
```

Then open the app again.

## Known Limitation

- The macOS app is not Apple-signed or notarized. Public install instructions must continue to include the `xattr` workaround above.
