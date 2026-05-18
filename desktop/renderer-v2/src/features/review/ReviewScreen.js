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
  const warningReason = escapeHtml(page.warningReason || "");
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
          ${page.suspicious ? `<span class="review-inline-pill review-inline-pill-risk">${checkLabel}</span>` : ""}
        </div>
        ${page.suspicious && warningReason ? `<p class="panel-note review-risk-note">${warningReason}</p>` : ""}
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
  const hasPages = pages.length > 0;
  const selectedCount = summary.keptCount;
  const reviewTitle = escapeHtml(t("review.title", { locale }));
  const reviewLabel = escapeHtml(state.source.displayName || t("review.fallbackLabel", { locale }));
  const reviewCountLabel = escapeHtml(reviewDone
    ? t("review.keptCount", { locale, replacements: { count: selectedCount } })
    : t("review.selectedCount", { locale, replacements: { selected: selectedCount, total: pages.length } }));
  const summaryLabel = escapeHtml(`${reviewDone ? t("review.kept", { locale }) : t("review.selected", { locale })} ${selectedCount} / ${pages.length}`);
  const appliedNote = escapeHtml(t("review.appliedNote", { locale }));
  const applyLabel = escapeHtml(state.review.status === "running" ? t("review.applyBusy", { locale }) : t("review.apply", { locale }));
  const errorLabel = state.review.error ? escapeHtml(state.review.error) : "";
  const hasFormats = Array.isArray(state.exportConfig.formats) && state.exportConfig.formats.length > 0;
  const applyDisabled = summary.keptCount === 0
    || !state.exportConfig.jobId
    || state.review.status === "running"
    || state.exportConfig.runStatus !== "done"
    || !hasFormats
    || hasPendingRoiDraft(state);

  return `
    <section class="screen screen-review" data-screen="review" aria-labelledby="reviewScreenTitle">
      <header class="screen-headline screen-headline-review">
        <div>
          <h1 id="reviewScreenTitle" data-screen-heading tabindex="-1">${reviewTitle}</h1>
          <p>${reviewLabel} • ${reviewCountLabel}</p>
        </div>
        <div class="review-toolbar">
          <div class="review-summary-pills">
            <span class="review-summary-pill">${summaryLabel}</span>
          </div>
          ${reviewDone
            ? `<p class="panel-note review-status-note">${appliedNote}</p>`
            : `<button class="button button-primary" data-action="apply-review" ${applyDisabled ? "disabled" : ""}>${applyLabel}</button>`}
        </div>
      </header>
      <section class="review-grid-shell" data-stitch-region="review-grid">
        ${hasPages
          ? `<div class="review-grid" role="list" aria-label="${reviewTitle}">
              ${pages.map((page) => renderPageCard(page, selectedSet.has(page.id), page.id === state.review.focusedPageId, reviewDone, locale)).join("")}
            </div>`
          : `<div class="review-empty" role="status">
              <strong>${escapeHtml(t("review.emptyTitle", { locale }))}</strong>
              <p>${escapeHtml(t("review.emptyBody", { locale }))}</p>
            </div>`}
      </section>
      ${state.review.error ? `<p class="inline-error" role="alert">${errorLabel}</p>` : ""}
    </section>
  `;
}
