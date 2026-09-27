# UI design protocol for Drum Sheet Capture

Read this file for a substantial UI redesign or a new screen. The root AGENTS.md identifies when it applies. This file is a task-specific playbook, not a second automatically discovered project instruction file.

## Goal and scope

The user should be able to take a video that already shows a drum score, choose the visible score area, capture pages, inspect them, and save usable files. Good design makes those decisions clear and keeps the score readable.

A visual reset may replace the current look. Do not assume the current Apple/Vercel styling, existing CSS tokens, or this protocol's examples are the final aesthetic. Keep product facts and working behavior. Do not turn a visual task into a backend rewrite or framework migration.

## Before drawing

1. Inspect the affected workflow in the running app or a current fixture, the source components, and docs/DESIGN.md. Treat old screenshots as evidence of problems, not a style to copy.
2. Name the user's decision at each screen and the main artifact they need to inspect: source video, score region, output preview, or captured page.
3. Identify current friction with concrete evidence. Separate broken behavior, unclear hierarchy, low readability, and mere taste.
4. Check the actual supported environment: macOS Apple Silicon and Windows x64 desktop, 1440×960 default window, 1120×840 minimum window, Korean and English. Mobile is outside the current product target.

## Choose a direction

- Start from the score and video. Let their contrast, dimensions, and editing needs determine the surrounding surfaces.
- For a broad redesign, sketch two materially different arrangements of one representative screen before committing to a visual system. Compare the same realistic content and state in both.
- Judge candidates by task completion, readability, error prevention, and recovery. Do not ask the user to choose fonts, hex colors, or design jargon.
- If a choice remains subjective, show the user concrete screen images and ask which is easier to use. If the evidence clearly favors one candidate, select it and record the reason.
- Update docs/DESIGN.md with the selected direction and its status. Record decisions that guide code; do not fill a long template with invented preferences.

## Design rules for this product

- Source: make local file selection obvious; keep public YouTube input available but secondary. Show recent sources and failures clearly.
- ROI: the video frame and score-region editor dominate. Distinguish suggested draft, user-edited draft, and applied region. Keep manual adjustment visible.
- Export: show what will be captured, which formats are selected, what is running, and what failed. Progress must not imply success before files exist.
- Review: the score image is the main artifact. Make inclusion selection and currently viewed capture distinct. Keep rebuild, open PDF, Save As, and output-folder actions understandable.
- Group related controls by proximity and dividers before adding boxes. Use a card when an item is independently selectable or needs containment, such as a captured page.
- Use color for action, focus, selection, and warnings. Decorative glow, gradients, repeated badges, and motion need a product reason. Shadows may convey actual elevation, such as a modal or score sheet, but should not decorate every control.
- Prefer system fonts that work without a network request. Use tabular numerals for timecodes and counts. Keep informational small text readable; target at least 4.5:1 text contrast against its actual background.
- Keep keyboard focus visible and honor reduced-motion settings. Compact desktop controls are acceptable when labels, spacing, and hit areas remain usable.

## Verify the result

- Render the changed screens at 1440×960 and 1120×840. Inspect Korean and English with long filenames, paths, and labels.
- Check a source-empty state, an invalid or failed YouTube import, ROI draft versus applied state, export progress/error, and review with many pages and suspicious captures when affected.
- Follow at least one realistic path from source to review. A static screenshot and passing DOM tests alone do not establish the packaged application flow.
- Run the relevant commands in root AGENTS.md. Report exactly what ran and which real-media, native-dialog, macOS, or Windows checks remain unverified.
- Fix concrete layout, contrast, focus, and state issues found in the rendered result before calling the design complete.
