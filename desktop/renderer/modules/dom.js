export function el(id) {
  return document.getElementById(id);
}

export function clamp(num, min, max) {
  return Math.max(min, Math.min(max, num));
}

export function parseJsonOrNull(text) {
  const value = (text || "").trim();
  if (!value) {
    return null;
  }
  try {
    return JSON.parse(value);
  } catch (_) {
    return null;
  }
}

export function fileUrl(filePath) {
  const normalized = String(filePath || "").replace(/\\/g, "/");
  if (!normalized) {
    return "";
  }
  const segments = normalized.split("/").map((segment, index) => {
    const encoded = encodeURIComponent(segment);
    if (index === 0 && /^[a-zA-Z]:$/.test(segment)) {
      return segment;
    }
    return encoded;
  });
  let encodedPath = segments.join("/");
  if (!encodedPath.startsWith("/")) {
    encodedPath = `/${encodedPath}`;
  }
  return `file://${encodedPath}`;
}
