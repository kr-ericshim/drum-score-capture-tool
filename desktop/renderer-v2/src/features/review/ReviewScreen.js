import { needsAttention, summarizeSelection } from "../../app/session/selectors.js";
import { t } from "../../lib/i18n.js";
import { normalizeAssetPath } from "../../lib/paths.js";
import { thumbShapeFor } from "./thumbShape.js";

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function hasPendingRoiDraft(state) {
  if (Boolean(state?.roi?.autoFit) !== Boolean(state?.roi?.appliedAutoFit)) return true;
  const draft = state?.roi?.draftRect;
  const applied = state?.roi?.appliedRect;
  if (!Array.isArray(draft) || draft.length !== 4) {
    return false;
  }
  if (!Array.isArray(applied) || applied.length !== 4) {
    return true;
  }
  return JSON.stringify(draft) !== JSON.stringify(applied);
}

function renderPagePills(page, locale) {
  const pill = (kind, key) => `<span class="review-inline-pill review-inline-pill-${kind}">${escapeHtml(t(`review.${key}`, { locale }))}</span>`;
  return [
    page.autoExcludeCandidate ? pill("exclude", "excludeCandidate") : "",
    page.suspicious && !page.autoExcludeCandidate ? pill("risk", "check") : "",
    page.similarTo ? pill("similar", "similar") : "",
  ].join("");
}

// One row per capture: the checkbox owns inclusion, the row background owns "currently viewed".
function renderPageCard(page, selected, focused, locked, locale) {
  const pageId = escapeHtml(page.id);
  const pageTitle = escapeHtml(page.title);
  const previewPath = escapeHtml(normalizeAssetPath(page.previewPath));
  const includeAriaLabel = escapeHtml(t("review.includeAria", { locale, replacements: { title: page.title } }));
  const pills = renderPagePills(page, locale);
  return `
    <article class="review-card ${selected ? "is-selected" : "is-excluded"} ${focused ? "is-focused" : ""}" role="listitem">
      <button class="review-card-figure" type="button" data-action="focus-review-page" data-page-id="${pageId}" ${focused ? 'aria-current="page"' : ""}>
        <img src="${previewPath}" alt="${pageTitle}" loading="lazy" />
      </button>
      <div class="review-card-meta">
        <label class="review-card-include">
          <input aria-label="${includeAriaLabel}" data-action="toggle-review-page" data-page-id="${pageId}" type="checkbox" ${selected ? "checked" : ""} ${locked ? "disabled" : ""} />
          <span title="${pageTitle}">${pageTitle}</span>
        </label>
        ${pills ? `<div class="review-card-badges">${pills}</div>` : ""}
        ${locked ? `<small class="review-card-locked">${escapeHtml(t("review.locked", { locale }))}</small>` : ""}
      </div>
    </article>
  `;
}

function similarNoteText(page, locale) {
  const similar = page?.similarTo;
  if (!similar) return "";
  const reference = similar.referenceIndex
    ? t("selector.pageTitle", { locale, replacements: { index: similar.referenceIndex } })
    : t("review.previousPage", { locale });
  if (similar.reason === "playhead_reset") {
    return t("review.similarNotePlayhead", { locale, replacements: { reference } });
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

export function renderReviewScreen(state) {
  const locale = state.ui.locale || "en";
  const pages = state.review.pages || [];
  const selectedSet = new Set(state.review.selectedPageIds);
  const summary = summarizeSelection(pages.map((page) => page.id), selectedSet);
  const reviewDone = state.review.status === "applied";
  const busy = ["running", "editing"].includes(state.review.status);
  const visiblePages = state.review.filter === "suspicious" ? pages.filter(needsAttention) : pages;
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
  const attentionCount = pages.filter(needsAttention).length;
  const comparing = Boolean(state.review.compare && focused?.similarTo && !state.review.cropping);
  const compareReference = focused?.similarTo ? pages.find(page => page.id === focused.similarTo.referenceId) : null;
  const reviewTitle = escapeHtml(t("review.title", { locale }));
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
    || state.exportConfig.runStatus !== "done"
    || !hasFormats
    || hasPendingRoiDraft(state);

  return `
    <section class="screen screen-review" data-screen="review" aria-labelledby="reviewScreenTitle">
      <header class="screen-headline screen-headline-review">
        <div class="review-heading-copy">
          <h1 id="reviewScreenTitle" data-screen-heading tabindex="-1">${reviewTitle}</h1>
          <p title="${reviewLabel}">${reviewLabel}<span class="visually-hidden"> • ${reviewCountLabel}</span></p>
        </div>
        <div class="review-toolbar review-output-actions" role="group" aria-label="${label("savedFiles")}">
          <span class="review-save-state ${reviewDone ? "is-saved" : "is-pending"}" role="status">${label(busy ? "applyBusyShort" : reviewDone ? "savedState" : "pendingState")}</span>
          <button type="button" class="button ${reviewDone ? "button-secondary" : "button-primary"}" data-action="apply-review" aria-label="${applyLabel}" title="${applyLabel}" ${applyDisabled ? "disabled" : ""}>${label(pdfSelected ? "rebuildShort" : "rebuildImagesShort")}</button>
          <button type="button" class="button ${reviewDone && state.review.pdfPath ? "button-primary" : "button-secondary"}" data-action="open-output-pdf" aria-describedby="reviewSaveHint" ${!state.review.pdfPath || outputBusy ? "disabled" : ""}>${label(reviewDone ? "openSavedPdf" : "openPreviousPdf")}</button>
          <span class="review-toolbar-divider" aria-hidden="true"></span>
          ${iconControl("save-output-pdf-as", label(state.ui.savingPdfAs ? "saveAsBusy" : reviewDone ? "saveAs" : "savePreviousAs"), !state.review.pdfPath || outputBusy, "", 'aria-describedby="reviewSaveHint"')}
          ${iconControl("open-output-dir", escapeHtml(t("rail.openFolder", { locale })), !state.review.outputDir || outputBusy)}
        </div>
      </header>
      <div class="review-workspace">
      <section class="review-grid-shell" data-stitch-region="review-grid">
        <div class="review-list-tools">
          <div class="review-filter" role="group" aria-label="${label("all")}">
            <button class="button button-secondary" data-action="review-filter" data-value="all" aria-pressed="${state.review.filter !== "suspicious"}">${label("all")} <span>${pages.length}</span></button>
            <button class="button button-secondary" data-action="review-filter" data-value="suspicious" aria-pressed="${state.review.filter === "suspicious"}">${label("suspiciousOnly")} <span>${attentionCount}</span></button>
          </div>
          ${control("review-select-all", "selectAll", busy)}${control("review-select-none", "selectNone", busy)}
        </div>
        <div class="review-list-summary">
          <span class="review-summary-pill">${summaryLabel}</span><span class="review-format-label">${escapeHtml(formats.join(" · ").toUpperCase())}</span>
        </div>
        ${visiblePages.length
          ? `<div class="review-grid" role="list" aria-label="${reviewTitle}" data-thumb-shape="${thumbShapeFor(visiblePages.map(page => normalizeAssetPath(page.previewPath)))}">
              ${visiblePages.map((page) => renderPageCard(page, selectedSet.has(page.id), page.id === focused?.id, busy, locale)).join("")}
            </div>`
          : `<div class="review-empty" role="status">
              <strong>${escapeHtml(t(hasPages ? "review.filterEmptyTitle" : "review.emptyTitle", { locale }))}</strong>
              <p>${escapeHtml(t(hasPages ? "review.filterEmptyBody" : "review.emptyBody", { locale }))}</p>
            </div>`}
        <div class="review-panel-foot">
          <p id="reviewSaveHint" class="review-save-hint">${saveHint}</p>
          ${state.review.outputDir ? `<div class="review-output-path"><span title="${escapeHtml(state.review.outputDir)}">${escapeHtml(state.review.outputDir)}</span><button type="button" class="button button-secondary" data-action="copy-output-dir">${escapeHtml(t("rail.copyPath", { locale }))}</button></div>` : ""}
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
          ${renderPagePills(focused, locale)}
          ${focused.similarTo ? `<button type="button" class="button button-secondary" data-action="review-compare" aria-pressed="${comparing}" ${state.review.cropping ? "disabled" : ""}>${label(comparing ? "closeCompare" : "compare")}</button>` : ""}
          ${focused.warningReason && (focused.suspicious || focused.autoExcludeCandidate) ? `<p class="review-risk-note">${escapeHtml(focused.warningReason)}</p>` : ""}
          ${focused.similarTo ? `<p class="review-similar-note">${escapeHtml(similarNoteText(focused, locale))}${compareReference ? ` <button type="button" class="review-link-button" data-action="focus-review-page" data-page-id="${escapeHtml(compareReference.id)}">${escapeHtml(t("review.goToReference", { locale, replacements: { title: compareReference.title } }))}</button>` : ""}</p>` : ""}` : ""}
        </div>
        ${state.review.cropping && focused ? `
          <div class="review-crop-stage">
            <img id="reviewCropImage" src="${escapeHtml(normalizeAssetPath(focused.capturePath))}" alt="${escapeHtml(focused.title)}" />
            <canvas id="reviewCropCanvas" tabindex="0" aria-label="${label("crop")}"></canvas>
            <input id="reviewCropInput" type="hidden" />
          </div>
          <div class="review-crop-actions">${control("review-apply-crop", "saveCrop", busy)}${control("review-close-crop", "closeCrop", busy)}</div>
        ` : comparing ? `<div class="review-viewer-surface is-comparing" tabindex="0" data-focus-key="review-canvas">
          ${renderCompareStage(focused, compareReference, locale)}
        </div>` : `<div class="review-viewer-surface" tabindex="0" data-focus-key="review-canvas" aria-describedby="reviewShortcutHelp">
          ${focused ? `<img class="review-full-image ${zoom === "fit" ? "is-fit" : "is-zoomed"}" ${zoom === "fit" ? "" : `style="zoom:${Number(zoom)}"`} src="${escapeHtml(normalizeAssetPath(focused.previewPath))}" alt="${escapeHtml(focused.title)}" />` : ""}
        </div>`}
        <div class="review-viewer-toolbar">
          <div class="review-tool-group" role="group" aria-label="${label("zoom")}">
            ${iconControl("review-zoom-out", label("zoomOut"), !focused)}${iconControl("review-zoom-in", label("zoomIn"), !focused)}
            ${control("review-fit", "fit", !focused, `aria-pressed="${zoom === "fit"}"`)}${control("review-actual", "actualSize", !focused, `aria-pressed="${Number(zoom) === 1}"`)}
          </div>
          <div class="review-tool-group" role="group" aria-label="${label("editing")}">
            ${iconControl("review-undo", label("undo"), busy || !state.review.canUndo, "Ctrl/⌘ Z")}${iconControl("review-redo", label("redo"), busy || !state.review.canRedo, "Ctrl/⌘ ⇧ Z")}
          </div>
          <div class="review-tool-group" role="group" aria-label="${label("crop")}">
            ${control("review-crop", "crop", !focused || busy || focused.selectionMode === "pages")}
            ${control("review-reset-crop", "resetCrop", !focused?.cropRect || busy)}
          </div>
        </div>
        <p id="reviewShortcutHelp" class="review-keyboard-help">${label("shortcutHelp")}</p>
      </section>
      </div>
      ${state.review.error ? `<p class="inline-error" role="alert">${errorLabel}</p>` : ""}
    </section>
  `;
}
