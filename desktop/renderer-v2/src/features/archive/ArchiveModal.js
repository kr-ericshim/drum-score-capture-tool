import { escapeAttr, escapeHtml } from "../../lib/html.js";
import { t } from "../../lib/i18n.js";

function formatCompletedAt(timestamp, locale) {
  const value = Number(timestamp || 0);
  if (!Number.isFinite(value) || value <= 0) {
    return "";
  }

  try {
    return new Intl.DateTimeFormat(locale === "ko" ? "ko-KR" : "en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    }).format(new Date(value * 1000));
  } catch (_) {
    return "";
  }
}

function pathBaseName(filePath = "") {
  const normalized = String(filePath || "").replace(/\\/g, "/").trim();
  if (!normalized) {
    return "";
  }
  return normalized.split("/").pop() || normalized;
}

function renderArchiveList(items, locale) {
  if (!items.length) {
    return `<p class="archive-empty">${t("archive.empty", { locale })}</p>`;
  }

  return `
    <div class="archive-list" role="list">
      ${items.map((item) => {
        const completedAt = formatCompletedAt(item.completedAt, locale);
        return `
          <div role="listitem">
            <button class="archive-row" type="button" data-action="select-archive-item" data-source-key="${escapeAttr(item.sourceKey)}">
              <span class="archive-row-copy">
                <strong>${escapeHtml(item.displayName || item.sourceKey)}</strong>
                <span>${completedAt || t("archive.completedUnknown", { locale })}</span>
              </span>
            </button>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderArchiveDetail(item, locale) {
  const completedAt = formatCompletedAt(item.completedAt, locale);
  const canReopenSource = Boolean(String(item.sourcePath || "").trim());

  return `
    <div class="archive-detail">
      <button class="archive-back" type="button" data-action="back-archive-detail">${t("archive.back", { locale })}</button>
      <section class="archive-detail-card">
        <p class="archive-detail-kicker">${t("archive.detailLabel", { locale })}</p>
        <h3>${escapeHtml(item.displayName || item.sourceKey)}</h3>
        <p class="archive-detail-meta">${completedAt || t("archive.completedUnknown", { locale })}</p>
        <dl class="archive-detail-paths">
          <div>
            <dt>${escapeHtml(t("archive.pathLabel.pdf", { locale }))}</dt>
            <dd>${escapeHtml(pathBaseName(item.pdfPath) || t("archive.completedUnknown", { locale }))}</dd>
          </div>
          <div>
            <dt>${escapeHtml(t("archive.pathLabel.folder", { locale }))}</dt>
            <dd>${escapeHtml(pathBaseName(item.outputDir) || t("archive.completedUnknown", { locale }))}</dd>
          </div>
          <div>
            <dt>${escapeHtml(t("archive.pathLabel.source", { locale }))}</dt>
            <dd>${escapeHtml(pathBaseName(item.sourcePath) || t("archive.completedUnknown", { locale }))}</dd>
          </div>
        </dl>
        <div class="archive-detail-actions">
          <button class="button button-secondary" type="button" data-action="reopen-archive-source" data-source-key="${escapeAttr(item.sourceKey)}" data-file-path="${escapeAttr(item.sourcePath || "")}" data-source-kind="${escapeAttr(item.sourceKind || "file")}" data-display-name="${escapeAttr(item.displayName || "")}" data-youtube-url="${escapeAttr(item.youtubeUrl || "")}" ${canReopenSource ? "" : "disabled"}>${t("archive.reopenSource", { locale })}</button>
          <button class="button button-primary" type="button" data-action="open-archive-pdf" data-source-key="${escapeAttr(item.sourceKey)}" ${item.pdfPath ? "" : "disabled"}>${t("archive.openPdf", { locale })}</button>
          <button class="button button-secondary" type="button" data-action="open-archive-folder" data-source-key="${escapeAttr(item.sourceKey)}" ${item.outputDir ? "" : "disabled"}>${t("archive.openFolder", { locale })}</button>
        </div>
      </section>
    </div>
  `;
}

function isWorkRunning(state) {
  return state.exportConfig?.runStatus === "running"
    || state.source?.prepareStatus === "loading"
    || ["running", "editing"].includes(state.review?.status);
}

function renderArchiveStorage(state, locale) {
  const storage = state.archive?.storage || {};
  const busy = isWorkRunning(state);
  const clearing = storage.status === "clearing";
  const usageText = storage.status === "loading"
    ? t("archive.storage.checking", { locale })
    : storage.status === "error" || !storage.totalHuman
      ? t("archive.storage.unknown", { locale })
      : t("archive.storage.usage", { locale, replacements: { size: storage.totalHuman, count: Number(storage.totalPaths || 0) } });
  const message = storage.error
    ? `<p class="archive-storage-message is-error" role="alert">${escapeHtml(storage.error)}</p>`
    : storage.result
      ? `<p class="archive-storage-message" role="status">${escapeHtml(storage.result)}</p>`
      : busy
        ? `<p class="archive-storage-message">${escapeHtml(t("archive.storage.busy", { locale }))}</p>`
        : "";
  return `
    <footer class="archive-storage" data-archive-storage>
      <div class="archive-storage-row">
        <div class="archive-storage-copy">
          <strong>${escapeHtml(t("archive.storage.title", { locale }))}</strong>
          <span>${escapeHtml(usageText)}</span>
        </div>
        ${storage.confirm ? "" : `<button class="button button-secondary archive-storage-clear" type="button" data-action="request-clear-cache" ${busy || clearing ? "disabled" : ""}>${escapeHtml(t("archive.storage.clear", { locale }))}</button>`}
      </div>
      ${storage.confirm ? `
        <div class="archive-storage-confirm" role="alertdialog" aria-labelledby="archiveStorageWarning">
          <p id="archiveStorageWarning">${escapeHtml(t("archive.storage.warning", { locale }))}</p>
          <div class="archive-storage-actions">
            <button class="button button-danger" type="button" data-action="confirm-clear-cache" ${busy || clearing ? "disabled" : ""}>${escapeHtml(t(clearing ? "archive.storage.clearing" : "archive.storage.confirm", { locale }))}</button>
            <button class="button button-secondary" type="button" data-action="cancel-clear-cache" ${clearing ? "disabled" : ""}>${escapeHtml(t("archive.storage.cancel", { locale }))}</button>
          </div>
        </div>
      ` : ""}
      ${message}
    </footer>
  `;
}

export function renderArchiveModal(state) {
  if (!state.archive?.isOpen) {
    return "";
  }

  const locale = state.ui.locale || "en";
  const items = Array.isArray(state.archive.items) ? state.archive.items : [];
  const selectedItem = items.find((item) => item.sourceKey === state.archive.selectedSourceKey) || null;
  const isError = state.archive.status === "error";
  const isLoading = state.archive.status === "loading";

  return `
    <div class="archive-overlay" data-archive-modal>
      <button class="archive-backdrop" type="button" data-action="close-archive" aria-label="${escapeAttr(t("archive.close", { locale }))}"></button>
      <section class="archive-modal" role="dialog" aria-modal="true" aria-labelledby="archiveModalTitle" tabindex="-1" data-archive-dialog>
        <header class="archive-modal-head">
          <div class="archive-modal-copy">
            <p class="archive-modal-kicker">${t("topbar.archive", { locale })}</p>
            <h2 id="archiveModalTitle">${t("archive.title", { locale })}</h2>
            <p>${t("archive.subtitle", { locale })}</p>
          </div>
          <button class="archive-close" type="button" data-action="close-archive">${t("archive.close", { locale })}</button>
        </header>
        <div class="archive-modal-body" aria-busy="${isLoading ? "true" : "false"}">
          ${isError ? `
            <div class="archive-feedback">
              <p class="inline-error" role="alert">${escapeHtml(state.archive.error || t("archive.error", { locale }))}</p>
              <button class="button button-secondary" type="button" data-action="retry-archive">${t("archive.retry", { locale })}</button>
            </div>
          ` : isLoading
            ? `<p class="archive-empty" role="status">${t("archive.loading", { locale })}</p>`
            : selectedItem
              ? renderArchiveDetail(selectedItem, locale)
              : renderArchiveList(items, locale)}
        </div>
        ${renderArchiveStorage(state, locale)}
      </section>
    </div>
  `;
}
