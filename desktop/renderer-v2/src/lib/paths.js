export function fileUrl(filePath) {
  const normalized = String(filePath || "").replace(/\\/g, "/");
  if (!normalized) {
    return "";
  }
  const encoded = normalized
    .split("/")
    .map((segment, index) => {
      if (index === 0 && /^[a-zA-Z]:$/.test(segment)) {
        return segment;
      }
      return encodeURIComponent(segment);
    })
    .join("/");
  return encoded.startsWith("/") ? `file://${encoded}` : `file:///${encoded}`;
}

export function baseName(filePath = "") {
  return String(filePath || "").replace(/\\/g, "/").split("/").pop() || "";
}

export function normalizeAssetPath(filePath = "") {
  const raw = String(filePath || "").trim();
  if (!raw) {
    return "";
  }
  if (/^(?:[a-z]+:)?\/\//i.test(raw) || raw.startsWith("data:")) {
    return raw;
  }
  if (raw.startsWith("/") || raw.includes("\\") || /^[a-zA-Z]:[\\/]/.test(raw)) {
    return fileUrl(raw);
  }
  return encodeURI(raw.replace(/\\/g, "/"));
}
