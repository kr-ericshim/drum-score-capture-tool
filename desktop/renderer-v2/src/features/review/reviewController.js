import { normalizeAssetPath } from "../../lib/paths.js";

export function createReviewController({ getState, setState, api, mountEditor, root }) {
  let jobId = "";
  let undo = [];
  let redo = [];
  let editor = null;
  let canvas = null;
  let draft = null;
  const equal = (a, b) => JSON.stringify(a || null) === JSON.stringify(b || null);
  const snapshot = state => ({
    selected: [...state.review.selectedPageIds],
    crops: Object.fromEntries(state.review.pages.map(page => [page.capturePath, page.cropRect || null])),
  });
  function syncJob() {
    const nextId = getState().exportConfig.jobId;
    if (nextId !== jobId) { jobId = nextId; undo = []; redo = []; }
  }
  function mark(next) {
    next.review.canUndo = undo.length > 0;
    next.review.canRedo = redo.length > 0;
    next.review.status = "idle";
    next.review.cropping = false;
    return next;
  }
  function remember() {
    undo.push(snapshot(getState()));
    undo = undo.slice(-40);
    redo = [];
  }
  function select(ids) {
    syncJob();
    if (["running", "editing"].includes(getState().review.status)) return;
    remember();
    setState(next => { next.review.selectedPageIds = ids; return mark(next); });
  }
  function toggle(id, checked) {
    const ids = new Set(getState().review.selectedPageIds);
    if (checked) ids.add(id); else ids.delete(id);
    select([...ids]);
  }
  async function restore(target) {
    const state = getState();
    const currentJob = state.exportConfig.jobId;
    setState(next => { next.review.status = "editing"; return next; });
    const pages = state.review.pages.map(page => ({ ...page }));
    try {
      for (const page of pages) {
        const roi = target.crops[page.capturePath];
        if (!equal(page.cropRect, roi)) {
          const result = await api.cropCapture(currentJob, page.capturePath, roi || []);
          page.cropRect = roi || null;
          page.previewPath = normalizeAssetPath(result.capture_path);
        }
      }
      if (getState().exportConfig.jobId !== currentJob) return false;
      setState(next => {
        next.review.pages = pages;
        next.review.selectedPageIds = [...target.selected];
        return mark(next);
      });
      return true;
    } catch (error) {
      if (getState().exportConfig.jobId === currentJob) setState(next => {
        next.review.status = "error"; next.review.error = String(error?.message || error); return next;
      });
      return false;
    }
  }
  async function handleAction(action, value) {
    syncJob();
    const state = getState();
    if (["running", "editing"].includes(state.review.status)) return;
    const pages = state.review.filter === "suspicious" ? state.review.pages.filter(page => page.suspicious || page.autoExcludeCandidate) : state.review.pages;
    const focused = pages.find(page => page.id === state.review.focusedPageId) || pages[0];
    if (action === "review-select-all") { select(state.review.pages.map(page => page.id)); return; }
    if (action === "review-select-none") { select([]); return; }
    if (action === "review-undo" || action === "review-redo") {
      const from = action === "review-undo" ? undo : redo;
      const to = action === "review-undo" ? redo : undo;
      if (!from.length) return;
      const current = snapshot(state);
      if (await restore(from[from.length - 1])) {
        from.pop(); to.push(current);
        setState(next => mark(next));
      }
      return;
    }
    if ((action === "review-apply-crop" || action === "review-reset-crop") && focused) {
      const roi = action === "review-reset-crop" ? null : editor?.applyDraft?.() || draft;
      if (action === "review-apply-crop" && !roi) return;
      const before = snapshot(state);
      const target = structuredClone(before);
      target.crops[focused.capturePath] = roi;
      if (await restore(target)) {
        undo.push(before); undo = undo.slice(-40); redo = [];
        setState(next => mark(next));
      }
      return;
    }
    setState(next => {
      if (action === "review-filter") {
        next.review.filter = value;
        const filtered = value === "suspicious" ? next.review.pages.filter(page => page.suspicious || page.autoExcludeCandidate) : next.review.pages;
        if (!filtered.some(page => page.id === next.review.focusedPageId)) next.review.focusedPageId = filtered[0]?.id || "";
        next.review.cropping = false;
      }
      if (action === "review-crop") next.review.cropping = true;
      if (action === "review-close-crop") next.review.cropping = false;
      if (action === "review-fit") next.review.zoom = "fit";
      if (action === "review-actual") next.review.zoom = 1;
      if (action === "review-zoom-in") next.review.zoom = Math.min(4, (Number(next.review.zoom) || 1) + 0.25);
      if (action === "review-zoom-out") next.review.zoom = Math.max(0.25, (Number(next.review.zoom) || 1) - 0.25);
      if (action === "review-next" || action === "review-previous") {
        const index = Math.max(0, pages.findIndex(page => page.id === focused?.id));
        next.review.focusedPageId = pages[Math.max(0, Math.min(pages.length - 1, index + (action === "review-next" ? 1 : -1)))]?.id || "";
        next.review.cropping = false;
      }
      return next;
    });
  }
  function handleKey(event) {
    const state = getState();
    if (state.ui.activeStep !== "review" || state.archive.isOpen || state.review.cropping || state.exportConfig.metadataModal?.isOpen) return;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(event.target?.tagName) || event.target?.isContentEditable) return;
    if (event.target?.tagName === "BUTTON" && event.target?.dataset?.action !== "focus-review-page" && event.key === " ") return;
    let action = event.key === "ArrowRight" ? "review-next" : event.key === "ArrowLeft" ? "review-previous" : "";
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") action = event.shiftKey ? "review-redo" : "review-undo";
    if (event.key === " " && state.review.focusedPageId) {
      event.preventDefault?.();
      toggle(state.review.focusedPageId, !state.review.selectedPageIds.includes(state.review.focusedPageId));
    } else if (action) { event.preventDefault?.(); void handleAction(action); }
  }
  function syncEditor() {
    const nextCanvas = root.querySelector?.("#reviewCropCanvas");
    if (nextCanvas === canvas) return;
    editor?.destroy(); editor = null; canvas = nextCanvas; draft = null;
    if (!canvas) return;
    const state = getState();
    const focused = state.review.pages.find(page => page.id === state.review.focusedPageId) || state.review.pages[0];
    editor = mountEditor({ image: root.querySelector("#reviewCropImage"), canvas,
      input: root.querySelector("#reviewCropInput"), initialPoints: focused?.cropRect,
      onDraftChange(points) { draft = points; },
    });
  }
  return { handleAction, handleKey, toggle, syncEditor, destroy() { editor?.destroy(); } };
}
