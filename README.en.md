# Drum Sheet Capture User Guide

Capture score regions shown in a video and save them as PNG, JPG, or PDF. This app captures images; it does not transcribe audio into notation or export MusicXML/MIDI.

[Download the latest release](https://github.com/kr-ericshim/drum-score-capture-tool/releases/latest) · [Project home](./README.md) · [한국어](./README.ko.md)

This guide follows the v0.1.33 source. Button names and layouts may differ in your installed version; check its release notes.

## Installation

| Computer | Download |
| --- | --- |
| Windows x64 — Intel/AMD 64-bit | `.exe` installer |
| macOS Apple Silicon — M-series | `arm64.dmg` |

Python, Node.js, and FFmpeg do not need to be installed separately. Intel Mac, native Windows ARM64, and Linux installers are not currently provided.

### Windows

1. Open the release page above and download the `.exe` under **Assets**. The source code ZIP is not an installer.
2. Run the installer and open the app.
3. The current build is unsigned, so SmartScreen may show a warning. After confirming the file came from this repository, use **More info → Run anyway** if offered. Managed computers may enforce a different policy.

### macOS

1. Download `arm64.dmg` from **Assets**.
2. Open it and copy the app to `Applications`.
3. Launch the copied app.

The current build is unsigned and not notarized, so Gatekeeper may block it. After confirming the download came from this repository, remove the installed app's quarantine attribute in Terminal and launch it again:

```bash
xattr -dr com.apple.quarantine "/Applications/Drum Sheet Capture.app"
```

If the DMG itself is blocked, replace the example path with the actual downloaded file path and keep the quotes:

```bash
xattr -dr com.apple.quarantine "/actual/download/path/downloaded-file.dmg"
```

## Basic workflow

1. **Import a video:** select a local file or prepare a public YouTube URL.
2. **Select the score area:** load a clear frame and check the suggested capture region (ROI), or draw it manually when no suggestion is available. Suggestions are editable drafts; choose **Apply region** to confirm. Leave enough room for notes, lyrics, and repeat markings.
3. **Run the capture:** confirm the time range and output formats, then start processing.
4. **Review the results:** inspect pages and select the captures to keep. When needed, crop captures and rebuild the PDF from the selection.
5. **Save the files:** check the PNG, JPG, or PDF output. Use **Save PDF as…** to save a PDF copy to your preferred location.

The frame selected in the score-area step is only for checking the ROI. Set the processing interval under **Capture range** in the capture step: enter **Start** and **End** as seconds (`90`), minutes:seconds (`1:30`), or hours:minutes:seconds (`1:02:03`). An empty start means the beginning of the video; an empty end means the end of the video. Leave both empty to process the whole video. The end must be after the start and cannot exceed the video duration.

A saved language preference takes priority. Otherwise, Korean system locales start in Korean and other locales start in English.

## Input and storage

- Video processing runs locally. YouTube import requires an internet connection.
- Sign-in, age, or region restrictions and YouTube service changes can prevent imports. You can also use a local video file.
- The file picker accepts MP4, MKV, MOV, AVI, and WEBM. A supported extension does not guarantee that every codec or damaged file can be read.
- Working videos, frames, and results can use much more disk space than the installer. Save important PDFs to a separate folder.
- Installed builds store working data in a `jobs` directory under the app's user data folder. Development runs use `backend/jobs`.

## Updates

When a newer stable release is available, a notice appears at the bottom of the app. Choose **Download page** to get the installer and install it manually. Updates are not installed automatically. Checking for updates requires an internet connection.

v0.1.32 does not include update notifications. To upgrade from that version to v0.1.33 or later for the first time, download and install it using the release link above.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Backend connection failed | Fully quit and reopen the app. Confirm the installer matches your OS architecture. If it persists, record the error and app version. |
| YouTube import failed | Check that the link is public and inspect the preparation details. Try local video input as well. |
| Blurry or incorrect preview | Seek to a frame where the score is still and clear, then reload it. |
| Notes or page edges are clipped | Adjust the ROI in the original frame and capture again. Zoom into the PDF to check markings above and below the staff. |
| Unexpected result pages | Check missing, duplicate, or suspicious captures in review, then export the final selection again. |

When an error occurs, choose **Copy diagnostics** at the bottom of the app to copy the app version, OS details, errors, and recent logs. **Report a problem** opens the issue form. Logs are not sent automatically; review the copied text before pasting the relevant details.

Report unresolved issues in [Issues](https://github.com/kr-ericshim/drum-score-capture-tool/issues). Include app version, OS/CPU architecture, local or YouTube input, reproduction steps, and the error message. Remove private file paths and links from logs before sharing.

## Development and builds

For source setup and builds, see the [project README](./README.md#development). Maintainers should use the [release runbook](./docs/release/github-release-runbook.md).
