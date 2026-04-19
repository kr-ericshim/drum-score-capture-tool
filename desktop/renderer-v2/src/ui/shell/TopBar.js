import { escapeAttr, escapeHtml } from "../../lib/html.js";
import { t } from "../../lib/i18n.js";

const BRAND_TITLE = "Drum Sheet Capture";
const BRAND_SUBTITLE = "Local score capture workflow";

function renderArchiveButton(locale) {
  return `<button class="topbar-archive" type="button" data-action="open-archive">${escapeHtml(t("topbar.archive", { locale }))}</button>`;
}

function renderLocaleButtons(locale) {
  const localeLabel = escapeAttr(t("topbar.localeLabel", { locale }));
  const koreanLabel = escapeHtml(t("topbar.locale.ko", { locale }));
  const englishLabel = escapeHtml(t("topbar.locale.en", { locale }));
  return `
    <div class="topbar-locale-group" role="group" aria-label="${localeLabel}">
      <button class="topbar-locale ${locale === "ko" ? "is-active" : ""}" data-action="set-locale" data-locale="ko" aria-pressed="${locale === "ko" ? "true" : "false"}">${koreanLabel}</button>
      <button class="topbar-locale ${locale === "en" ? "is-active" : ""}" data-action="set-locale" data-locale="en" aria-pressed="${locale === "en" ? "true" : "false"}">${englishLabel}</button>
    </div>
  `;
}

export function renderTopBar(state, summary) {
  const locale = state.ui.locale || "ko";
  const backendReady = state.ui.backend?.ready;
  const stepLabel = escapeHtml(t(`topbar.step.${state.ui.activeStep}`, { locale }));
  const sourceLabel = escapeHtml(summary.sourceLabel);
  const brandTitle = escapeHtml(t("topbar.brandTitle", { locale }) || BRAND_TITLE);
  const brandSubtitle = escapeHtml(t("topbar.brandSubtitle", { locale }) || BRAND_SUBTITLE);
  const engineLabel = escapeHtml(backendReady ? t("topbar.engine.ready", { locale }) : t("topbar.engine.waiting", { locale }));

  if (state.ui.activeStep === "roi") {
    return `
      <div class="topbar-roi">
        <div class="topbar-balance" aria-hidden="true"></div>
        <div class="topbar-center topbar-center-solo">
          <span class="topbar-source">${sourceLabel}</span>
          <span class="topbar-step">${stepLabel}</span>
        </div>
        <div class="topbar-tools topbar-tools-compact">
          ${renderArchiveButton(locale)}
          ${renderLocaleButtons(locale)}
        </div>
      </div>
    `;
  }

  return `
    <div class="topbar-brand">
      <span class="topbar-mark" aria-hidden="true"></span>
      <div class="topbar-copy">
        <strong>${brandTitle}</strong>
        <span>${brandSubtitle}</span>
      </div>
    </div>
    <div class="topbar-center">
      <span class="topbar-source">${sourceLabel}</span>
      <span class="topbar-step">${stepLabel}</span>
    </div>
    <div class="topbar-tools">
      ${renderArchiveButton(locale)}
      ${renderLocaleButtons(locale)}
      <span class="engine-badge ${backendReady ? "is-ready" : "is-waiting"}">${engineLabel}</span>
    </div>
  `;
}
