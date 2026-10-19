# Drum Sheet Capture User Guide

Turn a drum score that is already shown in a video into an A4 PDF. You choose the score region once; the app reads the score lines shown in the video, cleans the original score images, and lays them out again on A4, measure by measure. PNG and JPG are also available.

The app does not transcribe audio, recognize notes, or export MusicXML/MIDI.

[Download the latest release](https://github.com/kr-ericshim/drum-score-capture-tool/releases/latest) · [Project home (Korean)](./README.md) · [한국어 가이드](./README.ko.md)

This guide follows v0.3.0. Installers up to v0.2.1 use the earlier method, which captures score screens as page images, so their screens and results differ. Check the [release notes](https://github.com/kr-ericshim/drum-score-capture-tool/releases) for your installed version.

[Supported videos](#supported-videos) · [Installation](#installation) · [Workflow](#workflow) · [Output](#output) · [Shortcuts](#shortcuts) · [Troubleshooting](#troubleshooting)

## Supported videos

| Video | Status |
| --- | --- |
| **One score line** on an opaque plate (light or dark background) that is replaced as a whole by the next line | Supported |
| The view jumps sideways within one line (jump view) | Experimental. Joins the app inferred must be compared with the video under **Check the joins** in review. |
| Score drawn over a translucent plate or over moving video | Refused, with a message that it is not supported. |
| Score that flows sideways, or several lines that scroll up together | Refused, with a message that it is not supported. |
| Several lines shown as one page, or a tall score rolling vertically | Out of scope. Results are not guaranteed. |

A screen shown for less than about half a second can be missed. Compare the PDF with the video once before you play from it.

## Installation

Download the file for your computer from **Assets** on the release page. The source code ZIP is not an installer.

| Computer | Download |
| --- | --- |
| Windows x64 — Intel/AMD 64-bit | `.exe` installer |
| macOS Apple Silicon — M-series, macOS 13 (Ventura) or later | `arm64.dmg` |

Python, Node.js, and FFmpeg do not need to be installed separately. Intel Mac, native Windows ARM64, and Linux installers are not provided.

### Windows

1. Download the `.exe` under **Assets** and run it.
2. Open Drum Sheet Capture.
3. The installer is unsigned, so SmartScreen may show a warning. After confirming the file came from this repository, use **More info → Run anyway** if offered. Managed computers may enforce a different policy.

### macOS

1. Download `arm64.dmg` from **Assets**.
2. Open it and copy **Drum Sheet Capture.app** to `Applications`.
3. Launch the copied app.

The macOS app has a free ad-hoc signature only. It is not Developer ID signed or notarized, so macOS may block the first launch. After verifying the download came from this repository, use **System Settings → Privacy & Security → Open Anyway**. Managed Macs may restrict this option.

Only if that option is unavailable, remove quarantine from the trusted installed app and reopen it. This does not repair an invalid signature:

```bash
xattr -dr com.apple.quarantine "/Applications/Drum Sheet Capture.app"
```

If “damaged” persists, download the latest installer again or report the issue instead of disabling system-wide security.

On macOS 12, keep using v0.1.37 and do not press Update in the app. From v0.2.0 the app needs macOS 13 or later.

## Workflow

The steps on the left are **Source → Score region → Create files → Review & save**. A saved language preference wins; otherwise Korean system locales start in Korean and others in English. Switch with **KO** / **EN** at the bottom left.

### 1. Source

Choose **Open video** or drop a file on the window. MP4, MKV, MOV, AVI, and WEBM are accepted. The picker opens in the folder you used last.

For YouTube, paste the link and press Enter or **Prepare video**. Progress details are under **Details**. Videos you used before are listed under **Reopen recent**; if you moved or deleted the original file, choose it again. Once a video is ready, the panel shows its name, resolution, and length with **Next: Score region**.

### 2. Score region

1. Pick a frame where the score is clear: **Earlier**, **Recommended**, or **Later** under **Representative frame**, or move the **Time** slider and choose **Refresh current frame**.
2. Check the suggested region and drag the region or its corners if needed. If there is no suggestion, draw one.
3. Make sure notes, lyrics, and repeat marks are inside, then choose **Apply region**. **Apply and make PDF** applies and starts the PDF at once.

A suggestion is an editable draft; only **Apply region** confirms it. A late suggestion never replaces your edit. If you edit after applying, apply again.

- **Follow white score edges** snaps to the white score background only when its edges are clear inside your region.
- **Add a section-label area**: when section names (for example Verse, A, B) are drawn outside the score region, mark them as a separate area. They are placed above the matching line as the original image, not retyped.
- After you apply, the app checks the whole video for score parts outside the region. If the top or bottom is cut, **Use suggested area** loads a larger region as a draft.

### 3. Create files

Optionally set **Capture range** **Start** and **End** as seconds (`90`) or minutes:seconds (`1:30`). Leave both empty for the whole video; with only a start, it runs to the end.

**Make PDF** starts at once without a details dialog; the title comes from the video name. To add title, performer, BPM, date, or memo first, choose **Edit PDF details…**. The details go on the first PDF page.

For PNG or JPG, open **More options** and choose **PNG images** or **JPG images**. They use the same pages as the PDF.

Progress shows while it runs, and **Cancel capture** stops it. A notification appears when it finishes; check the result in **Review & save**.

### 4. Review & save

The list on the left holds the **score lines** that go into the PDF, in order. Select a line to view it large; its checkbox means **Included in output**. The row background marks the line you are viewing; only the checkbox marks inclusion.

- **Move up / Move down** change the order. The default order is the order the video shows the lines; when a repeat or D.S. shows an earlier line again, it is placed again.
- **Looks similar** marks a line that resembles an earlier one. Use **Compare side by side**; if it is a duplicate, choose **Leave this one out**. Keep it if it is a real repeat.
- **Transition fragments (N)** and **Other moments (N)** hold screens or marks shown only briefly. They are listed unchecked; only checked items go into the score.
- **Page view / System view** switch between the last built pages and single lines.
- **Rearrange by measure (about 4 per line)** is on by default. Turn it off to keep the lines as the video showed them.
- **Review required** and **Incomplete** mean parts were cut in the source, a mark was hard to separate, or a stretch of the video had no score found. Compare the named lines and ranges with the video.
- **Check the joins** (jump view): play the video at each join the app inferred. If you answer **A measure repeats or is missing** and rebuild, that join is not made and both screens are kept.
- If a line does not fit on the page, leave it out or choose **Use N mm for this document** to make the score smaller.

Changes reach the file only after **Rebuild PDF**. Rebuilding does not capture the video again. **Edit title** rebuilds the PDF with a new title only.

Open the result with **Open PDF**, and keep a copy with the **Save PDF as…** icon button; the dialog opens in the folder you used last. Copy PNG/JPG files from **Open folder**. **Open another video** starts the next song.

## Output

### Clean reflow (default)

The app collects the score lines shown in the video, removes the video background and playback marks, splits lines at measure boundaries, and fits them to the A4 width using the original score images. Notes are never redrawn; section labels, tempo, and lyrics stay as source images. A low-resolution source stays low-resolution.

### Original screens (fallback)

If the cleaned result looks wrong, choose **Rebuild as original screens** under the review list. The PDF then holds the video screens as they are; the same part may repeat. It is available only for videos that show one score line at a time. **Open original images folder** shows the screen images.

## Archive and storage

**Archive** at the bottom left lists the last PDF made for each video, with **Open PDF**, **Open Folder**, and **Reopen Source**. It shows files in the app's working folder; it is not a backup. Jobs that made only PNG/JPG do not appear.

**Archive → Clear cache** shows the space used. After reading the confirmation, choose **Delete all**. It deletes captures, generated PDFs/images, downloaded YouTube videos, and archive/recent-video history inside the app's working folder. Original local videos and files saved with **Save PDF as…** remain. Deletion cannot be undone and is disabled while work is running.

## Shortcuts

| Screen | Key | Action |
| --- | --- | --- |
| Score region | `Tab` | Focus the region editor |
| Score region | Arrow keys | Move the region |
| Score region | `1`–`4` | Choose a corner to resize |
| Score region | `0` | Switch back to moving the whole region |
| Score region | `Shift` + arrow | Larger steps |
| Review & save | `←` / `→` | Previous / next line |
| Review & save | `Space` | Include / exclude the viewed line |
| Review & save | `Ctrl+Z` / `⌘Z` | Undo |
| Review & save | `Ctrl+Shift+Z` / `⌘Shift+Z` | Redo |

Region shortcuts work while the editor has focus. Review shortcuts do not work in text fields; when a button has focus, Space presses that button.

## Good to know

- Video processing runs locally. YouTube import needs an internet connection.
- The installed app checks GitHub for a new version at launch and when you press **Update**. It downloads only after you choose **Update**, verifies the checksum, and installs when you choose **Restart to install**. On macOS, if the app runs from somewhere it cannot replace itself (inside the DMG or a read-only folder), it opens the installer window instead.
- **Report** sends only when you press **Send**: what you wrote, plus the diagnostics and app screenshot if you keep them checked. Videos and generated files are never sent; a screenshot includes the score on screen.
- Sign-in, age, or region restrictions and YouTube changes can prevent imports.
- A supported extension does not guarantee that every codec or damaged file can be read.
- Working videos and intermediate files use much more disk space than the installer.
- Installed builds keep working data in a `jobs` folder under the app's user data folder. Development runs use `backend/jobs`.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Processor does not connect | Fully quit and reopen the app. If it persists, use **Copy diagnostics** and report it. |
| YouTube import failed | Check that the link is public and read the error under **Details**. If you have the video as a file, use **Open video**. |
| Low resolution notice | Use a higher-resolution video or the original file. |
| "Not supported" for the video | See [Supported videos](#supported-videos). Translucent plates, scores drawn over video, and sideways or multi-line scrolling are refused. |
| No score lines found in the region | Go back to **Score region** and apply a region that holds the whole staff. |
| Notes or marks are cut off | Widen the region in **Score region**, apply, and create the files again. Review cannot restore parts that were cut. |
| A line is missing or appears twice | Check **Review required**, **Incomplete**, and **Looks similar** in review, fix the lines, and choose **Rebuild PDF**. For one-line videos you can also rebuild as original screens. |
| The PDF does not show your changes | Choose **Rebuild PDF**, then open the new file with **Open PDF**. |
| Nothing in Archive | Check that the job made a PDF and that its file was not moved or deleted. |

Report unresolved issues with **Report** in the app or in [Issues](https://github.com/kr-ericshim/drum-score-capture-tool/issues). Include the app version, OS and CPU, the video (link or kind), the steps, and the error message. GitHub issues are public; remove private file paths and links from logs first.

## Development and builds

Source setup, tests, and build commands are in the [project README](./README.md#development). Maintainers should use the [release runbook](./docs/release/github-release-runbook.md).
