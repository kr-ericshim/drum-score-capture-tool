// Empty endpoints mean the start/end of the source, not an invalid partial range.
export function parseCaptureTime(value) {
  const text = String(value ?? '').trim();
  if (!text) return null;
  if (/^\d+(?:\.\d+)?$/.test(text)) return Number(text);
  if (!/^\d+:\d{1,2}(?::\d{1,2})?(?:\.\d+)?$/.test(text)) return NaN;
  const parts = text.split(':').map(Number);
  if (parts.slice(1).some(part => part >= 60)) return NaN;
  return parts.reduce((total, part) => total * 60 + part, 0);
}

export function captureRange(state) {
  const start = parseCaptureTime(state.exportConfig?.rangeStart) ?? 0;
  const end = parseCaptureTime(state.exportConfig?.rangeEnd);
  const duration = Number(state.source?.metadata?.durationSec || 0);
  let error = '';
  if (!Number.isFinite(start) || (end !== null && !Number.isFinite(end))) error = 'format';
  else if (start < 0 || (end !== null && end <= start)) error = 'order';
  else if (duration > 0 && (start >= duration || (end !== null && end > duration))) error = 'duration';
  return { start, end, error };
}
