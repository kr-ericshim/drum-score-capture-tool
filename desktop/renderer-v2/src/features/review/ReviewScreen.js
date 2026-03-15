import { summarizeSelection } from "../../app/session/selectors.js";
import { t } from "../../lib/i18n.js";
import { normalizeAssetPath } from "../../lib/paths.js";

function renderPageCard(page, selected, focused, locked, locale) {
  return `
    <article class="review-card ${selected ? "is-selected" : ""} ${focused ? "is-focused" : ""}">
      <button class="review-card-figure" type="button" data-action="focus-review-page" data-page-id="${page.id}">
        <img src="${normalizeAssetPath(page.previewPath)}" alt="${page.title}" loading="lazy" />
        ${selected ? `<span class="review-card-tag">${t("review.selectedTag", { locale })}</span>` : ""}
      </button>
      <div class="review-card-meta review-card-meta-detail">
        <div class="review-card-copy">
          <span>${page.title}</span>
          <small>${locked ? t("review.locked", { locale }) : t("review.candidate", { locale })}</small>
        </div>
        <div class="review-card-badges">
          ${page.suspicious ? `<span class="review-inline-pill review-inline-pill-risk">${t("review.check", { locale })}</span>` : ""}
        </div>
        <label class="choice-row">
          <input aria-label="${t("review.includeAria", { locale, replacements: { title: page.title } })}" data-action="toggle-review-page" data-page-id="${page.id}" type="checkbox" ${selected ? "checked" : ""} ${locked ? "disabled" : ""} />
          ${t("review.include", { locale })}
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
  const selectedCount = reviewDone
    ? Number(state.review.keptCount || summary.keptCount || 0)
    : summary.keptCount;
  const reviewLabel = state.source.displayName || t("review.fallbackLabel", { locale });
  const focusedPage = pages.find((page) => page.id === state.review.focusedPageId) || pages[0];

  return `
    <section class="screen screen-review" data-screen="review">
      <header class="screen-headline screen-headline-review">
        <div>
          <h1>${t("review.title", { locale })}</h1>
          <p>${reviewLabel} • ${reviewDone
            ? t("review.keptCount", { locale, replacements: { count: selectedCount } })
            : t("review.selectedCount", { locale, replacements: { selected: selectedCount, total: pages.length } })}</p>
        </div>
        <div class="review-toolbar">
          <div class="review-summary-pills">
            <span class="review-summary-pill">${reviewDone ? t("review.kept", { locale }) : t("review.selected", { locale })} ${selectedCount} / ${pages.length}</span>
          </div>
          ${reviewDone
            ? `<p class="panel-note review-status-note">${t("review.appliedNote", { locale })}</p>`
            : `<button class="button button-primary" data-action="apply-review" ${summary.keptCount === 0 || !state.exportConfig.jobId || state.review.status === "running" || state.exportConfig.runStatus !== "done" ? "disabled" : ""}>${state.review.status === "running" ? t("review.applyBusy", { locale }) : t("review.apply", { locale })}</button>`}
        </div>
      </header>
      <section class="review-grid-shell" data-stitch-region="review-grid">
        <div class="review-grid">
          ${pages.map((page) => renderPageCard(page, selectedSet.has(page.id), page.id === state.review.focusedPageId, reviewDone, locale)).join("")}
        </div>
      </section>
      ${state.review.error ? `<p class="inline-error" role="alert">${state.review.error}</p>` : ""}
    </section>
  `;
}
