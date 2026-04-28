# Score Capture Program Design Notes

## Register

Product UI. Design should disappear into the task: choosing a video, selecting the score region, checking captured pages, and exporting a usable PDF.

## Visual Direction

- Calm desktop utility, not a futuristic control panel or a web dashboard.
- Muted gray-green desktop surfaces with restrained teal accent for primary actions, selected state, progress, and focus.
- Avoid broad white canvases. The default work area should feel like a local tool surface under the user's hands, not a bright web page.
- PDF and score surfaces may use a subtle paper tone, but the app should not read as a beige theme.
- Avoid amber-heavy, neon, dashboard, glass, and decorative radial effects.

## Components

- Keep standard product controls: buttons, checkboxes, select fields, tables, rails, and modals.
- Use one compact system-font stack for labels, buttons, headings, and data.
- Cards and panels stay shallow: 4px radius, low shadow, clear borders.
- Shell chrome should stay quiet. Source, ROI, Export, and Review work surfaces must read before top bar, rail, or context lane.

## Interaction Rules

- Source: the file-open action is the first visual target.
- ROI: the frame and region editor dominate.
- Export: preview remains the primary surface; document metadata stays modal-only for PDF export.
- Review: page grid remains the primary surface; apply action belongs to the grid workflow.
