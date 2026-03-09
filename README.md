# Drum Sheet Capture

Local desktop tool for capturing drum sheet pages from video and exporting PNG, JPG, or PDF.

## Guides

- [Korean User Guide](./README.ko.md)
- [English User Guide](./README.en.md)
- [Production Readiness Report](./docs/reports/2026-03-09-github-production-readiness-report.md)
- [GitHub Release Runbook](./docs/release/github-release-runbook.md)

## Release Targets

- Windows installer
- macOS DMG

Recommended public release build:

```bash
cd desktop
npm run dist:release
```

`dist:release` is the standalone GitHub release profile.
It keeps the bundled Python runtime and uses the compact packaging rules intended for end users.

Other build profiles:

- `npm run dist:full`: internal fallback package, largest size
- `npm run dist:compact`: compact standalone package, same payload class as release
- `npm run dist:lean`: smaller package that expects an external Python/runtime setup

## Repository Layout

- [`desktop/`](./desktop): Electron app
- [`backend/`](./backend): FastAPI processing engine
- [`docs/plans/`](./docs/plans): design and implementation plans
- [`docs/reports/`](./docs/reports): release-readiness reports
- [`docs/release/`](./docs/release): GitHub release and operations docs

## Developer Note

For local development:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

cd ../desktop
npm install
npm start
```

Run the desktop app from [`desktop/`](./desktop), where `package.json` exists.
