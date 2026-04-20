import { t } from "../../lib/i18n.js";

function escapeHtml(value = "") {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function fileDirectory(filePath = "") {
  const normalized = String(filePath || "").replace(/\\/g, "/");
  if (!normalized) {
    return "";
  }
  const parts = normalized.split("/");
  parts.pop();
  const directory = parts.join("/");
  if (!directory) {
    return normalized.startsWith("/") ? "/" : "";
  }
  return directory.endsWith("/") ? directory : `${directory}/`;
}

function isLikelyYoutubeUrl(value = "") {
  const text = String(value || "").trim();
  if (!text) {
    return false;
  }
  return /^(https?:\/\/)?(((www|m|music)\.)?youtube\.com|youtu\.be)\//i.test(text);
}

function preparePercent(progress = 0) {
  return Math.max(0, Math.min(100, Math.round(Number(progress || 0) * 100)));
}

function fileName(filePath = "") {
  const normalized = String(filePath || "").replace(/\\/g, "/");
  if (!normalized) {
    return "";
  }
  return normalized.split("/").pop() || normalized;
}

function normalizeRegistryItem(item = {}) {
  const filePath = String(item.filePath || "").trim();
  if (!filePath) {
    return null;
  }
  const sourceOrigin = String(item.sourceOrigin || "job").trim() || "job";
  const youtubeUrl = String(item.youtubeUrl || "").trim();
  return {
    filePath,
    displayName: String(item.displayName || "").trim() || fileName(filePath),
    directory: String(item.directory || "").trim() || fileDirectory(filePath),
    resolutionLabel: String(item.resolutionLabel || "").trim(),
    durationLabel: String(item.durationLabel || "").trim(),
    hasScore: Boolean(item.hasScore),
    sourceOrigin,
    youtubeUrl,
  };
}

function buildRegistryItems(state) {
  const items = Array.isArray(state.source.registryItems)
    ? state.source.registryItems.map(normalizeRegistryItem).filter(Boolean)
    : [];
  const activePath = String(state.source.filePath || "").trim();
  if (!activePath) {
    return items;
  }

  const activeItem = normalizeRegistryItem({
    filePath: activePath,
    displayName: state.source.displayName || fileName(activePath),
    directory: fileDirectory(activePath),
    resolutionLabel: state.source.metadata?.resolutionLabel || "",
    durationLabel: state.source.metadata?.durationLabel || "",
    hasScore: items.find((item) => item.filePath === activePath)?.hasScore,
    sourceOrigin: state.source.archiveSourceKind === "youtube" ? "prepared" : "job",
    youtubeUrl: state.source.archiveSourceKind === "youtube" ? state.source.archiveSourceKey : "",
  });

  if (!activeItem) {
    return items;
  }

  const matchIndex = items.findIndex((item) => item.filePath === activePath);
  if (matchIndex >= 0) {
    items[matchIndex] = {
      ...items[matchIndex],
      ...activeItem,
      hasScore: items[matchIndex].hasScore,
    };
    return items;
  }
  return [activeItem, ...items];
}

export function buildSourceScreenModel(state) {
  const locale = state.ui.locale || "ko";
  const metadata = state.source.metadata || {};
  const fileMeta = [];
  if (state.source.displayName) {
    fileMeta.push({ label: t("source.meta.file", { locale }), value: state.source.displayName });
  }
  if (metadata.durationLabel) {
    fileMeta.push({ label: t("source.meta.length", { locale }), value: metadata.durationLabel });
  }
  if (metadata.resolutionLabel) {
    fileMeta.push({ label: t("source.meta.resolution", { locale }), value: metadata.resolutionLabel });
  }

  const prepareStage = String(state.source.prepareStage || "");
  const prepareProgressMode = String(state.source.prepareProgressMode || "indeterminate");
  const preparePercentValue = preparePercent(state.source.prepareProgress);
  const prepareStageLabel = prepareStage ? t(`source.prepareStage.${prepareStage}`, { locale }) : "";
  const prepareSummary = prepareStage
    ? (prepareProgressMode === "determinate"
      ? t("source.prepareStageProgress", {
        locale,
        replacements: {
          stage: prepareStageLabel,
          percent: `${preparePercentValue}%`,
        },
      })
      : prepareStageLabel)
    : String(state.source.prepareMessage || "");

  return {
    locale,
    title: t("source.title", { locale }),
    helper: t("source.helper", { locale }),
    primaryAction: {
      label: t("source.title", { locale }),
      displayLabel: t("source.primaryAction", { locale }),
      disabled: false,
    },
    secondaryAction: null,
    fileMeta,
    fileDirectory: fileDirectory(state.source.filePath),
    currentFilePath: String(state.source.filePath || ""),
    registryItems: buildRegistryItems(state),
    youtubeUrl: state.source.youtubeUrl || "",
    prepareStatus: state.source.prepareStatus || "idle",
    prepareStage,
    prepareStageLabel,
    prepareSummary,
    prepareProgress: preparePercentValue,
    prepareProgressMode,
    prepareMessage: state.source.prepareMessage || "",
    prepareLogs: Array.isArray(state.source.prepareLogs) ? state.source.prepareLogs : [],
    prepareDisabled: state.source.prepareStatus === "loading" || !isLikelyYoutubeUrl(state.source.youtubeUrl),
    youtubeUrlValid: isLikelyYoutubeUrl(state.source.youtubeUrl),
    showQualityGate: /low resolution|resolved to/i.test(String(state.source.prepareErrorDetail || "")),
    showPrepareStatus: state.source.prepareStatus !== "idle" || (Array.isArray(state.source.prepareLogs) && state.source.prepareLogs.length > 0),
    error: state.source.error || "",
    errorDetail: state.source.prepareErrorDetail || "",
  };
}

function getRegistryColumns(locale) {
  return [
    { key: "filename", label: t("source.registryFilename", { locale }) },
    { key: "path", label: t("source.registryPath", { locale }) },
    { key: "resolution", label: t("source.registryRes", { locale }) },
    { key: "duration", label: t("source.registryLength", { locale }) },
    { key: "action", label: t("source.registryAction", { locale }) },
  ];
}

function renderRegistryCell(column, content) {
  return `<td data-column="${escapeHtml(column.key)}" data-column-label="${escapeHtml(column.label)}">${content}</td>`;
}

function renderRegistryRows(model) {
  if (!model.registryItems.length) {
    return `
      <tr>
        <td colspan="5" class="registry-empty">${escapeHtml(t("source.registryEmpty", { locale: model.locale }))}</td>
      </tr>
    `;
  }

  return model.registryItems.map((item) => {
    const selected = item.filePath === model.currentFilePath;
    const actionMarkup = selected
      ? `<span class="registry-status">${escapeHtml(t("source.activeStatus", { locale: model.locale }))}</span>`
      : `<button type="button" data-action="load-registry-source" data-file-path="${escapeHtml(item.filePath)}" data-display-name="${escapeHtml(item.displayName || "")}" data-source-origin="${escapeHtml(item.sourceOrigin || "job")}" data-youtube-url="${escapeHtml(item.youtubeUrl || "")}">${escapeHtml(t("source.registryLoad", { locale: model.locale }))}</button>`;
    const columns = getRegistryColumns(model.locale);
    return `
      <tr class="registry-row${selected ? " is-selected" : ""}" data-selected="${selected ? "true" : "false"}">
        ${renderRegistryCell(columns[0], escapeHtml(item.displayName || fileName(item.filePath) || "source.mp4"))}
        ${renderRegistryCell(columns[1], escapeHtml(item.directory || t("source.directoryMissing", { locale: model.locale })))}
        ${renderRegistryCell(columns[2], escapeHtml(item.resolutionLabel || t("source.registryUnknown", { locale: model.locale })))}
        ${renderRegistryCell(columns[3], escapeHtml(item.durationLabel || t("source.registryUnknown", { locale: model.locale })))}
        ${renderRegistryCell(columns[4], actionMarkup)}
      </tr>
    `;
  }).join("");
}

export function renderSourceScreen(state) {
  const model = buildSourceScreenModel(state);
  const hintId = "sourceYoutubeHint";
  const logId = "sourceYoutubeLog";
  const noteId = model.youtubeUrl && !model.youtubeUrlValid ? "sourceYoutubeNote" : "";

  return `
    <section class="screen screen-source" data-screen="source" aria-labelledby="sourceScreenTitle">
      <header class="screen-headline screen-headline-source">
        <div>
          <h1 id="sourceScreenTitle" data-screen-heading tabindex="-1">${escapeHtml(model.title)}</h1>
          <p>${escapeHtml(model.helper)}</p>
        </div>
      </header>
      <div class="source-workbench">
        <section class="source-ingest panel" data-stitch-region="source-ingest" data-drop-zone="source-ingest">
          <div class="ingest-icon">+</div>
          <div class="panel-heading source-ingest-heading">
            <span class="panel-kicker">${escapeHtml(t("source.ingestKicker", { locale: model.locale }))}</span>
            <h2>${escapeHtml(t("source.ingestTitle", { locale: model.locale }))}</h2>
            <p>${escapeHtml(t("source.ingestBody", { locale: model.locale }))}</p>
          </div>
          <div class="source-actions">
            <button class="button button-primary" data-action="select-source-file">${escapeHtml(model.primaryAction.displayLabel)}</button>
          </div>
          <p class="source-drop-hint" aria-live="polite">
            <span class="source-drop-idle">${escapeHtml(t("source.dropHint", { locale: model.locale }))}</span>
            <span class="source-drop-active">${escapeHtml(t("source.dropActive", { locale: model.locale }))}</span>
          </p>
          <div class="source-youtube">
            <div class="source-youtube-copy">
              <span class="source-youtube-kicker">${escapeHtml(t("source.youtubeTitle", { locale: model.locale }))}</span>
              <p id="${hintId}">${escapeHtml(t("source.youtubeHint", { locale: model.locale }))}</p>
            </div>
            <div class="source-youtube-controls">
              <div class="source-youtube-field">
                <label class="visually-hidden" for="sourceYoutubeUrl">${escapeHtml(t("source.youtubeFieldLabel", { locale: model.locale }))}</label>
                <input
                  id="sourceYoutubeUrl"
                  type="url"
                  inputmode="url"
                  autocomplete="off"
                  spellcheck="false"
                  value="${escapeHtml(model.youtubeUrl)}"
                  placeholder="${escapeHtml(t("source.youtubePlaceholder", { locale: model.locale }))}"
                  aria-describedby="${escapeHtml([hintId, noteId].filter(Boolean).join(" "))}"
                  data-action="youtube-url-input"
                />
              </div>
              <button class="button button-secondary source-youtube-submit" data-action="prepare-source-youtube" ${model.prepareDisabled ? "disabled" : ""}>${escapeHtml(t("source.youtubeAction", { locale: model.locale }))}</button>
            </div>
            ${model.youtubeUrl && !model.youtubeUrlValid ? `<p id="${noteId}" class="source-youtube-note">${escapeHtml(t("source.youtubeInvalid", { locale: model.locale }))}</p>` : ""}
            ${model.showPrepareStatus ? `
              <div class="source-prepare-status" data-status="${escapeHtml(model.prepareStatus)}">
                <div class="source-prepare-status-head">
                  <strong>${escapeHtml(t("source.youtubeStatusTitle", { locale: model.locale }))}</strong>
                  <span>${escapeHtml(model.prepareSummary || model.prepareMessage || t("source.youtubeIdleLog", { locale: model.locale }))}</span>
                </div>
                <div
                  class="source-prepare-progress"
                  data-mode="${escapeHtml(model.prepareProgressMode)}"
                  role="progressbar"
                  aria-label="${escapeHtml(t("source.youtubeProgressAria", { locale: model.locale }))}"
                  aria-valuemin="0"
                  aria-valuemax="100"
                  ${model.prepareProgressMode === "determinate"
                    ? `aria-valuenow="${model.prepareProgress}" aria-valuetext="${escapeHtml(`${model.prepareProgress}%`)}"`
                    : `aria-valuetext="${escapeHtml(model.prepareSummary || model.prepareMessage || t("source.youtubeIdleLog", { locale: model.locale }))}"`}
                >
                  <span class="source-prepare-progress-track">
                    <span class="source-prepare-progress-fill" style="width: ${model.prepareProgressMode === "determinate" ? model.prepareProgress : 35}%"></span>
                  </span>
                  <span class="source-prepare-progress-value">${escapeHtml(model.prepareProgressMode === "determinate" ? `${model.prepareProgress}%` : t("source.prepareIndeterminate", { locale: model.locale }))}</span>
                </div>
              </div>
            ` : ""}
            ${model.showQualityGate ? `
              <div class="source-quality-gate" data-tone="warning">
                <strong>${escapeHtml(t("source.qualityGateTitle", { locale: model.locale }))}</strong>
                <p>${escapeHtml(t("source.qualityGateBody", { locale: model.locale, replacements: { detail: model.errorDetail } }))}</p>
              </div>
            ` : ""}
            <div id="${logId}" class="source-prepare-log" data-role="youtube-log" aria-live="polite">
              <strong>${escapeHtml(t("source.youtubeLogTitle", { locale: model.locale }))}</strong>
              <pre>${escapeHtml(model.prepareLogs.length ? model.prepareLogs.join("\n") : t("source.youtubeIdleLog", { locale: model.locale }))}</pre>
            </div>
          </div>
        </section>
        <section class="source-registry panel" data-stitch-region="source-registry">
          <div class="panel-heading">
            <span class="panel-kicker">${escapeHtml(t("source.registryKicker", { locale: model.locale }))}</span>
            <h2>${escapeHtml(t("source.registryTitle", { locale: model.locale }))}</h2>
            <p>${escapeHtml(t("source.registryBody", { locale: model.locale }))}</p>
            <p>${escapeHtml(t("source.registryRegistered", { locale: model.locale, replacements: { count: model.registryItems.length } }))}</p>
          </div>
          <div class="registry-table-wrap">
            <table class="registry-table">
              <thead>
                <tr>
                  ${getRegistryColumns(model.locale).map((column) => `<th scope="col" data-column="${escapeHtml(column.key)}">${escapeHtml(column.label)}</th>`).join("")}
                </tr>
              </thead>
              <tbody>
                ${renderRegistryRows(model)}
              </tbody>
            </table>
          </div>
        </section>
      </div>
      ${model.error ? `<p class="inline-error" role="alert">${escapeHtml(model.error)}</p>` : ""}
    </section>
  `;
}
