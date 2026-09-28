import { escapeAttr, escapeHtml } from "../../lib/html.js";
import { t } from "../../lib/i18n.js";

export function createBugReportDraft() {
  return { description: "", steps: "", email: "", includeDiagnostics: true, includeScreenshot: false };
}

export function createBugReportState() {
  return {
    isOpen: false,
    // editing | sending | sent | error
    status: "editing",
    configured: false,
    diagnostics: "",
    screenshotPreview: "",
    draft: createBugReportDraft(),
    invalid: "",
    errorReason: "",
    notice: "",
  };
}

function fieldLabel(locale, key, required) {
  const tag = t(required ? "bugReport.required" : "bugReport.optional", { locale });
  return `<span class="bug-report-label">${escapeHtml(t(key, { locale }))} <small>${escapeHtml(tag)}</small></span>`;
}

function renderForm(report, locale) {
  const { draft, invalid } = report;
  const sending = report.status === "sending";
  const disabled = sending ? " disabled" : "";
  const describedBy = (field, hintId = "") => {
    const ids = [hintId, invalid === field ? `bugReportError-${field}` : ""].filter(Boolean).join(" ");
    return `${invalid === field ? ' aria-invalid="true"' : ""}${ids ? ` aria-describedby="${ids}"` : ""}`;
  };
  const fieldError = (field) => (invalid === field
    ? `<p class="bug-report-field-error" id="bugReportError-${field}">${escapeHtml(t(`bugReport.error.${field}`, { locale }))}</p>`
    : "");
  const screenshot = draft.includeScreenshot
    ? report.screenshotPreview
      ? `<img class="bug-report-screenshot" src="${escapeAttr(report.screenshotPreview)}" alt="${escapeAttr(t("bugReport.screenshotAlt", { locale }))}">`
      : `<p class="bug-report-hint">${escapeHtml(t("bugReport.screenshotUnavailable", { locale }))}</p>`
    : "";
  const errorKey = report.status === "error" ? `bugReport.error.${report.errorReason || "network"}` : "";
  return `
    <label class="bug-report-field">
      ${fieldLabel(locale, "bugReport.description", true)}
      <textarea rows="4" data-bug-report-field="description" aria-required="true" placeholder="${escapeAttr(t("bugReport.descriptionPlaceholder", { locale }))}"${describedBy("description")}${disabled}>${escapeHtml(draft.description)}</textarea>
      ${fieldError("description")}
    </label>
    <label class="bug-report-field">
      ${fieldLabel(locale, "bugReport.steps", false)}
      <textarea rows="3" data-bug-report-field="steps" placeholder="${escapeAttr(t("bugReport.stepsPlaceholder", { locale }))}"${disabled}>${escapeHtml(draft.steps)}</textarea>
    </label>
    ${report.configured ? `
      <label class="bug-report-field">
        ${fieldLabel(locale, "bugReport.email", false)}
        <input type="email" autocomplete="email" data-bug-report-field="email" value="${escapeAttr(draft.email)}"${describedBy("email", "bugReportEmailHint")}${disabled}>
        <span class="bug-report-hint" id="bugReportEmailHint">${escapeHtml(t("bugReport.emailHint", { locale }))}</span>
        ${fieldError("email")}
      </label>
    ` : ""}
    <div class="bug-report-attachments">
      <label class="bug-report-check">
        <input type="checkbox" data-bug-report-field="includeDiagnostics"${draft.includeDiagnostics ? " checked" : ""}${disabled}>
        <span>${escapeHtml(t("bugReport.includeDiagnostics", { locale }))}</span>
      </label>
      <p class="bug-report-hint">${escapeHtml(t("bugReport.diagnosticsHint", { locale }))}</p>
      ${draft.includeDiagnostics ? `
        <details class="bug-report-diagnostics">
          <summary>${escapeHtml(t("bugReport.viewDiagnostics", { locale }))}</summary>
          <pre tabindex="0">${escapeHtml(report.diagnostics || t("bugReport.diagnosticsEmpty", { locale }))}</pre>
        </details>
      ` : ""}
      ${report.configured ? `
        <label class="bug-report-check">
          <input type="checkbox" data-bug-report-field="includeScreenshot"${draft.includeScreenshot ? " checked" : ""}${disabled}>
          <span>${escapeHtml(t("bugReport.includeScreenshot", { locale }))}</span>
        </label>
        <p class="bug-report-hint">${escapeHtml(t("bugReport.screenshotHint", { locale }))}</p>
        ${screenshot}
      ` : ""}
    </div>
    ${errorKey ? `<p class="inline-error" role="alert">${escapeHtml(t(errorKey, { locale }))}</p>` : ""}
    ${report.notice ? `<p class="bug-report-hint" role="status">${escapeHtml(report.notice)}</p>` : ""}
  `;
}

function renderActions(report, locale) {
  const button = (action, key, tone, disabled = false) =>
    `<button class="button button-${tone}" type="button" data-action="${action}"${disabled ? " disabled" : ""}>${escapeHtml(t(key, { locale }))}</button>`;
  if (report.status === "sent") return button("close-bug-report", "bugReport.close", "primary");
  const sending = report.status === "sending";
  if (!report.configured) {
    return button("close-bug-report", "bugReport.cancel", "secondary") + button("open-bug-report-issue", "bugReport.github", "primary");
  }
  // Primary action last, so it sits at the right edge as in the other dialogs.
  return button("close-bug-report", "bugReport.cancel", "secondary", sending)
    + (report.status === "error" ? button("open-bug-report-issue", "bugReport.github", "secondary") : "")
    + button("send-bug-report", sending ? "bugReport.sending" : "bugReport.send", "primary", sending);
}

export function renderBugReportModal(report, locale) {
  if (!report?.isOpen) return "";
  const sending = report.status === "sending";
  const intro = t(report.configured ? "bugReport.intro" : "bugReport.introGithub", { locale });
  return `
    <div class="archive-overlay" data-bug-report-modal>
      <button class="archive-backdrop" type="button" tabindex="-1" data-action="close-bug-report" aria-label="${escapeAttr(t("bugReport.close", { locale }))}"${sending ? " disabled" : ""}></button>
      <section class="archive-modal bug-report-modal" role="dialog" aria-modal="true" aria-labelledby="bugReportTitle" aria-describedby="bugReportIntro" tabindex="-1" data-bug-report-dialog>
        <header class="archive-modal-head">
          <div class="archive-modal-copy">
            <h2 id="bugReportTitle">${escapeHtml(t("bugReport.title", { locale }))}</h2>
            <p id="bugReportIntro">${escapeHtml(intro)}</p>
          </div>
          <button class="archive-close" type="button" data-action="close-bug-report"${sending ? " disabled" : ""}>${escapeHtml(t("bugReport.close", { locale }))}</button>
        </header>
        <div class="archive-modal-body bug-report-body" aria-busy="${sending ? "true" : "false"}">
          ${report.status === "sent"
            ? `<p class="bug-report-sent" role="status">${escapeHtml(t("bugReport.sent", { locale }))}</p>`
            : renderForm(report, locale)}
        </div>
        <footer class="bug-report-actions">${renderActions(report, locale)}</footer>
      </section>
    </div>
  `;
}
