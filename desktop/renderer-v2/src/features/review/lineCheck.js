// The line-by-line check of a clean reflow chart: each printed line next to the video
// moments it came from (reflow.line_review via deriveReflowInfo().lines).

/** Opened by default when a printed line holds a view-jump seam (jump-view videos). */
export function lineCheckOpen(state) {
  const lines = state.review.reflow?.lines || [];
  if (!lines.length) return false;
  const open = state.review.lineCheck?.open;
  return typeof open === "boolean" ? open : lines.some(line => line.seams.length > 0);
}

// Whether the viewer shows the composed A4 pages. Until the user picks a view, the pages
// are the default, except when a jump video has seams left to check (or the line check
// was opened): then the line check comes first.
export function pagePreviewOn(state) {
  const choice = state.review.pagePreview;
  if (typeof choice === "boolean") return choice;
  const open = state.review.lineCheck?.open;
  return !(typeof open === "boolean" ? open : seamChecks(state.review.reflow?.lines || []).length > 0);
}

// The middle of each source display: the moment whose frame is shown next to the line.
export function lineSourceTimes(line) {
  const seen = new Set();
  return line.sources.map(source => Math.round(((source.tStart + source.tEnd) / 2) * 10) / 10)
    .filter(time => (seen.has(time) ? false : (seen.add(time), true)));
}

export function releaseFrameUrl(url) {
  if (String(url || "").startsWith("blob:") && typeof globalThis.URL?.revokeObjectURL === "function") globalThis.URL.revokeObjectURL(url);
}

/** 1-based position of a line on its page. */
export function lineNumberOnPage(lines, line) {
  return lines.filter(other => other.page === line.page).indexOf(line) + 1;
}

const CLIP_LEAD_SEC = 5; // the clip starts this long before the view jumps ...
const CLIP_TAIL_SEC = 5; // ... and ends this long after

// The places worth a look: every seam the app did not verify from the overlap alone, with the
// printed line(s) around it and the stretch of video around the moment the view jumped.
export function seamChecks(lines) {
  const seen = new Set();
  return lines.flatMap((line, index) => line.seams.filter(seam => seam.status !== "verified" && !seen.has(seam.id)).map(seam => {
    seen.add(seam.id);
    // "seam-ep-0003-ep-0004": the displays before and after the jump
    const [, a = "", b = ""] = /^seam-(.+?)-(ep-.+)$/.exec(seam.id) || [];
    const before = line.sources.find(source => source.display === a);
    const after = line.sources.find(source => source.display === b);
    const jump = before ? before.tEnd : after ? after.tStart : null;
    // a seam near a line end continues on the neighbouring line: show that one too
    // (a rebuilt seam that now splits two lines always does)
    const around = [seam.boundary === "start" || (!seam.boundary && seam.xFrac < 0.25) ? lines[index - 1] : null, line,
      seam.boundary === "end" || (!seam.boundary && seam.xFrac > 0.75) ? lines[index + 1] : null]
      .filter(other => other && other.page > 0);
    return { seam, line, lineNumber: lineNumberOnPage(lines, line), around, jump,
      clip: jump === null ? null : [Math.max(0, jump - CLIP_LEAD_SEC), jump + CLIP_TAIL_SEC] };
  }));
}

/**
 * The seams the next rebuild keeps unverified: the ones already kept so, plus every seam answered
 * "bad" since. null when no new "bad" answer waits for a rebuild (the request then leaves them as they are).
 */
export function pendingSeamRejections(state) {
  const committed = state.review.reflow?.rejectedSeamIds || [];
  const answers = state.review.lineCheck?.answers || {};
  const fresh = Object.keys(answers).filter(id => answers[id] === "bad" && !committed.includes(id));
  return fresh.length ? [...new Set([...committed, ...fresh])].sort() : null;
}
