# Drum Sheet Capture

Local Electron and Python desktop app that captures scores already shown in videos and exports PNG, JPG, and PDF. It does not transcribe audio into notation.

## Project boundaries

- Preserve the working source video, editable ROI, capture selection, and generated files. Inspect existing uncommitted work before editing it.
- Keep an automatic ROI suggestion as an editable draft. Applying the ROI is a separate user action; a late suggestion must not replace a user edit.
- Do not describe source tests or browser fixtures as proof of a packaged macOS or Windows workflow.

## UI work

- For a substantial new UI or redesign, read [.codex/AGENTS.md](.codex/AGENTS.md) and [docs/DESIGN.md](docs/DESIGN.md). Update the design brief with the chosen direction before changing the visual system.
- Redesign may replace the visual layout and styling. Preserve capture, ROI, export, and review behavior unless the task explicitly changes it. A framework migration is not part of a visual redesign.
- For a small UI fix, inspect the affected screen and shared styles, make the local change, and verify it; the full design exploration is unnecessary.

## Verification

- Renderer/UI changes: run npm --prefix desktop run verify:renderer-v2 and inspect the rendered screen at the default 1440×960 and minimum 1120×840 desktop sizes when layout is affected.
- Desktop process changes: run npm --prefix desktop run test:desktop-node.
- Backend changes: run PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'.
- Check the affected Korean and English labels, keyboard focus, and relevant loading, error, and long-content states. Report any platform or real-media flow that was not exercised.
