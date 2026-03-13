# Drum Sheet Capture v0.1.25

## Highlights

- Release packaging now requires a bundled frozen backend runtime, so the packaged app does not depend on a separate Python install.
- Local backend access is scoped to the desktop session token instead of accepting unauthenticated renderer requests.
- Job metadata now survives app restarts and corrupt metadata is recovered into a visible error state instead of disappearing silently.
- Review export now refinalizes selected captures and the redesigned desktop shell keeps review-state navigation aligned with the new workspace flow.

## macOS Install Note

The current public macOS build is unsigned. Install from the DMG, copy the app to `Applications`, then run:

```bash
xattr -dr com.apple.quarantine "/Applications/Drum Sheet Capture.app"
```

If Gatekeeper blocks the DMG itself before it opens, run:

```bash
xattr -dr com.apple.quarantine "/path/to/Drum Sheet Capture-0.1.25-arm64.dmg"
```

## Known Limitation

- The macOS app is not Apple-signed or notarized. Public install instructions must continue to include the `xattr` workaround above.
