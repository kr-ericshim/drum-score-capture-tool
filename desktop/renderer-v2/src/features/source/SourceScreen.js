import { t } from "../../lib/i18n.js";

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
  return /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\//i.test(text);
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
    youtubeUrl: state.source.youtubeUrl || "",
    prepareLogs: Array.isArray(state.source.prepareLogs) ? state.source.prepareLogs : [],
    prepareDisabled: state.source.prepareStatus === "loading" || !isLikelyYoutubeUrl(state.source.youtubeUrl),
    youtubeUrlValid: isLikelyYoutubeUrl(state.source.youtubeUrl),
    showQualityGate: /low resolution|resolved to/i.test(String(state.source.prepareErrorDetail || "")),
    error: state.source.error || "",
    errorDetail: state.source.prepareErrorDetail || "",
  };
}

function renderRegistryRows(model) {
  if (!model.fileMeta.length) {
    return `
      <tr>
        <td colspan="5" class="registry-empty">${t("source.registryEmpty", { locale: model.locale })}</td>
      </tr>
    `;
  }

  return `
    <tr class="registry-row is-selected">
      <td>${model.fileMeta.find((item) => item.label === t("source.meta.file", { locale: model.locale }))?.value || "session_capture.mp4"}</td>
      <td>${model.fileDirectory || t("source.directoryMissing", { locale: model.locale })}</td>
      <td>${model.fileMeta.find((item) => item.label === t("source.meta.resolution", { locale: model.locale }))?.value || "1920x1080"}</td>
      <td>${model.fileMeta.find((item) => item.label === t("source.meta.length", { locale: model.locale }))?.value || "00:00"}</td>
      <td><span class="registry-status">${t("source.activeStatus", { locale: model.locale })}</span></td>
    </tr>
  `;
}

export function renderSourceScreen(state) {
  const model = buildSourceScreenModel(state);

  return `
    <section class="screen screen-source" data-screen="source">
      <header class="screen-headline screen-headline-source">
        <div>
          <h1>${model.title}</h1>
          <p>${model.helper}</p>
        </div>
      </header>
      <div class="source-workbench">
        <section class="source-ingest panel" data-stitch-region="source-ingest">
          <div class="ingest-icon">+</div>
          <h2>${t("source.ingestTitle", { locale: model.locale })}</h2>
          <p>${t("source.ingestBody", { locale: model.locale })}</p>
          <div class="source-actions">
            <button class="button button-primary" data-action="select-source-file">${model.primaryAction.displayLabel}</button>
          </div>
          <div class="source-youtube">
            <div class="source-youtube-copy">
              <span class="source-youtube-kicker">${t("source.youtubeTitle", { locale: model.locale })}</span>
              <p>${t("source.youtubeHint", { locale: model.locale })}</p>
            </div>
            <div class="source-youtube-controls">
              <label class="source-youtube-field">
                <input
                  type="url"
                  inputmode="url"
                  autocomplete="off"
                  spellcheck="false"
                  value="${model.youtubeUrl}"
                  placeholder="${t("source.youtubePlaceholder", { locale: model.locale })}"
                  data-action="youtube-url-input"
                />
              </label>
              <button class="button button-secondary source-youtube-submit" data-action="prepare-source-youtube" ${model.prepareDisabled ? "disabled" : ""}>${t("source.youtubeAction", { locale: model.locale })}</button>
            </div>
            ${model.youtubeUrl && !model.youtubeUrlValid ? `<p class="source-youtube-note">${t("source.youtubeInvalid", { locale: model.locale })}</p>` : ""}
            ${model.showQualityGate ? `
              <div class="source-quality-gate" data-tone="warning">
                <strong>${t("source.qualityGateTitle", { locale: model.locale })}</strong>
                <p>${t("source.qualityGateBody", { locale: model.locale, replacements: { detail: model.errorDetail } })}</p>
              </div>
            ` : ""}
            <div class="source-prepare-log" data-role="youtube-log">
              <strong>${t("source.youtubeLogTitle", { locale: model.locale })}</strong>
              <pre>${model.prepareLogs.length ? model.prepareLogs.join("\n") : t("source.youtubeIdleLog", { locale: model.locale })}</pre>
            </div>
          </div>
        </section>
        <section class="source-registry panel" data-stitch-region="source-registry">
          <div class="panel-heading">
            <h2>${t("source.registryTitle", { locale: model.locale })}</h2>
            <p>${t("source.registryRegistered", { locale: model.locale, replacements: { count: model.fileMeta.length ? 1 : 0 } })}</p>
          </div>
          <div class="registry-table-wrap">
            <table class="registry-table">
              <thead>
                <tr>
                  <th>${t("source.registryFilename", { locale: model.locale })}</th>
                  <th>${t("source.registryPath", { locale: model.locale })}</th>
                  <th>${t("source.registryRes", { locale: model.locale })}</th>
                  <th>${t("source.registryLength", { locale: model.locale })}</th>
                  <th>${t("source.registryAction", { locale: model.locale })}</th>
                </tr>
              </thead>
              <tbody>
                ${renderRegistryRows(model)}
              </tbody>
            </table>
          </div>
        </section>
      </div>
      ${model.error ? `<p class="inline-error" role="alert">${model.error}</p>` : ""}
    </section>
  `;
}
