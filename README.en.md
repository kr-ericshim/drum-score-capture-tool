# Drum Sheet Capture User Guide

[Back to README hub](./README.md)

## Overview

Drum Sheet Capture is a local desktop app that lets you select the score area from a video and export the result as PNG, JPG, or PDF.

Supported release targets:

- Windows installer
- macOS DMG

## Installation

Download the file for your operating system from GitHub Releases.

- Windows: `.exe` installer
- macOS: `.dmg`

The default public release is a standalone build.
It is intended to run without requiring a separate Python installation.

## Launch

1. Open the app.
2. Click `Select Video` on the first screen.
3. Choose either a local file or a YouTube URL.

On first launch, the UI uses the saved language if one exists.
Otherwise it defaults to Korean for `ko*` system locales and English for everything else.

## Basic Workflow

1. Select a video
2. Open a frame where the score is clearly visible
3. Draw the ROI box around the score area
4. Choose export formats
5. Start processing
6. Review the results and export the final selection

## Output

The app can export:

- PNG
- JPG
- PDF

You can review generated pages before exporting the final set.

## Troubleshooting

### macOS Gatekeeper blocks the app

Because the current public macOS build is unsigned, Gatekeeper may block the DMG or the app on first launch.

1. Open the DMG and copy the app to `Applications`.
2. Open Terminal and remove the quarantine attribute:

```bash
xattr -dr com.apple.quarantine "/Applications/Drum Sheet Capture.app"
```

If macOS blocks the DMG itself before it opens, run the same command against the downloaded DMG first:

```bash
xattr -dr com.apple.quarantine "/path/to/Drum.Sheet.Capture-arm64.dmg"
```

After that, try launching the app again.

### Backend connection failed

- Restart the app.
- Confirm that you are running the latest release build.

### The preview frame is not usable

- Move to a moment where the score is clearer and load the frame again.
- Leave a small top and bottom margin instead of drawing the ROI too tightly.

### Page size or clipping looks wrong

- Adjust the ROI and run the process again.
- Review suspicious pages before exporting the final set.

## Release Build Notes

The public GitHub release build uses the `dist:release` profile.

This profile keeps:

- standalone installation
- Windows and macOS release focus
- aggressive removal of caches, tests, docs, and non-runtime assets

`full` remains an internal fallback package and should not be treated as the default public release.
