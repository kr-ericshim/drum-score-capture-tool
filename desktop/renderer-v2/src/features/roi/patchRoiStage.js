// Keep the canvas attached while its draft changes during a pointer gesture.
export function patchRoiStage(stage, markup) {
  const current = stage?.querySelector?.('[data-screen="roi"]');
  const image = current?.querySelector?.("#roiImage");
  const document = stage?.ownerDocument;
  if (!image || !document?.createElement) return false;
  const template = document.createElement("template");
  template.innerHTML = markup;
  const next = template.content.querySelector('[data-screen="roi"]');
  if (!next || next.querySelector("#roiImage")?.getAttribute("src") !== image.getAttribute("src")) return false;
  for (const selector of [".roi-stage-footer", ".roi-candidate-strip"]) {
    const oldNode = current.querySelector(selector);
    const newNode = next.querySelector(selector);
    if (Boolean(oldNode) !== Boolean(newNode)) return false;
  }
  for (const selector of [".roi-stage-footer", ".roi-candidate-strip"]) {
    const oldNode = current.querySelector(selector);
    const newNode = next.querySelector(selector);
    if (oldNode && oldNode.innerHTML !== newNode.innerHTML) oldNode.innerHTML = newNode.innerHTML;
  }
  const slider = current.querySelector("#frameTimeSlider");
  const nextSlider = next.querySelector("#frameTimeSlider");
  if (slider && nextSlider) {
    slider.value = nextSlider.value; slider.max = nextSlider.max; slider.disabled = nextSlider.disabled;
  }
  for (const selector of ["#frameTimeValue", '[data-action="load-preview-frame"]']) {
    const oldNode = current.querySelector(selector), newNode = next.querySelector(selector);
    if (oldNode && newNode) { oldNode.textContent = newNode.textContent; oldNode.disabled = newNode.disabled; }
  }
  const hidden = current.querySelector("#roiInput");
  if (hidden) hidden.value = next.querySelector("#roiInput")?.value || "";
  return true;
}
