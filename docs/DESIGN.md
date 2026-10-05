# Drum Sheet Capture design brief

Status: selected and being implemented across all four steps: Floating Dock Canvas (2026-09-27). It supersedes the Light Side-Rail Workspace (2026-09-24). This document records product truths and the criteria for choosing the next interface. It does not approve the current CSS or require an Apple/Vercel look.

## Product and user

Drum Sheet Capture is a local desktop app that captures notation already visible in a video and saves PNG, JPG, or PDF files. It does not transcribe audio, recognize notes into MusicXML, or create MIDI.

The primary user has a video with an on-screen drum score and wants readable pages to practice, review, or share. They may use a local file or a public YouTube link. The app processes media locally after import; YouTube import needs network access.

The supported release targets are macOS Apple Silicon and Windows x64. The app opens at 1440×960 and has a 1120×840 minimum window. Korean and English are both product languages. Mobile is not a design target for this desktop release.

The editable automatic ROI suggestion exists in the current working tree. Treat it as unreleased until a release and installed-app flow verify it.

## What the design must help the user do

1. Find and prepare the right video without mistaking an import failure for an empty result.
2. Inspect a clear frame and place the score region without cutting off notes, lyrics, or repeat marks.
3. Understand whether an automatic region is only a suggestion, whether the user has edited it, and whether it has been applied.
4. Choose output settings and see honest progress and errors while pages are generated.
5. Compare captured pages, include or exclude them, fix a crop if needed, and save a PDF that reflects the current selection.
6. Locate, open, or copy the saved result without confusing the last generated PDF with unsaved review edits.

Success is a usable, readable output with a clear path to correct mistakes. Visual novelty is secondary.

## Working visual direction: score-first desktop workbench

This is a starting hypothesis to test with real screens, not a frozen palette.

- The video or score page is the visual center of each step. The shell, workflow navigation, and controls recede until needed.
- Give score paper a clear white surface and enough room to read symbols. Use a neutral surrounding workspace that separates paper, video, and controls without decorative effects.
- Use one restrained interactive accent for the primary action, keyboard focus, editable region, and currently viewed item. Do not rely on accent color alone to communicate inclusion, errors, or completion.
- Keep density appropriate for a mouse-and-keyboard desktop tool. Prefer short labels and nearby controls to large mobile-style blocks.
- Use system UI fonts and tabular numerals for timecodes, counts, and progress. Use monospace for technical paths only when it improves scanning.
- Separate areas through spacing, alignment, and thin dividers. Captured pages may be cards because each is an independent review item. Avoid cards nested only for decoration.
- Reserve depth for an actual elevated layer such as a modal or a score sheet. Avoid glow, decorative gradients, constant pulsing, and movement that does not explain state.
- Informational text, including captions and status labels, should reach at least 4.5:1 contrast against its real background. Disabled controls may be visually quieter but must remain identifiable.

The existing Apple and Vercel reference files under docs/design are historical inputs. Borrow a specific useful principle only after checking it against this workflow; neither brand is the desired identity.

## Screen hierarchy

| Step | Main artifact | Primary decision | Secondary information |
| --- | --- | --- | --- |
| Video | Selected file or import status | Open a local file or prepare a public YouTube video | Recent sources, metadata, detailed import log |
| Score region | Video frame with editable region | Choose the frame and apply the intended region | Suggested region evidence, timecode, keyboard help |
| Create files | Crop/output preview | Confirm formats and start generation | Output path, progress, error detail |
| Review and save | Large score image beside capture list | Decide inclusion/crop and rebuild output | Suspicion flags, page count, output location |

Within review, the checkbox means inclusion and the focused frame means currently viewed. They must remain distinguishable. A suggested ROI enters an editable draft; only the apply action makes it the capture region. Late automatic results must not overwrite user edits.

## States that must be designed

- No source yet; invalid or inaccessible YouTube link; preparation in progress or failed.
- Frame loading; no score region found; automatic suggestion available; manually edited draft; applied ROI.
- Export running, completed, failed, or blocked by incomplete input.
- Review with zero, few, and many captures; suspicious or excluded candidates; unsaved changes; saved output.
- Long Korean and English filenames, paths, labels, and error messages.
- Keyboard focus, disabled actions, reduced motion, and narrow supported desktop window.

A status should name what happened and the next useful action. Do not use a success-looking color or phrase for a pending, partial, or failed result.

## Selected visual direction: Floating Dock Canvas (2026-09-27)

The user judged the Light Side-Rail result as generic ("AI-made"): a page title and subtitle repeated the step tab, status appeared in three places, and more than fifteen equal-weight buttons competed on the review screen. Four styles were compared with the same review content (quiet pro tool, paper and red pencil, instrument panel, canvas editor); the user chose the canvas-editor style (Figma/Framer). Three header-free arrangements were then compared (floating dock, bottom timeline, all-in-one sidebar); the user chose the floating dock. Comparison pages: `design/design-directions.html`, `design/canvas-layouts.html`, `design/floating-dock-flow.html`.

- No top header. A narrow floating dock at the far left holds the four steps (number, or a check when complete), archive, language, and a single engine-status dot.
- Beside the dock, one floating panel per step holds the step title, the file name, and that step's controls. It replaces the page headline band.
- Everything else is a neutral dotted canvas. The artifact (video frame, output preview, captured score) sits on it as paper with real elevation.
- One next action per step floats at the top right of the canvas (apply region, create files, rebuild/save). Secondary output actions stay compact (see Review refinement, 2026-10-05).
- Canvas tools (zoom, fit, crop, undo) float as one toolbar at the bottom centre of the canvas.
- Status is quiet by default. A floating notice appears only for an inline message or a backend problem that needs recovery.
- A single blue accent for primary action, selection, focus and the editable region. Text uses a darker blue that keeps 4.5:1 contrast. Warnings stay orange-red. System fonts with tabular/monospace numerals for times and counts.
- Review list thumbnails follow the captures' shape (see Review refinement, 2026-10-05); cards no longer use square thumbnails.
- Not yet implemented and tracked as follow-up product work: composed PDF-page preview on the export/review canvas and a change-point scrubber on the ROI screen. Until then the canvas shows the existing crop preview and capture image.

## Superseded visual direction: Light Side-Rail Workspace (2026-09-24)

The user approved Proposal A's left-list / right-artifact composition, then explicitly extended the scope to the whole application. They rejected the dark aesthetic as generic and welcomed Airbnb-like brightness and clarity. This direction supersedes the Review-only dark implementation.

Two arrangements were compared for the export screen with the same settings and score: (A) shared top navigation, 290px settings at left, large score at right; (B) permanent step rail plus right settings inspector, leaving two sidebars around the score. Choose A: it carries the already approved Review structure to each step and leaves more width for actual media. See `design/light-workspace-layouts.svg`.

- All four steps share one compact top navigation and the same light surfaces, typography, controls and status line. Source/ROI/Export/Review, archive and metadata dialogs use common tokens.
- Source: a left import area for local files and secondary YouTube input; recent videos occupy the larger right area.
- ROI: left time controls, candidate frames, draft status and explicit apply action; large editable video frame at right. Automatic suggestions remain drafts and preserve user edits.
- Export: left output format/settings; right capture preview and honest progress. Keep metadata confirmation and cancellation behavior.
- Review: keep the 290px capture rail, clear inclusion versus viewing state, and unobstructed score. Dock editing controls below the image; preserve undo/redo/crop reset and saved-file semantics.
- White surfaces, pale neutral canvas, charcoal primary buttons, deep teal focus/selection and restrained warning colors. Use whitespace and thin dividers before cards. No glass blur, gradients, pulsing, or decorative icon boxes.
- Local system fonts, readable secondary text, tabular times/counts. Preserve native input affordances and keyboard focus.
- Airbnb is a reference for content hierarchy and airy light surfaces, not a request for travel cards, branding, pink gradients or mobile-size spacing. Reference: https://www.airbnb.com/stays/design .
- Inputs may be portrait or landscape. Never assume A4 or claim that fit-to-window makes every note readable; preserve zoom and natural aspect ratios.

## Verification before calling the redesign complete

- Inspect Source, ROI, Create files, and Review at 1440×960 and 1120×840, in Korean and English.
- Use real or representative video-score content. Check that notation remains readable and editing handles do not hide it.
- Exercise keyboard navigation, focus, long text, loading, error, selection, and unsaved-output states.
- Run renderer and relevant desktop/backend tests, then distinguish tested source behavior from packaged macOS and Windows behavior.
- Record any unresolved usability issue or platform gap instead of describing the redesign as fully verified.

## Scoped workflow additions (2026-09-27)

Preserve the Floating Dock Canvas visual system. Capture start/end inputs live in the existing export inspector, before the processing profile. Blank endpoints mean the full source; accept seconds and minutes:seconds (hours also supported). Reject invalid ordering and ranges beyond known duration before a job is submitted. Lock edits during capture or metadata confirmation, preserve existing output until a new capture actually starts, and reset the range on source replacement.

Keep update availability in the existing quiet status notice, with a releases-page action and per-version dismissal. Backend startup shows a preparation message; recovery actions appear after startup, with diagnostic copy and a user-initiated issue link on failures. No remote log submission and no new full-screen loading screen. PDF composition preview and change-point scrubber remain separate follow-up product work.

## Detail polish pass (2026-09-28)

Same Floating Dock Canvas system; this pass removes the unfinished feel without changing layout or behavior.

- Signature: capture-frame corners (the ROI handle shape) mark the app mark in the dock and the source drop target, instead of a letter "D" and a dashed box.
- Numbers: timecodes, counts, sizes and dates use system sans with tabular numerals. The monospace font is no longer applied to Korean text, dates or file-size lines, where it spread word spacing.
- Korean wraps between words (`word-break: keep-all`); headline subtitles wrap to two lines instead of an ellipsis.
- Panel hierarchy: section title 13px/650 primary text, helper 12px secondary text, values in primary text; export modules are separated by one divider each.
- Controls: one inset treatment for text fields (hover border, accent border plus focus halo); checkboxes use the accent; disabled secondary buttons are a flat recessed fill; buttons press to 0.98 scale over 120ms.
- A lone next-step action floats as a single elevated button, not a button inside a second white frame.
- Dock tools use one drawn 18px icon set (archive, update, report) with a matching update dot.
- Review status uses drawn dots: amber for "needs review", red for "exclude candidate", amber for unapplied selection. Warnings no longer paint most of the list red.
- ROI representative frames are a three-row list (label left, time right); the draft/applied note is a dot plus text instead of another bordered box.
- Dialogs dim the whole window including the dock, place the primary action last (right), and enter with a 180ms fade/scale that reduced-motion disables.

## Motion and detail refinement (2026-09-28)

Preserve Floating Dock Canvas and existing work in progress. The authored moment is the transition between workflow steps: only the inspector contents settle in, while the dock, paper, and editing coordinates stay still. Trigger this on step changes, never on progress updates, typing, or capture selection. Use the existing ease-out and duration tokens; no new animation dependency.

- Dialog entry runs once per opening, with a coordinated backdrop. Pointer dismissal leaves a short inert visual fade; state and focus restore immediately. Keyboard navigation and reduced motion remain immediate.
- Notices use an interruptible opacity/translation transition instead of replaying a keyframe. Hidden notices cannot receive focus or pointer input.
- Keep pointer press feedback at 0.98; exclude keyboard focus and reduced motion. Cancel running motion when the preference changes or the app is destroyed.
- Remove doubled heading spacing in export modules, strengthen the keyboard focus outline, and keep panel scroll gutters stable. Preserve Korean/English content and all capture/ROI/export semantics.

## Review refinement (2026-10-05)

Same Floating Dock Canvas system. The review screen looked unfinished because several equal-weight toolbars competed with the score, one state was marked several ways, and thumbnails ignored the captures' shape. Each floating group now has one job and a fixed place.

- Top right: save status, then the rebuild and open-PDF buttons (whichever is the next step is primary), then Save As and Open folder as icon buttons with tooltips and accessible names. While rebuilding, the status reads a short "Rebuilding…"; the long explanation stays in the panel footer.
- Current-capture bar: centred on the paper's axis below the save actions. Previous/next chevrons around the capture name and position, then one "Included in output" checkbox (replacing an inclusion label plus a toggle button), then any flags and the compare action. Warning and similarity notes wrap inside the bar; the paper's top padding grows when they are present.
- Bottom canvas tools: zoom out/in (icons), Fit and 100% (pressed state shown) | undo/redo (icons, shortcut in tooltip) | crop and reset crop. The shortcut line appears only while the keyboard is in use on this screen. Keyboard focus stays on the canvas after a shortcut re-renders the screen.
- Capture list: the row background and left bar mean "currently viewed"; the checkbox alone means "included". The thumbnail has no accent frame, the capture is named once (beside its checkbox), and excluded thumbnails stay at 50% opacity so they can be re-checked.
- One thumbnail layout per list, chosen from the median measured aspect ratio of loaded thumbnails: wide strips span the row with name and flags on one line below; portrait pages (aspect < 1.15) show as a 76px page beside name and flags. Thumbnails are never cropped. Timecodes appear only when capture times exist (not yet provided by the job result).

