# Media toolchain and local release builds

The app retains **both ffmpeg and ffprobe**. Removing ffprobe is not necessary for the first size reduction, and retaining it preserves structured metadata and yt-dlp post-processing. Do not restore the old npm-provided binaries: the inspected v0.1.30 macOS ffmpeg reported nonredistributable/nonfree code and its ffprobe was Intel-only.

## Pinned inputs

- Python: `.python-version` (3.11 minor line; setup-python resolves the available platform patch); build launcher rejects other Python minor versions.
- Python dependencies: `backend/requirements-build.lock`, shared by CI and release builds. Refresh deliberately with `uv pip compile backend/requirements-build.txt --python-version 3.11 --universal -o backend/requirements-build.lock` and rerun both platforms.
- FFmpeg: 8.1.2 official source; SHA-256 is pinned in `scripts/build-media-tools.sh`.
- dav1d: 1.5.3 official source, also checksum-pinned; statically linked BSD-2-Clause AV1 software decoder. Native FFmpeg AV1 support alone is not sufficient on machines without AV1 hardware decoding.
- LGPL build flags explicitly disable GPL and nonfree components and automatic discovery of local libraries. Native H.264, HEVC and VP9 decoding is retained. Image encoders, MPEG-4/FFV1 test fixtures, AAC, local-file/pipe processing, native platform TLS, and the existing filters/muxers remain available.
- `uvicorn` uses asyncio/h11 without its standard extra. PyInstaller excludes uvloop, httptools, watchfiles and dotenv even if an old development environment has them installed. WebSockets dependencies used by yt-dlp are retained.

## macOS build

Keep the existing development `.venv` intact. Use the dedicated build environment:

```bash
uv python install 3.11
uv venv --python 3.11 backend/.venv-build
uv pip sync --python backend/.venv-build/bin/python backend/requirements-build.lock
# Required once if pkg-config is missing:
brew install pkgconf
PATH="$PWD/backend/.venv-build/bin:$PATH" bash scripts/build-media-tools.sh
npm --prefix desktop ci
npm --prefix desktop run dist:release
npm --prefix desktop run smoke:packaged-runtime
npm --prefix desktop run smoke:packaged-electron
```

`run-builder.js` prefers `.venv-build`, then compatible existing interpreters. Set `DRUMSHEET_BUILD_PYTHON` to explicitly choose an interpreter. No build mutates the development virtualenv. Build tools get an ad-hoc signature after stripping on arm64; this is **not** Developer ID signing or notarization.

## Windows build

The release workflow installs the MINGW64 GCC, NASM, pkgconf, zlib, Meson and Ninja toolchain with MSYS2. Run `bash scripts/build-media-tools.sh` from that shell, then run the normal Python/Node build steps. The build must produce x64 executables; staging rejects mismatched executable architecture, wrong FFmpeg versions, GPL/nonfree flags, or absent license/source records. Windows compilation and installed-app behavior must pass on a Windows runner before publication.

## License and source distribution

The app carries media license texts and `SOURCE.txt` under `backend/bin/licenses`. The source package contains the exact upstream FFmpeg and dav1d archives, the build script, and the configure record. Windows also carries the zlib license. `dist:release` copies a platform-specific `ffmpeg-8.1.2-<platform>-<arch>-source.tar.gz` alongside the installer. CI uploads and publishes these source packages with the installers. Keep these assets available for the corresponding release; do not publish just the installer.

FFmpeg's build configuration and notices are checked, but this is not an audit of every third-party component of Electron/OpenCV/Python. See https://ffmpeg.org/legal.html for FFmpeg's distribution guidance.

## Updates and support

The packaged app checks the public GitHub latest stable release after rendering. It coalesces requests, uses a five-second timeout and a one-day persistent cache, and never blocks capture on offline/rate-limit failures. Version comparisons are numeric and prereleases are excluded. A user may skip a version. Download opens the project's fixed releases page; no arbitrary URL from the response is opened. This is notification only, not automatic installation. Development mode does not poll GitHub.

yt-dlp remains pinned to 2026.8.19, the latest stable version returned by PyPI during the 2026-09-27 verification. Upgrading it requires refreshing the lock, package smoke tests and a live YouTube import. An unavailable test video is not proof that import works or is broken. Do not self-update Python files inside the frozen backend.

Diagnostic copy retains at most 100 recent backend log lines, redacts configured session tokens, credential lines, URLs and local user paths, and adds platform/app state. Nothing is submitted automatically. The user must review the copied report and paste it into an issue themselves.

## Signing boundary

On the inspected Mac there is an Apple Development identity but **no Developer ID Application identity**. Public macOS signing/notarization cannot be completed with that development identity. Keep unsigned builds explicitly identified until the distribution certificate and notarization credentials are configured. The existing local `DRUMSHEET_ENABLE_SIGNING` switch is available; CI remains intentionally unsigned. Windows signing credentials/service enrollment are likewise not configured by this change.

## v0.1.33 preflight corrections

Windows explicitly enables D3D11VA and DXVA2 despite disabled autodetection; this retains available hardware decode paths while software decoding remains the fallback. macOS exports MACOSX_DEPLOYMENT_TARGET=12.0 before building either dav1d or FFmpeg. The dav1d cache path includes the source version, platform and build-script hash so older archives cannot silently survive a flag change. The release job has a 60-minute timeout; this preflight intentionally exercises a cold build.

The actions/python-versions manifest checked on 2026-09-27 lists Python 3.11.15 only for Linux/RHEL, not macOS or Windows. `.python-version` therefore specifies 3.11, with locked Python dependencies and platform CI, rather than claiming identical patch binaries across platforms. Local uv and hosted setup-python can resolve different 3.11 patch versions; inspect Setup Python output when diagnosing differences.
