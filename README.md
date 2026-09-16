# Drum Sheet Capture

Turn score pages shown in a video into PNG, JPG, or PDF files. Select the score area, capture it locally, and review the pages before exporting.

**[Download the latest release](https://github.com/kr-ericshim/drum-score-capture-tool/releases/latest)** · [한국어 가이드](./README.ko.md) · [English guide](./README.en.md)

## Download and install

| Your computer | Download | Installation |
| --- | --- | --- |
| Windows x64 (Intel/AMD 64-bit) | `.exe` installer | Run the installer and launch Drum Sheet Capture. |
| macOS Apple Silicon (M-series) | `arm64.dmg` | Open the DMG and copy the app to Applications. |

Public installers bundle the Python backend and FFmpeg/FFprobe. You do not need to install Python, Node.js, or FFmpeg separately to use the app. Intel Mac, native Windows ARM64, and Linux installers are not currently provided.

The builds are currently **unsigned**. See the [Korean installation notes](./README.ko.md#설치) or [English installation notes](./README.en.md#installation) for Windows SmartScreen and macOS Gatekeeper guidance.

The guides describe the current source tree. Features in an unreleased checkout may differ from the latest downloadable release; check the release notes for your installed version.

## How it works

1. Open a local video or prepare a public YouTube URL.
2. Load a frame where the score is visible and mark its capture region (ROI).
3. Choose the capture range and export options, then run the capture.
4. Review the captured pages, adjust the selection, and export PNG, JPG, or PDF.

Image processing runs locally. YouTube import needs an internet connection, and access restrictions or service changes can prevent a download. The app captures score images; it does not transcribe audio into notation or generate editable MusicXML/MIDI.

## Development

The CI environment uses **Python 3.11** and **Node.js 22**. Source runs also need `ffmpeg` and `ffprobe` on `PATH`, or the corresponding `DRUMSHEET_FFMPEG_BIN` / `DRUMSHEET_FFPROBE_BIN` environment variables.

From the repository root on macOS:

```bash
python3.11 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-build.txt
npm --prefix desktop ci
npm --prefix desktop start
```

On Windows PowerShell:

```powershell
py -3.11 -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements-build.txt
npm --prefix desktop ci
npm --prefix desktop start
```

Build the standalone installer **on the target operating system** (Apple Silicon macOS or Windows x64):

```bash
npm --prefix desktop run dist:release
npm --prefix desktop run smoke:packaged-electron
npm --prefix desktop run smoke:packaged-runtime
```

The build stages platform-specific FFmpeg/FFprobe binaries and freezes the backend. Outputs go to `dist/`. `pack:release` creates an unpacked app only; it does not produce an installer. See the [release runbook](./docs/release/github-release-runbook.md) for the full checks and CI preflight.

| Build profile | Purpose |
| --- | --- |
| `release` | Recommended public package; uses compact filtering. |
| `compact` | Same packaging policy as `release`. |
| `lean` | Excludes optional third-party trees; still bundles the frozen backend. |
| `full` | Internal fallback with fewer exclusions; not the public default. |

Optional HAT upscaling dependencies are separate from the normal installation; they are not required for standard capture and export.

## Project and support

- [`desktop/`](./desktop): Electron app and renderer.
- [`backend/`](./backend): local processing engine.
- [Release runbook](./docs/release/github-release-runbook.md) and [production checklist](./docs/release/final-production-checklist.md).
- [Report a problem](https://github.com/kr-ericshim/drum-score-capture-tool/issues): include app version, OS/architecture, input type, reproduction steps, and the error message. Remove private file paths or links before sharing logs.
- [MIT license](./LICENSE).
