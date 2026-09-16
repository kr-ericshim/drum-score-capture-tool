import { summarizeSelection } from "../../app/session/selectors.js";
import { t } from "../../lib/i18n.js";
import { normalizeAssetPath } from "../../lib/paths.js";

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

function renderPageCard(page, selected, focused, locked, locale) {
  const pageId = escapeHtml(page.id);
  const pageTitle = escapeHtml(page.title);
  const previewPath = escapeHtml(normalizeAssetPath(page.previewPath));
  const statusLabel = locked ? escapeHtml(t("review.locked", { locale })) : "";
  const includeAriaLabel = escapeHtml(t("review.includeAria", { locale, replacements: { title: page.title } }));
  const includeLabel = escapeHtml(t("review.include", { locale }));
  const checkLabel = escapeHtml(t("review.check", { locale }));
  const excludeCandidateLabel = escapeHtml(t("review.excludeCandidate", { locale }));
  return `
    <article class="review-card ${selected ? "is-selected" : ""} ${focused ? "is-focused" : ""}" role="listitem">
      <button class="review-card-figure" type="button" data-action="focus-review-page" data-page-id="${pageId}" ${focused ? 'aria-current="page"' : ""}>
        <img src="${previewPath}" alt="${pageTitle}" loading="lazy" />
      </button>
      <div class="review-card-meta review-card-meta-detail">
        <div class="review-card-copy">
          <span>${pageTitle}</span>
          ${statusLabel ? `<small>${statusLabel}</small>` : ""}
        </div>
        <div class="review-card-badges">
          ${page.autoExcludeCandidate ? `<span class="review-inline-pill review-inline-pill-risk">${excludeCandidateLabel}</span>` : ""}
          ${page.suspicious ? `<span class="review-inline-pill review-inline-pill-risk">${checkLabel}</span>` : ""}
        </div>
        <label class="choice-row">
          <input aria-label="${includeAriaLabel}" data-action="toggle-review-page" data-page-id="${pageId}" type="checkbox" ${selected ? "checked" : ""} ${locked ? "disabled" : ""} />
          ${includeLabel}
        </label>
      </div>
    </article>
  `;
}

export function renderReviewScreen(state) {
  const locale = state.ui.locale || "en";
  const pages = state.review.pages || [];
  const selectedSet = new Set(state.review.selectedPageIds);
  const summary = summarizeSelection(pages.map((page) => page.id), selectedSet);
  const reviewDone = state.review.status === "applied";
  const busy = ["running", "editing"].includes(state.review.status);
  const visiblePages = state.review.filter === "suspicious" ? pages.filter(page => page.suspicious || page.autoExcludeCandidate) : pages;
  const focused = visiblePages.find(page => page.id === state.review.focusedPageId) || visiblePages[0];
  const focusedIndex = visiblePages.findIndex(page => page.id === focused?.id);
  const zoom = state.review.zoom || "fit";
  const label = key => escapeHtml(t(`review.${key}`, { locale }));
  const control = (action, key, disabled = false) => `<button type="button" class="button button-secondary" data-action="${action}" ${disabled ? "disabled" : ""}>${label(key)}</button>`;
  const hasPages = pages.length > 0;
  const selectedCount = summary.keptCount;
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
        <div class="review-output-actions" role="group" aria-label="${label("savedFiles")}">
          <button type="button" class="button ${reviewDone && state.review.pdfPath ? "button-primary" : "button-secondary"}" data-action="open-output-pdf" aria-describedby="reviewSaveHint" ${!state.review.pdfPath || outputBusy ? "disabled" : ""}>${label("openSavedPdf")}</button>
          <button type="button" class="button button-secondary" data-action="save-output-pdf-as" aria-describedby="reviewSaveHint" ${!state.review.pdfPath || outputBusy ? "disabled" : ""}>${label(state.ui.savingPdfAs ? "saveAsBusy" : "saveAs")}</button>
          <button type="button" class="button ${reviewDone && !state.review.pdfPath && state.review.outputDir ? "button-primary" : "button-secondary"}" data-action="open-output-dir" ${!state.review.outputDir || outputBusy ? "disabled" : ""}>${escapeHtml(t("rail.openFolder", { locale }))}</button>
        </div>
        <div class="review-toolbar">
          <div class="review-save-context">
            <div class="review-summary-pills">
              <span class="review-summary-pill">${summaryLabel}</span>
              <span class="review-format-label">${escapeHtml(formats.join(" · ").toUpperCase())}</span>
            </div>
            <p id="reviewSaveHint" class="review-save-hint" role="status">${saveHint}</p>
          </div>
          <button type="button" class="button ${reviewDone ? "button-secondary" : "button-primary"}" data-action="apply-review" ${applyDisabled ? "disabled" : ""}>${applyLabel}</button>
        </div>
      </header>
      <div class="review-workspace">
      <section class="review-grid-shell" data-stitch-region="review-grid">
        <div class="review-list-tools">
          <div class="review-filter" role="group" aria-label="${label("all")}">
            <button class="button button-secondary" data-action="review-filter" data-value="all" aria-pressed="${state.review.filter !== "suspicious"}">${label("all")}</button>
            <button class="button button-secondary" data-action="review-filter" data-value="suspicious" aria-pressed="${state.review.filter === "suspicious"}">${label("suspiciousOnly")}</button>
          </div>
          ${control("review-select-all", "selectAll", busy)}${control("review-select-none", "selectNone", busy)}
        </div>
        ${visiblePages.length
          ? `<div class="review-grid" role="list" aria-label="${reviewTitle}">
              ${visiblePages.map((page) => renderPageCard(page, selectedSet.has(page.id), page.id === focused?.id, busy, locale)).join("")}
            </div>`
          : `<div class="review-empty" role="status">
              <strong>${escapeHtml(t(hasPages ? "review.filterEmptyTitle" : "review.emptyTitle", { locale }))}</strong>
              <p>${escapeHtml(t(hasPages ? "review.filterEmptyBody" : "review.emptyBody", { locale }))}</p>
            </div>`}
      </section>
      <section class="review-viewer" aria-label="${reviewTitle}">
        <div class="review-viewer-toolbar">
          <div class="review-tool-group" role="group" aria-label="${label("navigation")}">
            ${control("review-previous", "previous", focusedIndex <= 0 || busy)}
            <span class="review-position">${focused ? focusedIndex + 1 : 0} / ${visiblePages.length}</span>
            ${control("review-next", "next", !focused || focusedIndex >= visiblePages.length - 1 || busy)}
          </div>
          <div class="review-tool-group" role="group" aria-label="${label("zoom")}">
          ${control("review-zoom-out", "zoomOut", !focused)}${control("review-zoom-in", "zoomIn", !focused)}
          ${control("review-fit", "fit", !focused)}${control("review-actual", "actualSize", !focused)}
          </div>
          <div class="review-tool-group" role="group" aria-label="${label("editing")}">
          ${control("review-undo", "undo", busy || !state.review.canUndo)}${control("review-redo", "redo", busy || !state.review.canRedo)}
          ${control("review-crop", "crop", !focused || busy || focused.selectionMode === "pages")}
          ${control("review-reset-crop", "resetCrop", !focused?.cropRect || busy)}
          </div>
        </div>
        ${focused ? `<div class="review-inspector">
          <div class="review-inspector-heading">
            <strong>${escapeHtml(focused.title)}</strong>
            <span class="review-inclusion-status">${selectedSet.has(focused.id) ? label("included") : label("excluded")}</span>
            ${focused.autoExcludeCandidate ? `<span class="review-inline-pill review-inline-pill-risk">${label("excludeCandidate")}</span>` : ""}
            ${focused.suspicious ? `<span class="review-inline-pill review-inline-pill-risk">${label("check")}</span>` : ""}
          </div>
          ${focused.warningReason && (focused.suspicious || focused.autoExcludeCandidate) ? `<p class="review-risk-note">${escapeHtml(focused.warningReason)}</p>` : ""}
        </div>` : ""}
        ${state.review.cropping && focused ? `
          <div class="review-crop-stage">
            <img id="reviewCropImage" src="${escapeHtml(normalizeAssetPath(focused.capturePath))}" alt="${escapeHtml(focused.title)}" />
            <canvas id="reviewCropCanvas" tabindex="0" aria-label="${label("crop")}"></canvas>
            <input id="reviewCropInput" type="hidden" />
          </div>
          <div class="review-crop-actions">${control("review-apply-crop", "saveCrop", busy)}${control("review-close-crop", "closeCrop", busy)}</div>
        ` : `<div class="review-viewer-surface" tabindex="0">
          ${focused ? `<img class="review-full-image ${zoom === "fit" ? "is-fit" : "is-zoomed"}" ${zoom === "fit" ? "" : `style="zoom:${Number(zoom)}"`} src="${escapeHtml(normalizeAssetPath(focused.previewPath))}" alt="${escapeHtml(focused.title)}" />` : ""}
        </div>`}
        <p class="review-keyboard-help">${label("shortcutHelp")}</p>
      </section>
      </div>
      ${state.review.error ? `<p class="inline-error" role="alert">${errorLabel}</p>` : ""}
    </section>
  `;
}
