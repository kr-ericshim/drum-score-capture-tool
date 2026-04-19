import { t } from "../../lib/i18n.js";

const BRAND_TITLE = "DRUM SHEET CAPTURE";
const BRAND_SUBTITLE = "PRECISION MEDIA WORKBENCH";

export function renderTopBar(state, summary) {
  const locale = state.ui.locale || "ko";
  const backendReady = state.ui.backend?.ready;
  const stepLabel = t(`topbar.step.${state.ui.activeStep}`, { locale });

  if (state.ui.activeStep === "roi") {
    return `
      <div class="topbar-center topbar-center-solo">
        <span class="topbar-source">${summary.sourceLabel}</span>
        <span class="topbar-step">${stepLabel}</span>
      </div>
      <div class="topbar-tools">
        <button class="topbar-archive" type="button" data-action="open-archive">${t("topbar.archive", { locale })}</button>
        <button class="topbar-locale ${locale === "ko" ? "is-active" : ""}" data-action="set-locale" data-locale="ko">${t("topbar.locale.ko", { locale })}</button>
        <button class="topbar-locale ${locale === "en" ? "is-active" : ""}" data-action="set-locale" data-locale="en">${t("topbar.locale.en", { locale })}</button>
      </div>
    `;
  }

  return `
    <div class="topbar-brand">
      <span class="topbar-mark" aria-hidden="true"></span>
      <div class="topbar-copy">
        <strong>${t("topbar.brandTitle", { locale }) || BRAND_TITLE}</strong>
        <span>${t("topbar.brandSubtitle", { locale }) || BRAND_SUBTITLE}</span>
      </div>
    </div>
    <div class="topbar-center">
      <span class="topbar-source">${summary.sourceLabel}</span>
      <span class="topbar-step">${stepLabel}</span>
    </div>
    <div class="topbar-tools">
      <button class="topbar-archive" type="button" data-action="open-archive">${t("topbar.archive", { locale })}</button>
      <button class="topbar-locale ${locale === "ko" ? "is-active" : ""}" data-action="set-locale" data-locale="ko">${t("topbar.locale.ko", { locale })}</button>
      <button class="topbar-locale ${locale === "en" ? "is-active" : ""}" data-action="set-locale" data-locale="en">${t("topbar.locale.en", { locale })}</button>
      <span class="engine-badge ${backendReady ? "is-ready" : "is-waiting"}">${backendReady ? t("topbar.engine.ready", { locale }) : t("topbar.engine.waiting", { locale })}</span>
    </div>
  `;
}
