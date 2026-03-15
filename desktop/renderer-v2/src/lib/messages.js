import { t } from "./i18n.js";

export function notice(key, { locale, replacements } = {}) {
  return t(`notice.${key}`, { locale, replacements });
}

export function youtubePrepareDetail(error) {
  return String(error?.message || error || "").trim();
}

export function isYoutubePrepareQualityIssue(detail) {
  return /low resolution|resolved to/i.test(String(detail || ""));
}

export function youtubePrepareError(errorOrDetail, locale = "en") {
  const detail = youtubePrepareDetail(errorOrDetail);
  if (!detail) {
    return locale === "ko" ? "유튜브 영상을 준비하지 못했습니다." : "Could not prepare the YouTube video.";
  }
  if (isYoutubePrepareQualityIssue(detail)) {
    return locale === "ko"
      ? `저화질 영상으로 감지되어 준비를 중단했습니다: ${detail}`
      : `YouTube preparation stopped because only a low-resolution video was available: ${detail}`;
  }
  return detail;
}

export function mergePrepareLogs(existing = [], error) {
  const detail = youtubePrepareDetail(error);
  if (!detail) {
    return [...existing];
  }
  return [...existing, detail];
}
