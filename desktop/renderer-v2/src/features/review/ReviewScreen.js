import { formatSecondsLabel, hasPendingRoiDraft, isReviewableRun, reviewListPages, summarizeSelection } from "../../app/session/selectors.js";
import { pickLocalizedText, reflowReviewReasonText, t } from "../../lib/i18n.js";
import { fileUrl, normalizeAssetPath } from "../../lib/paths.js";
import { thumbShapeFor } from "./thumbShape.js";
import { lineCheckOpen, lineNumberOnPage, lineSourceTimes, pagePreviewOn, seamChecks } from "./lineCheck.js";

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// "Needs a look" marks a row only while it singles some rows out; on every row it says nothing.
function renderPagePills(page, locale, markCheck = true) {
  const pill = (kind, key) => `<span class="review-inline-pill review-inline-pill-${kind}">${escapeHtml(t(`review.${key}`, { locale }))}</span>`;
  const looksSimilar = page.similarTo?.reason === "looks_similar";
  return [
    page.autoExcludeCandidate ? pill("exclude", "excludeCandidate") : "",
    markCheck && page.suspicious && !page.autoExcludeCandidate ? pill("risk", "check") : "",
    page.similarTo ? pill("similar", looksSimilar ? "looksSimilar" : "similar") : "",
  ].join("");
}

// One row per capture: the checkbox owns inclusion, the row background owns "currently viewed".
function renderPageCard(page, selected, focused, locked, locale, markCheck = true) {
  const pageId = escapeHtml(page.id);
  const pageTitle = escapeHtml(page.title);
  const previewPath = escapeHtml(normalizeAssetPath(page.previewPath));
  const includeAriaLabel = escapeHtml(t("review.includeAria", { locale, replacements: { title: page.title } }));
  const pills = renderPagePills(page, locale, markCheck);
  return `
    <article class="review-card ${selected ? "is-selected" : "is-excluded"} ${focused ? "is-focused" : ""}" role="listitem">
      <button class="review-card-figure" type="button" data-action="focus-review-page" data-page-id="${pageId}" ${focused ? 'aria-current="page"' : ""}>
        <img src="${previewPath}" alt="${pageTitle}" loading="lazy" />
      </button>
      <div class="review-card-meta">
        <label class="review-card-include">
          <input aria-label="${includeAriaLabel}" data-action="toggle-review-page" data-page-id="${pageId}" type="checkbox" ${selected ? "checked" : ""} ${locked ? "disabled" : ""} />
          <span title="${pageTitle}">${pageTitle}</span>
          ${page.timeLabel ? `<span class="review-card-time">${escapeHtml(page.timeLabel)}</span>` : ""}
        </label>
        ${pills ? `<div class="review-card-badges">${pills}</div>` : ""}
        ${locked ? `<small class="review-card-locked">${escapeHtml(t("review.locked", { locale }))}</small>` : ""}
      </div>
    </article>
  `;
}

function similarNoteText(page, locale, referenceTitle = "") {
  const similar = page?.similarTo;
  if (!similar) return "";
  // A reflow system is named by its own title (video order), not its list position.
  const reference = referenceTitle && page.kind === "system" ? referenceTitle
    : similar.referenceIndex
      ? t("selector.pageTitle", { locale, replacements: { index: similar.referenceIndex } })
      : t("review.previousPage", { locale });
  if (similar.reason === "looks_similar") {
    return t("review.looksSimilarNote", { locale, replacements: { reference } });
  }
  if (similar.reason === "playhead_reset") {
    return t("review.similarNotePlayhead", { locale, replacements: { reference } });
  }
  if (similar.reason === "recent_return") {
    return t("review.similarNoteReturn", { locale, replacements: { reference } });
  }
  if (similar.reason === "low_alignment_confidence") {
    return t("review.similarNoteAlign", { locale, replacements: { reference } });
  }
  return t("review.similarNote", { locale, replacements: { reference, count: similar.changeCount } });
}

function renderChangeBoxes(boxes, locale) {
  const label = escapeHtml(t("review.changeBox", { locale }));
  return (boxes || []).map((box) => {
    const pct = (value) => `${(Number(value) * 100).toFixed(2)}%`;
    return `<span class="review-change-box" role="img" aria-label="${label}" style="left:${pct(box.left)};top:${pct(box.top)};width:${pct(box.width)};height:${pct(box.height)}"></span>`;
  }).join("");
}

function renderCompareStage(focused, reference, locale) {
  const boxes = focused.similarTo?.changeBoxes || [];
  // Wide (landscape) captures stack so each keeps the full width; portrait pages sit side by side.
  const stacked = Number(focused.similarTo?.frameAspect || 0) >= 1.2;
  const frame = (page, caption, extraClass = "") => `
    <figure class="review-compare-frame ${extraClass}">
      <div class="review-compare-canvas">
        <img src="${escapeHtml(normalizeAssetPath(page.previewPath))}" alt="${escapeHtml(page.title)}" />
        ${renderChangeBoxes(boxes, locale)}
      </div>
      <figcaption>${escapeHtml(caption)}</figcaption>
    </figure>`;
  const referenceCaption = reference
    ? t("review.compareReference", { locale, replacements: { title: reference.title } })
    : t("review.previousPage", { locale });
  return `
    <div class="review-compare-stage ${stacked ? "is-stacked" : "is-side-by-side"}" data-review-compare>
      ${reference ? frame(reference, referenceCaption, "is-reference") : `<div class="review-compare-missing">${escapeHtml(t("review.compareMissing", { locale }))}</div>`}
      ${frame(focused, t("review.compareCurrent", { locale, replacements: { title: focused.title } }), "is-current")}
    </div>`;
}

function formatMm(value) {
  return Number(value).toFixed(2).replace(/0$/, "");
}

// Clean reflow facts: layout conflict (with the explicit smaller-size choice), a size
// the user chose, pending "looks similar" suggestions, short displays left out or
// listed unchecked, and section labels outside the score region. An automatic size
// and the marks left to "other moments" are the app's own choices and are not reported.
function renderReflowNotes(info, locale, busy, reasonsOpen = false) {
  if (!info) return "";
  const tt = (key, replacements = {}) => escapeHtml(t(`review.${key}`, { locale, replacements }));
  const notes = [];
  if (info.incomplete) notes.push(renderIncompleteNote(info, locale));
  if (info.reviewRequired) {
    const reasons = info.reviewReasons || [];
    // the reasons are folded: the note says what to do, the reasons say why
    notes.push(`<div class="review-reflow-note is-warning" role="alert" data-review-required>
      <p><strong>${tt("reviewRequiredTitle")}</strong> ${tt("reviewRequiredDetail")}</p>
      ${reasons.length ? `<button type="button" class="review-link-button review-reasons-toggle" data-action="toggle-more" data-value="reviewReasons" aria-expanded="${reasonsOpen}" aria-controls="reviewReasonsList">${tt(reasonsOpen ? "reviewReasonsHide" : "reviewReasonsShow", { count: reasons.length })}</button>
      <ul id="reviewReasonsList" class="reflow-review-reasons" aria-label="${tt("reviewReasonsLabel")}" tabindex="0" ${reasonsOpen ? "" : "hidden"}>
        ${reasons.map(reason => `<li>${escapeHtml(reflowReviewReasonText(reason, locale))}</li>`).join("")}</ul>` : ""}
    </div>`);
  }
  if (info.conflict) {
    const systems = info.conflict.systemNumbers.map(n => t("selector.systemTitle", { locale, replacements: { index: n } })).join(", ");
    const requested = formatMm(info.conflict.requestedMm ?? info.defaultStaffGapMm);
    const offered = info.conflict.offeredMm;
    // why the automatic size did not resolve it: the fitting size is below the automatic floor
    const belowAuto = offered && info.conflict.sizeReason === "BELOW_AUTO_MINIMUM"
      ? `<p>${tt("conflictBelowAuto", { size: formatMm(offered), min: formatMm(info.conflict.autoMinMm) })}</p>` : "";
    notes.push(`<div class="review-reflow-note is-conflict" role="alert">
      ${info.conflictPending ? `<p><strong>${tt("conflictPendingTitle")}</strong> ${tt("conflictPendingDetail")}</p>` : ""}
      <p><strong>${tt("conflictTitle")}</strong> ${tt("conflictDetail", { systems, size: requested })}</p>
      ${belowAuto}
      ${offered ? `<button type="button" class="button button-secondary" data-action="review-use-staff-size" data-size="${escapeHtml(offered)}" ${busy ? "disabled" : ""}>${tt("useSmallerStaff", { size: formatMm(offered) })}</button>`
        : `<p>${tt("conflictNoSize")}</p>`}
    </div>`);
  }
  if (info.smallerStaff && !info.conflict) {
    notes.push(`<div class="review-reflow-note is-info" role="status">
      <p>${tt("staffSizeChosen", { size: formatMm(info.staffGapMm) })}</p>
      <button type="button" class="button button-secondary" data-action="review-use-staff-size" data-size="${escapeHtml(info.defaultStaffGapMm)}" ${busy ? "disabled" : ""}>${tt("resetStaffSize", { size: formatMm(info.defaultStaffGapMm) })}</button>
    </div>`);
  }
  if (info.measureReflow?.fellBack) {
    notes.push(`<p class="review-reflow-note is-warning" role="status">${tt("measureFallback")}${info.measureReflow.reason ? ` <small class="review-reflow-code">${tt("measureFallbackReason", { reason: info.measureReflow.reason })}</small>` : ""}</p>`);
  }
  if (info.labelsOutsideRoi) {
    notes.push(`<p class="review-reflow-note is-warning" role="status">${tt("labelsOutsideRoi")}</p>`);
  }
  if (info.suggestionsState === "pending") {
    notes.push(`<p class="review-reflow-note is-pending" role="status">${tt("similarPending")}</p>`);
  }
  if (info.listedShort || info.hiddenShort) {
    const parts = [];
    if (info.listedShort) parts.push(t("review.shortListed", { locale, replacements: { count: info.listedShort } }));
    if (info.hiddenShort) parts.push(t("review.shortHidden", { locale, replacements: { count: info.hiddenShort } }));
    notes.push(`<p class="review-reflow-note is-info">${escapeHtml(parts.join(" "))}</p>`);
  }
  return notes.length ? `<div class="review-reflow-notes">${notes.join("")}</div>` : "";
}

// An incomplete chart (a jump-view interval stayed unresolved): said plainly, with every
// unresolved time range. A long list scrolls inside the note (focusable, so it scrolls by keyboard).
function renderIncompleteNote(info, locale) {
  const tt = (key, replacements = {}) => escapeHtml(t(`review.${key}`, { locale, replacements }));
  const ranges = info.unresolvedRanges || [];
  const listLabel = tt("incompleteRangesLabel", { count: ranges.length });
  return `<div class="review-reflow-note is-incomplete" role="alert" data-review-incomplete>
      <p><strong>${tt("incompleteTitle")}</strong> ${tt(ranges.length ? "incompleteDetail" : "incompleteDetailNoRanges", { count: ranges.length })}</p>
      ${ranges.length ? `<ul class="review-coverage-ranges" aria-label="${listLabel}" ${ranges.length > 4 ? 'tabindex="0"' : ""}>
        ${ranges.map(range => `<li>${escapeHtml(range.label)}</li>`).join("")}
      </ul>` : ""}
    </div>`;
}

// Several short transition displays (page curls, fades, brief flashes) are one collapsed
// group instead of a row each; every one keeps its own checkbox to restore it.
function renderFragmentGroup(list, selectedSet, focused, busy, locale, markCheck) {
  if (!list.grouped) return "";
  return renderCollapsedGroup({
    pages: list.fragments, expanded: list.expanded, action: "review-toggle-fragments", idBase: "reviewFragment",
    keys: { group: "fragmentsGroup", included: "fragmentsIncluded", hint: "fragmentsHint" },
  }, selectedSet, focused, busy, locale, markCheck);
}

// Several "other moments" (a system's display while it showed marks the system's strip
// leaves out) are one collapsed group; each keeps its own checkbox.
function renderAlternateGroup(list, selectedSet, focused, busy, locale, markCheck) {
  if (!list.alternatesGrouped) return "";
  return renderCollapsedGroup({
    pages: list.alternates, expanded: list.alternatesExpanded, action: "review-toggle-alternates", idBase: "reviewAlternate",
    keys: { group: "alternatesGroup", included: "fragmentsIncluded", hint: "alternatesHint" },
  }, selectedSet, focused, busy, locale, markCheck);
}

function renderCollapsedGroup({ pages, expanded, action, idBase, keys }, selectedSet, focused, busy, locale, markCheck) {
  const tt = (key, replacements = {}) => escapeHtml(t(`review.${key}`, { locale, replacements }));
  const included = pages.filter(page => selectedSet.has(page.id)).length;
  return `
    <section class="review-fragment-group ${expanded ? "is-open" : ""}" aria-labelledby="${idBase}Toggle">
      <button id="${idBase}Toggle" type="button" class="review-fragment-toggle" data-action="${action}" aria-expanded="${expanded}" aria-controls="${idBase}List">
        <span class="review-fragment-title">${tt(keys.group, { count: pages.length })}</span>
        ${included ? `<span class="review-fragment-count">${tt(keys.included, { count: included })}</span>` : ""}
      </button>
      <div id="${idBase}List" class="review-fragment-body" ${expanded ? "" : "hidden"}>
        <p class="review-fragment-hint">${tt(keys.hint)}</p>
        ${expanded ? `<div class="review-grid review-fragment-list" role="list" aria-label="${tt(keys.group, { count: pages.length })}" data-thumb-shape="${thumbShapeFor(pages.map(page => normalizeAssetPath(page.previewPath)))}">
          ${pages.map((page) => renderPageCard(page, selectedSet.has(page.id), page.id === focused?.id, busy, locale, markCheck)).join("")}
        </div>` : ""}
      </div>
    </section>`;
}

function clock(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

// The applied score region in video pixels, for cropping a full frame (null when unknown).
function lineRoiCrop(roi) {
  const points = Array.isArray(roi?.appliedRect) ? roi.appliedRect : [];
  const frameW = Number(roi?.imageWidth) || 0;
  if (points.length !== 4 || !(frameW > 0)) return null;
  const xs = points.map(point => Number(point?.[0])), ys = points.map(point => Number(point?.[1]));
  if (![...xs, ...ys].every(Number.isFinite)) return null;
  const x = Math.max(0, Math.min(...xs)), y = Math.max(0, Math.min(...ys));
  const w = Math.max(...xs) - x, h = Math.max(...ys) - y;
  return w > 1 && h > 1 ? { x, y, w, h, frameW } : null;
}

// A crop of the score region from a full video frame (percent geometry, no canvas).
function renderSourceFrame(frame, time, roiCrop, locale, captionText = "") {
  const tt = (key, replacements = {}) => escapeHtml(t(`review.lines.${key}`, { locale, replacements }));
  // the caption comes first: with two frames stacked, a caption below one reads as the next one's title
  const caption = `<figcaption>${captionText ? escapeHtml(captionText) : tt("sourceAt", { time: clock(time) })}</figcaption>`;
  if (!frame || frame.status === "loading") return `<figure class="review-line-source is-loading">${caption}<p role="status">${tt("sourceLoading")}</p></figure>`;
  if (frame.status !== "ready") return `<figure class="review-line-source is-error">${caption}<p role="alert">${tt("sourceFailed")}</p></figure>`;
  const alt = tt("sourceAlt", { time: clock(time) });
  if (!roiCrop) return `<figure class="review-line-source">${caption}<div class="review-line-source-frame"><img src="${escapeHtml(frame.url)}" alt="${alt}" /></div></figure>`;
  const { x, y, w, h, frameW } = roiCrop;
  return `<figure class="review-line-source">${caption}
      <div class="review-line-source-frame is-cropped" style="aspect-ratio:${w.toFixed(1)} / ${h.toFixed(1)}">
        <img style="width:${pct(frameW / w)};margin-left:${pct(-x / w)};margin-top:${pct(-y / w)}" src="${escapeHtml(frame.url)}" alt="${alt}" />
      </div></figure>`;
}

function pct(value) {
  return `${(value * 100).toFixed(3)}%`;
}

// A window of a printed page: the page image placed so that only [x, y, w, h] shows.
function renderPageWindow(path, pageW, [x, y, w, h], alt, overlay = "") {
  return `<div class="review-line-crop" style="aspect-ratio:${w.toFixed(1)} / ${h.toFixed(1)}">
      ${path ? `<img src="${escapeHtml(normalizeAssetPath(path))}" alt="${escapeHtml(alt)}" loading="lazy" style="width:${pct(pageW / w)};margin-left:${pct(-x / w)};margin-top:${pct(-y / w)}" />` : ""}
      ${overlay}
    </div>`;
}

// One place to check: the printed line(s) around an inferred seam above a clip of the video
// around the moment the view jumped (score region only, with sound), and one question.
function renderSeamCheck(check, index, lineCheck, pagePath, roiCrop, videoUrl, lines, locale) {
  const tt = (key, replacements = {}) => escapeHtml(t(`review.lines.${key}`, { locale, replacements }));
  const { seam, line, lineNumber, around, clip } = check;
  // a join the last rebuild kept with both views, after the user marked it wrong
  const repaired = seam.userRejected;
  const answer = repaired ? "" : lineCheck?.answers?.[seam.id] || "";
  const where = tt("checkWhere", { page: line.page, line: lineNumber, time: clock(check.jump) });
  const printed = around.map(other => {
    const number = lineNumberOnPage(lines, other);
    const marker = other === line ? `<span class="review-line-seam is-${seam.status}" style="left:${pct(seam.xFrac)}" role="img" aria-label="${tt(`seam.${seam.status}`)}"></span>` : "";
    return renderPageWindow(pagePath(other.page), other.pageSize[0], other.rect, t("review.lines.lineAlt", { locale, replacements: { page: other.page, line: number } }), marker);
  }).join("");
  const crop = roiCrop ? `style="aspect-ratio:${roiCrop.w.toFixed(1)} / ${roiCrop.h.toFixed(1)}"` : "";
  const videoStyle = roiCrop ? `style="width:${pct(roiCrop.frameW / roiCrop.w)};margin-left:${pct(-roiCrop.x / roiCrop.w)};margin-top:${pct(-roiCrop.y / roiCrop.w)}"` : "";
  const clipLabel = clip ? `${clock(clip[0])}–${clock(clip[1])}` : "";
  return `<article class="review-seam-check ${repaired ? "is-repaired" : answer ? `is-${answer}` : ""}" data-seam-id="${escapeHtml(seam.id)}" aria-labelledby="seamCheck${index}">
      <header class="review-line-head">
        <strong id="seamCheck${index}">${tt("checkTitle", { index: index + 1 })}</strong>
        <span class="review-line-meta">${where}</span>
        ${answer === "ok" ? `<span class="review-seam-done">${tt("answeredOk")}</span>`
          : repaired ? `<span class="review-seam-done is-unconfirmed">${tt("repairedTag")}</span>`
          : answer === "unsure" ? `<span class="review-seam-done is-unconfirmed">${tt("answeredUnsure")}</span>` : ""}
      </header>
      <p class="review-seam-label">${tt("pdfLabel")}</p>
      <div class="review-seam-printed">${printed}</div>
      ${clip && videoUrl ? `<p class="review-seam-label">${tt("videoLabel", { range: clipLabel })}</p>
      <div class="review-seam-video ${roiCrop ? "is-cropped" : ""}" ${crop}>
        <video data-seam-video="${escapeHtml(seam.id)}" data-start="${clip[0].toFixed(2)}" data-end="${clip[1].toFixed(2)}" src="${escapeHtml(`${videoUrl}#t=${clip[0].toFixed(2)}`)}" preload="metadata" playsinline ${videoStyle}></video>
      </div>
      <div class="review-seam-play-row">
        <button type="button" class="button button-primary" data-action="review-seam-play" data-value="${escapeHtml(seam.id)}" data-label-play="${tt("play", { range: clipLabel })}" data-label-pause="${tt("pause")}">${tt("play", { range: clipLabel })}</button>
      </div>` : `<p class="review-reflow-note" role="status">${tt("videoMissing")}</p>`}
      ${repaired ? `<p class="review-reflow-note" role="status">${tt("repairedNote")}</p>` : `<p class="review-seam-question">${tt("question")}</p>
      <div class="review-seam-answers" role="group" aria-label="${tt("checkTitle", { index: index + 1 })}">
        <button type="button" class="button ${answer === "ok" ? "button-primary" : "button-secondary"}" data-action="review-seam-answer" data-value="${escapeHtml(seam.id)}|ok" aria-pressed="${answer === "ok"}">${tt("answerOk")}</button>
        <button type="button" class="button button-secondary" data-action="review-seam-answer" data-value="${escapeHtml(seam.id)}|bad" aria-pressed="${answer === "bad"}">${tt("answerBad")}</button>
        <button type="button" class="button button-secondary" data-action="review-seam-answer" data-value="${escapeHtml(seam.id)}|unsure" aria-pressed="${answer === "unsure"}">${tt("answerUnsure")}</button>
      </div>
      ${answer === "unsure" ? `<p class="review-reflow-note" role="status">${tt("unsureNote")}</p>` : ""}
      ${answer === "bad" ? `<div class="review-reflow-note is-warning" role="status"><p>${tt("badNote")}</p>
        <button type="button" class="button button-secondary" data-action="open-bug-report">${tt("report")}</button></div>` : ""}`}
    </article>`;
}

// The line check: first the few places worth a look (inferred view-jump seams), then, folded,
// every printed line with the video moments it came from.
function renderLineCheck(lines, lineCheck, outputPages, roiCrop, videoUrl, locale) {
  const tt = (key, replacements = {}) => escapeHtml(t(`review.lines.${key}`, { locale, replacements }));
  const seams = lines.flatMap(line => line.seams);
  const checks = seamChecks(lines);
  // "hard to tell" leaves the place unchecked
  const answered = checks.filter(check => check.seam.userRejected || ["ok", "bad"].includes(lineCheck?.answers?.[check.seam.id])).length;
  const pagePath = page => outputPages.find(item => item.index === page)?.path || "";
  // nothing to check: the full list is the content
  const showAll = typeof lineCheck?.showAll === "boolean" ? lineCheck.showAll : !checks.length;
  const rows = showAll ? lines.map(line => {
    const number = lineNumberOnPage(lines, line);
    const times = line.sources.length
      ? `${clock(Math.min(...line.sources.map(s => s.tStart)))}–${clock(Math.max(...line.sources.map(s => s.tEnd)))}` : "";
    const open = Boolean(lineCheck?.sourceOpen?.[line.id]);
    const markers = line.seams.map(seam => `<span class="review-line-seam is-${seam.status}" style="left:${pct(seam.xFrac)}" role="img" aria-label="${tt(`seam.${seam.status}`)}" title="${tt(`seam.${seam.status}`)}"></span>`).join("");
    // no measure count: a layout unit can hold several measures, so the count under-reads
    const meta = [tt("position", { page: line.page, line: number }),
      times ? `<span class="review-line-time">${escapeHtml(times)}</span>` : ""].filter(Boolean).join(" · ");
    return `<article class="review-line ${line.attention ? "needs-check" : ""}" data-line-id="${escapeHtml(line.id)}">
        <header class="review-line-head">
          <span class="review-line-meta">${meta}</span>
          ${line.sources.length ? `<button type="button" class="button button-secondary review-line-toggle" data-action="review-line-source" data-value="${escapeHtml(line.id)}" aria-expanded="${open}">${tt(open ? "hideSource" : "showSource")}</button>` : ""}
        </header>
        ${renderPageWindow(pagePath(line.page), line.pageSize[0], line.rect, t("review.lines.lineAlt", { locale, replacements: { page: line.page, line: number } }), markers)}
        ${open ? `<div class="review-line-sources">${lineSourceTimes(line).map(time => renderSourceFrame(lineCheck?.frames?.[time.toFixed(1)], time, roiCrop, locale)).join("")}</div>` : ""}
      </article>`;
  }).join("") : "";
  const intro = checks.length ? tt("introChecks", { seams: seams.length, count: checks.length })
    : seams.length ? tt("introVerified", { seams: seams.length }) : tt("introNoSeams", { lines: lines.length });
  return `<div class="review-lines">
      <div class="review-lines-head">
        <h2>${tt(checks.length ? "titleChecks" : "title")}</h2>
        ${checks.length ? `<span class="review-seam-progress" role="status">${tt("progress", { done: answered, count: checks.length })}</span>` : ""}
        <p>${intro}</p>
      </div>
      ${checks.map((check, index) => renderSeamCheck(check, index, lineCheck, pagePath, roiCrop, videoUrl, lines, locale)).join("")}
      <div class="review-lines-all">
        <button type="button" class="button button-secondary" data-action="review-lines-all" aria-expanded="${showAll}">${tt(showAll ? "hideAll" : "showAll", { count: lines.length })}</button>
        ${showAll && seams.length ? `<p class="review-lines-legend">${["verified", "resolved", "unverified"].filter(status => seams.some(seam => seam.status === status))
          .map(status => `<span class="review-line-seam-key is-${status}" aria-hidden="true"></span>${tt(`seam.${status}`)}`).join(" ")}</p>` : ""}
      </div>
      ${rows}
    </div>`;
}

// Verifier codes and disposition reasons with a plain explanation; any other code shows the generic text.
const HYPOTHESIS_REASONS = [
  ["SOURCE_FOREGROUND_MISSING_OR_CHANGED", "missing"], ["EQUIVALENCE_CONTAINMENT_FAILED", "onlyInLeftOut"],
  ["DISPLAY_UNRESOLVED", "displayUnresolved"], ["DISPLAY_UNACCOUNTED", "displayUnresolved"],
  ["TERMINAL_EVIDENCE_MISSING", "noEvidence"], ["OBSERVATION_WITHOUT_TERMINAL", "noEvidence"],
  ["SECTION_LABEL_SOURCE_UNLEDGERED", "label"], ["CHAIN_UNAVAILABLE", "chain"], ["REMOVED_BY_", "removed"],
  ["fade_transition", "fade"], ["registration_out_of_range", "shaky"], ["source_clipped", "clipped"],
];

function hypothesisReason(code, locale) {
  const match = HYPOTHESIS_REASONS.find(([prefix]) => String(code).startsWith(prefix));
  return t(`review.hypothesis.reason.${match ? match[1] : "other"}`, { locale });
}

/**
 * Hypotheses of the last delivered file that did not pass its check: the source frame and the
 * delivered result of the same region at the same scale, the moment, the system and the reason.
 */
function renderHypotheses(hypotheses, pages, locale) {
  const tt = (key, replacements = {}) => escapeHtml(t(`review.hypothesis.${key}`, { locale, replacements }));
  const counts = hypotheses.counts;
  if (hypotheses.status === "loading" && !hypotheses.items.length) {
    return `<p class="review-hypotheses-state" role="status">${tt("loading")}</p>`;
  }
  if (hypotheses.status === "error") {
    return `<div class="review-hypotheses-state" role="alert"><p>${tt("loadFailed")}${hypotheses.error ? ` ${escapeHtml(hypotheses.error)}` : ""}</p>
      <button type="button" class="button button-secondary" data-action="review-hypotheses-retry">${tt("retry")}</button></div>`;
  }
  const bySystem = new Map(pages.map(page => [page.systemId || page.id, page]));
  const summary = counts ? tt("summary", {
    hypotheses: counts.hypotheses, bundles: counts.bundles, pages: counts.pages,
    safe: counts.boundariesSafe, unknown: counts.boundariesUnknown,
  }) : "";
  const card = (item) => {
    const page = item.systemId ? bySystem.get(item.systemId) : null;
    const time = item.timestampSec === null ? "" : formatSecondsLabel(item.timestampSec);
    const rawAlt = tt("rawAlt", { time: time || "-" });
    return `<li class="review-hypothesis is-${escapeHtml(item.status)}">
      <div class="review-hypothesis-pair">
        <figure class="review-hypothesis-frame">${item.rawCrop
          ? `<img src="${escapeHtml(item.rawCrop)}" alt="${rawAlt}" loading="lazy" />`
          : `<div class="review-hypothesis-missing">${tt("noImage")}</div>`}
          <figcaption>${tt("raw")}${time ? ` · ${escapeHtml(time)}` : ""}</figcaption></figure>
        <figure class="review-hypothesis-frame">${item.primaryCrop
          ? `<img src="${escapeHtml(item.primaryCrop)}" alt="${tt("primaryAlt")}" loading="lazy" />`
          : `<div class="review-hypothesis-missing">${tt("notDelivered")}</div>`}
          <figcaption>${tt("primary")}${item.pageIndex ? ` · ${tt("page", { index: item.pageIndex })}` : ""}</figcaption></figure>
      </div>
      <div class="review-hypothesis-meta">
        <span class="review-inline-pill ${item.status === "fail" ? "review-inline-pill-exclude" : "review-inline-pill-risk"}">${tt(`status.${item.status}`)}</span>
        <span class="review-hypothesis-reason" title="${escapeHtml(item.code)}">${escapeHtml(hypothesisReason(item.code, locale))}</span>
        ${page ? `<button type="button" class="review-link-button" data-action="review-hypothesis-system" data-value="${escapeHtml(page.id)}">${tt("showSystem", { title: page.title })}</button>` : ""}
      </div>
    </li>`;
  };
  const more = hypotheses.items.length < hypotheses.total;
  return `<div class="review-hypotheses" data-review-hypotheses>
      <p class="review-hypotheses-summary" role="status">${summary}</p>
      ${hypotheses.items.length
        ? `<ol class="review-hypotheses-list" aria-label="${tt("listLabel")}">${hypotheses.items.map(card).join("")}</ol>`
        : `<p class="review-hypotheses-state">${tt(hypotheses.ledgerStatus === "unassessed" ? "unassessed" : "empty")}</p>`}
      ${more ? `<button type="button" class="button button-secondary review-hypotheses-more" data-action="review-hypotheses-more" ${hypotheses.status === "loading" ? "disabled" : ""}>${tt("more", { shown: hypotheses.items.length, total: hypotheses.total })}</button>` : ""}
    </div>`;
}

const REBUILD_STAGES = new Set(["queued", "planning", "sizing", "rendering", "writing", "capturing", "comparing"]);

// Original screens mode (ORIGINAL_SCREENS_DESIGN.md §5): what the files are, and where the captured screens are.
function renderOriginalNote(original, locale, busy) {
  return `<div class="review-reflow-notes"><div class="review-reflow-note is-info" role="status" data-review-original>
      <p>${escapeHtml(t("review.original.notice", { locale }))}</p>
      <button type="button" class="button button-secondary" data-action="open-original-screens-dir" ${!original.screensDir || busy ? "disabled" : ""}>${escapeHtml(t("review.original.openScreens", { locale }))}</button>
    </div></div>`;
}

/**
 * Progress of a running background rebuild (PDF 다시 만들기) and its cancel button. The button stays
 * focusable (aria-disabled once a cancel was asked) so keyboard focus moves onto it from Rebuild.
 */
function renderRebuildProgress(review, locale) {
  const task = review.exportTask || {};
  const percent = Math.max(0, Math.min(100, Math.round(Number(task.progress || 0) * 100)));
  const cancelling = Boolean(task.cancelRequested);
  const stage = cancelling ? "cancelling" : REBUILD_STAGES.has(task.stage) ? task.stage : "queued";
  const stageLabel = t(`review.rebuildStage.${stage}`, { locale });
  const text = escapeHtml(t("review.rebuildProgress", { locale, replacements: { stage: stageLabel, percent } }));
  const cancelLabel = escapeHtml(t("review.cancelRebuild", { locale }));
  return `<span class="review-rebuild-progress" role="status" aria-live="polite">
            <span class="review-rebuild-meter" role="progressbar" aria-label="${escapeHtml(t("review.rebuildProgressAria", { locale }))}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}" aria-valuetext="${text}"><span style="width:${percent}%"></span></span>
            <span class="review-rebuild-text">${text}</span>
          </span>
          <button type="button" class="button button-secondary review-rebuild-cancel" data-action="cancel-review-export" aria-label="${escapeHtml(t("review.cancelRebuildLabel", { locale }))}" ${cancelling ? 'aria-disabled="true"' : ""}>${cancelLabel}</button>`;
}

export function renderReviewScreen(state) {
  const locale = state.ui.locale || "en";
  const pages = state.review.pages || [];
  const selectedSet = new Set(state.review.selectedPageIds);
  const summary = summarizeSelection(pages.map((page) => page.id), selectedSet);
  const reviewDone = state.review.status === "applied";
  const busy = ["running", "editing"].includes(state.review.status);
  // a background rebuild: the toolbar shows its stage and progress, with a cancel button
  const rebuilding = state.review.status === "running" && Boolean(state.review.exportTask);
  const list = reviewListPages(state.review);
  const visiblePages = list.navigable;
  const focused = visiblePages.find(page => page.id === state.review.focusedPageId) || visiblePages[0];
  const focusedIndex = visiblePages.findIndex(page => page.id === focused?.id);
  const focusedIncluded = Boolean(focused && selectedSet.has(focused.id));
  const zoom = state.review.zoom || "fit";
  const label = key => escapeHtml(t(`review.${key}`, { locale }));
  const control = (action, key, disabled = false, extra = "") => `<button type="button" class="button button-secondary" data-action="${action}" ${extra} ${disabled ? "disabled" : ""}>${label(key)}</button>`;
  // Icon-only tools carry their name (and shortcut, when one exists) in the accessible label and tooltip.
  const iconControl = (action, text, disabled = false, hint = "", extra = "") => `<button type="button" class="button button-secondary button-icon" data-action="${action}" aria-label="${text}" title="${hint ? `${text} (${hint})` : text}" ${extra} ${disabled ? "disabled" : ""}></button>`;
  const hasPages = pages.length > 0;
  const selectedCount = summary.keptCount;
  // "needs a look" on a row only while it singles out some of the rows that can be kept
  const keepable = pages.filter(page => !page.autoExcludeCandidate);
  const markCheck = keepable.some(page => !page.suspicious);
  const comparing = Boolean(state.review.compare && focused?.similarTo && !state.review.cropping && !state.review.hypotheses?.open);
  const compareReference = focused?.similarTo ? pages.find(page => page.id === focused.similarTo.referenceId) : null;
  const isSystems = pages.some(page => page.kind === "system");
  const original = state.review.originalScreens || {};
  const reviewTitle = escapeHtml(t(original.active ? "review.original.title" : isSystems ? "review.systemsTitle" : "review.title", { locale }));
  const outputPages = Array.isArray(state.review.outputPages) ? state.review.outputPages : [];
  const hypotheses = state.review.hypotheses || { open: false, items: [], status: "idle" };
  const hypothesesOpen = Boolean(hypotheses.open && !state.review.cropping);
  const pagePreview = Boolean(pagePreviewOn(state) && outputPages.length && !state.review.cropping && !hypothesesOpen);
  const reviewLines = state.review.reflow?.lines || [];
  const linesOpen = Boolean(reviewLines.length && outputPages.length && lineCheckOpen(state) && !state.review.cropping && !hypothesesOpen && !pagePreview);
  const roiCrop = lineRoiCrop(state.roi);
  const allIndex = focused ? pages.findIndex(page => page.id === focused.id) : -1;
  const focusedSimilar = Boolean(focused?.similarTo?.reason === "looks_similar");
  const reflowInfo = state.review.reflow || null;
  const measureReflow = state.exportConfig.measureReflow !== false;
  // A job made before clean charts keeps its files but cannot be rebuilt here.
  const legacyJob = hasPages && !isSystems && !reflowInfo && !original.active;
  // the current files are an incomplete chart: never shown as an ordinary saved result
  const incomplete = Boolean(reflowInfo?.incomplete) && state.exportConfig.runStatus === "done";
  const reviewLabel = escapeHtml(state.source.displayName || t("review.fallbackLabel", { locale }));
  const reviewCountLabel = escapeHtml(reviewDone
    ? t("review.keptCount", { locale, replacements: { count: selectedCount } })
    : t("review.selectedCount", { locale, replacements: { selected: selectedCount, total: pages.length } }));
  const summaryLabel = escapeHtml(`${reviewDone ? t("review.kept", { locale }) : t("review.selected", { locale })} ${selectedCount} / ${pages.length}`);
  const formats = Array.isArray(state.exportConfig.formats) ? state.exportConfig.formats : [];
  const pdfSelected = formats.includes("pdf");
  const applyLabel = label(state.review.status === "running" ? "applyBusy" : pdfSelected ? "savePdf" : "saveImages");
  const outputBusy = Boolean(state.ui.savingPdfAs) || busy || state.exportConfig.runStatus === "running";
  const saveHint = label(state.review.status === "running" ? "applyBusy" : reviewDone ? "editableSaved" : "saveHint");
  const errorLabel = state.review.error ? escapeHtml(state.review.error) : "";
  const hasFormats = formats.length > 0;
  const applyDisabled = summary.keptCount === 0
    || !state.exportConfig.jobId
    || busy
    || Boolean(state.ui.savingPdfAs)
    || !isReviewableRun(state)
    || !hasFormats
    || hasPendingRoiDraft(state)
    || legacyJob;

  return `
    <section class="screen screen-review" data-screen="review" aria-labelledby="reviewScreenTitle">
      <header class="screen-headline screen-headline-review">
        <div class="review-heading-copy">
          <h1 id="reviewScreenTitle" data-screen-heading tabindex="-1">${reviewTitle}</h1>
          <p title="${reviewLabel}">${reviewLabel}<span class="visually-hidden"> • ${reviewCountLabel}</span></p>
        </div>
        <div class="review-toolbar review-output-actions" role="group" aria-label="${label("savedFiles")}">
          ${rebuilding
            ? renderRebuildProgress(state.review, locale)
            : `<span class="review-save-state ${incomplete && !busy ? "is-incomplete" : reviewDone ? "is-saved" : "is-pending"}" role="status">${label(busy ? "applyBusyShort" : incomplete ? "incompleteState" : reviewDone ? "savedState" : "pendingState")}</span>
          <button type="button" class="button ${reviewDone ? "button-secondary" : "button-primary"}" data-action="apply-review" aria-label="${applyLabel}" title="${applyLabel}" ${applyDisabled ? "disabled" : ""}>${label(pdfSelected ? "rebuildShort" : "rebuildImagesShort")}</button>`}
          <button type="button" class="button ${reviewDone && state.review.pdfPath ? "button-primary" : "button-secondary"}" data-action="open-output-pdf" aria-describedby="reviewSaveHint" ${!state.review.pdfPath || outputBusy ? "disabled" : ""}>${label(reviewDone ? "openSavedPdf" : "openPreviousPdf")}</button>
          <span class="review-toolbar-divider" aria-hidden="true"></span>
          ${iconControl("save-output-pdf-as", label(state.ui.savingPdfAs ? "saveAsBusy" : reviewDone ? "saveAs" : "savePreviousAs"), !state.review.pdfPath || outputBusy, "", 'aria-describedby="reviewSaveHint"')}
          ${iconControl("open-output-dir", escapeHtml(t("rail.openFolder", { locale })), !state.review.outputDir || outputBusy)}
        </div>
      </header>
      <div class="review-workspace">
      <section class="review-grid-shell" data-stitch-region="review-grid">
        <div class="review-list-summary">
          <span class="review-summary-pill">${summaryLabel}</span>
        </div>
        ${legacyJob ? `<p class="review-reflow-note is-warning" role="status">${escapeHtml(t("review.legacyJob", { locale }))}</p>`
          : original.active ? renderOriginalNote(original, locale, outputBusy) : renderReflowNotes(reflowInfo, locale, busy, Boolean(state.ui.more?.reviewReasons))}
        ${list.main.length || list.fragments.length || list.alternates.length
          ? list.grouped || list.alternatesGrouped ? `<div class="review-list-scroll">
              ${list.main.length ? `<div class="review-grid" role="list" aria-label="${reviewTitle}" data-thumb-shape="${thumbShapeFor(list.main.map(page => normalizeAssetPath(page.previewPath)))}">
                ${list.main.map((page) => renderPageCard(page, selectedSet.has(page.id), page.id === focused?.id, busy, locale, markCheck)).join("")}
              </div>` : ""}
              ${renderAlternateGroup(list, selectedSet, focused, busy, locale, markCheck)}
              ${renderFragmentGroup(list, selectedSet, focused, busy, locale, markCheck)}
            </div>`
            : `<div class="review-grid" role="list" aria-label="${reviewTitle}" data-thumb-shape="${thumbShapeFor(list.main.map(page => normalizeAssetPath(page.previewPath)))}">
              ${list.main.map((page) => renderPageCard(page, selectedSet.has(page.id), page.id === focused?.id, busy, locale, markCheck)).join("")}
            </div>`
          : `<div class="review-empty" role="status">
              <strong>${escapeHtml(t(hasPages ? "review.filterEmptyTitle" : "review.emptyTitle", { locale }))}</strong>
              <p>${escapeHtml(t(hasPages ? "review.filterEmptyBody" : "review.emptyBody", { locale }))}</p>
            </div>`}
        <div class="review-panel-foot">
          ${isSystems ? `<label class="review-layout-option">
            <input type="checkbox" data-action="toggle-measure-reflow" ${measureReflow ? "checked" : ""} ${outputBusy ? "disabled" : ""} aria-describedby="reviewMeasureReflowHint" />
            <span>${escapeHtml(t("export.layout.measure", { locale }))}<small id="reviewMeasureReflowHint">${label("measureHint")}</small></span>
          </label>` : ""}
          ${original.available && !original.active ? `<button type="button" class="button button-secondary review-original-rebuild" data-action="rebuild-original-screens" ${outputBusy || !hasFormats || !isReviewableRun(state) ? "disabled" : ""}>${escapeHtml(t("review.original.rebuild", { locale }))}</button>` : ""}
          <p id="reviewSaveHint" class="visually-hidden">${saveHint}</p>
        </div>
      </section>
      <section class="review-viewer" aria-label="${reviewTitle}">
        <div class="review-inspector ${focused ? (focusedIncluded ? "is-included" : "is-excluded") : ""}">
          <div class="review-tool-group review-nav" role="group" aria-label="${label("navigation")}">
            ${iconControl("review-previous", label("previous"), !focused || focusedIndex <= 0 || busy, "←")}
            <span class="review-nav-label">${focused ? `<strong title="${escapeHtml(focused.title)}">${escapeHtml(focused.title)}</strong>` : ""}<span class="review-position">${focused ? focusedIndex + 1 : 0} / ${visiblePages.length}</span></span>
            ${iconControl("review-next", label("next"), !focused || focusedIndex >= visiblePages.length - 1 || busy, "→")}
          </div>
          ${focused ? `<label class="review-inspector-include" title="${label("included")} (Space)">
            <input type="checkbox" data-action="review-toggle-focused" ${focusedIncluded ? "checked" : ""} ${busy ? "disabled" : ""} />
            ${label("included")}
          </label>
          ${renderPagePills(focused, locale, markCheck)}
          ${focused.similarTo ? `<button type="button" class="button ${focusedSimilar && !comparing ? "button-primary" : "button-secondary"}" data-action="review-compare" aria-pressed="${comparing}" ${state.review.cropping || hypothesesOpen ? "disabled" : ""}>${label(comparing ? "closeCompare" : "compare")}</button>` : ""}
          ${focusedSimilar ? `<button type="button" class="button button-secondary review-remove-duplicate" data-action="review-remove-duplicate" ${busy || !focusedIncluded ? "disabled" : ""}>${label("leaveOut")}</button>` : ""}
          ${focused.kind === "system" && !pagePreview && !linesOpen ? `<div class="review-tool-group review-order" role="group" aria-label="${label("order")}">
            ${iconControl("review-move-up", label("moveUp"), busy || allIndex <= 0, "", 'data-icon="up"')}${iconControl("review-move-down", label("moveDown"), busy || allIndex < 0 || allIndex >= pages.length - 1, "", 'data-icon="down"')}
          </div>` : ""}
          ${focused.warningReason && (focused.suspicious || focused.autoExcludeCandidate) ? `<p class="review-risk-note">${escapeHtml(pickLocalizedText(focused.warningReason, locale))}</p>` : ""}
          ${focused.similarTo ? `<p class="review-similar-note">${escapeHtml(similarNoteText(focused, locale, compareReference?.title || ""))}${compareReference ? ` <button type="button" class="review-link-button" data-action="focus-review-page" data-page-id="${escapeHtml(compareReference.id)}">${escapeHtml(t("review.goToReference", { locale, replacements: { title: compareReference.title } }))}</button>` : ""}</p>` : ""}` : ""}
        </div>
        ${state.review.cropping && focused ? `
          <div class="review-crop-stage">
            <img id="reviewCropImage" src="${escapeHtml(normalizeAssetPath(focused.capturePath))}" alt="${escapeHtml(focused.title)}" />
            <canvas id="reviewCropCanvas" tabindex="0" aria-label="${label("crop")}"></canvas>
            <input id="reviewCropInput" type="hidden" />
          </div>
          <div class="review-crop-actions">${control("review-apply-crop", "saveCrop", busy)}${control("review-close-crop", "closeCrop", busy)}</div>
        ` : hypothesesOpen ? `<div class="review-viewer-surface is-hypotheses" tabindex="0" data-focus-key="review-canvas">
          ${renderHypotheses(hypotheses, pages, locale)}
        </div>` : pagePreview ? `<div class="review-viewer-surface is-pages" tabindex="0" data-focus-key="review-canvas">
          <p class="review-pages-note">${label("pagePreviewNote")}</p>
          <div class="review-pages-stack">
            ${outputPages.map(page => `<img class="review-page-image" src="${escapeHtml(normalizeAssetPath(page.path))}" alt="${escapeHtml(t("review.pageAlt", { locale, replacements: { index: page.index } }))}" loading="lazy" />`).join("")}
          </div>
        </div>` : linesOpen ? `<div class="review-viewer-surface is-lines" tabindex="0" data-focus-key="review-canvas">
          ${renderLineCheck(reviewLines, state.review.lineCheck, outputPages, roiCrop, fileUrl(state.review.reflow?.sourceVideoPath || state.source.filePath), locale)}
        </div>` : comparing ? `<div class="review-viewer-surface is-comparing" tabindex="0" data-focus-key="review-canvas">
          ${renderCompareStage(focused, compareReference, locale)}
        </div>` : `<div class="review-viewer-surface" tabindex="0" data-focus-key="review-canvas" aria-describedby="reviewShortcutHelp">
          ${focused ? `<img class="review-full-image ${zoom === "fit" ? "is-fit" : "is-zoomed"}" ${zoom === "fit" ? "" : `style="zoom:${Number(zoom)}"`} src="${escapeHtml(normalizeAssetPath(focused.previewPath))}" alt="${escapeHtml(focused.title)}" />` : ""}
        </div>`}
        <div class="review-viewer-toolbar">
          ${pagePreview || linesOpen || hypothesesOpen || comparing || state.review.cropping ? "" : `<div class="review-tool-group" role="group" aria-label="${label("zoom")}">
            ${iconControl("review-zoom-out", label("zoomOut"), !focused)}${iconControl("review-zoom-in", label("zoomIn"), !focused)}
            ${control("review-fit", "fit", !focused, `aria-pressed="${zoom === "fit"}"`)}${control("review-actual", "actualSize", !focused, `aria-pressed="${Number(zoom) === 1}"`)}
          </div>`}
          <div class="review-tool-group" role="group" aria-label="${label("editing")}">
            ${iconControl("review-undo", label("undo"), busy || !state.review.canUndo, "Ctrl/⌘ Z")}${iconControl("review-redo", label("redo"), busy || !state.review.canRedo, "Ctrl/⌘ ⇧ Z")}
          </div>
          ${reflowInfo?.ledger && (reflowInfo.ledger.reviewHypotheses > 0 || hypothesesOpen) ? `<div class="review-tool-group" role="group" aria-label="${label("hypothesis.toolbar")}">
            <button type="button" class="button button-secondary" data-action="review-hypotheses" aria-pressed="${hypothesesOpen}" ${busy ? "disabled" : ""}>${escapeHtml(t(hypothesesOpen ? "review.hypothesis.close" : "review.hypothesis.open", { locale, replacements: { count: reflowInfo.ledger.reviewHypotheses } }))}</button>
          </div>` : ""}
          ${outputPages.length ? `<div class="review-tool-group" role="group" aria-label="${label("pagePreview")}">
            ${reviewLines.length ? `<button type="button" class="button button-secondary" data-action="review-lines" aria-pressed="${linesOpen}" ${busy ? "disabled" : ""}>${escapeHtml(seamChecks(reviewLines).length ? t("review.lines.toolbarChecks", { locale, replacements: { count: seamChecks(reviewLines).length } })
              : t("review.lines.toolbar", { locale, replacements: { count: reviewLines.length } }))}</button>` : ""}
            ${control("review-page-preview", pagePreview ? "systemView" : "pagePreview", busy, `aria-pressed="${pagePreview}"`)}
          </div>` : ""}
          ${original.active || isSystems ? "" : `<div class="review-tool-group" role="group" aria-label="${label("crop")}">
            ${control("review-crop", "crop", !focused || busy || focused.selectionMode === "pages" || focused.kind === "system")}
            ${focused?.cropRect ? control("review-reset-crop", "resetCrop", busy) : ""}
          </div>`}
        </div>
        <p id="reviewShortcutHelp" class="review-keyboard-help">${label("shortcutHelp")}</p>
      </section>
      </div>
      ${state.review.error ? `<p class="inline-error" role="alert">${errorLabel}</p>` : ""}
    </section>
  `;
}
