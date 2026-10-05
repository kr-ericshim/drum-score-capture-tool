// The capture list lays out every thumbnail the same way, chosen from the captures' real aspect ratio:
// wide score strips span the panel, portrait pages sit as small pages beside their details.
// Aspects are only known once an image loads, so they are cached by image path and the grid is updated in place.
const PAGE_ASPECT_LIMIT = 1.15;
const aspects = new Map();

export function rememberThumbAspect(src, width, height) {
  if (!src || !(width > 0) || !(height > 0)) return;
  aspects.set(String(src), width / height);
}

export function thumbShapeFor(paths) {
  const known = (paths || []).map(path => aspects.get(String(path))).filter(Number.isFinite).sort((a, b) => a - b);
  if (!known.length) return "strip";
  const median = known[Math.floor(known.length / 2)];
  return median < PAGE_ASPECT_LIMIT ? "page" : "strip";
}

export function syncThumbShape(image) {
  const grid = image?.closest?.(".review-grid");
  if (!grid || !image.matches?.(".review-card-figure img")) return;
  rememberThumbAspect(image.getAttribute("src"), image.naturalWidth, image.naturalHeight);
  const paths = [...grid.querySelectorAll(".review-card-figure img")].map(node => node.getAttribute("src"));
  const shape = thumbShapeFor(paths);
  if (grid.dataset.thumbShape !== shape) grid.dataset.thumbShape = shape;
}
