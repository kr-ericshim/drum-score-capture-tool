import { APP_REVIEW_CODES, reviewListPages } from "../../app/session/selectors.js";
import { normalizeAssetPath } from "../../lib/paths.js";
import { describeError } from "../../lib/i18n.js";

const HYPOTHESIS_PAGE = 100;

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
    // Clean reflow: the list order is the output order, so undo covers it too.
    order: state.review.pages.map(page => page.id),
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
    if (Array.isArray(target.order) && target.order.length === pages.length) {
      pages.sort((a, b) => target.order.indexOf(a.id) - target.order.indexOf(b.id));
    }
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
        next.review.status = "error"; next.review.error = describeError(error, next.ui?.locale || "en"); return next;
      });
      return false;
    }
  }
  // One page of ledger hypotheses for the current job and revision; a stale answer is dropped.
  async function loadHypotheses(offset) {
    const state = getState();
    const key = { jobId: state.exportConfig.jobId, revision: state.review.jobRevision };
    setState(next => { next.review.hypotheses.status = "loading"; next.review.hypotheses.error = ""; return next; });
    try {
      if (typeof api.getReviewHypotheses !== "function") throw new Error("");
      const page = await api.getReviewHypotheses(key.jobId, { offset, limit: HYPOTHESIS_PAGE, codes: [...APP_REVIEW_CODES] });
      const now = getState();
      if (now.exportConfig.jobId !== key.jobId || now.review.jobRevision !== key.revision) return;
      setState(next => {
        const items = offset ? [...next.review.hypotheses.items, ...page.items] : page.items;
        next.review.hypotheses = { ...next.review.hypotheses, ...key, status: "ready", items, counts: page.counts,
          total: page.total, ledgerStatus: page.status, error: "" };
        return next;
      });
    } catch (error) {
      if (getState().exportConfig.jobId !== key.jobId) return;
      setState(next => {
        next.review.hypotheses.status = "error";
        next.review.hypotheses.error = error?.message ? describeError(error, next.ui?.locale || "en") : "";
        return next;
      });
    }
  }
  async function handleAction(action, value) {
    syncJob();
    const state = getState();
    if (["running", "editing"].includes(state.review.status)) return;
    if (action === "review-hypotheses") {
      const hyp = state.review.hypotheses;
      if (hyp.open) { setState(next => { next.review.hypotheses.open = false; return next; }); return; }
      const fresh = hyp.jobId === state.exportConfig.jobId && hyp.revision === state.review.jobRevision && hyp.status === "ready";
      setState(next => {
        next.review.hypotheses.open = true;
        next.review.pagePreview = false; next.review.compare = false; next.review.cropping = false;
        return next;
      });
      if (!fresh) await loadHypotheses(0);
      return;
    }
    if (action === "review-hypotheses-retry") { await loadHypotheses(0); return; }
    if (action === "review-hypotheses-more") { await loadHypotheses(state.review.hypotheses.items.length); return; }
    const pages = reviewListPages(state.review).navigable;
    const focused = pages.find(page => page.id === state.review.focusedPageId) || pages[0];
    if (action === "review-toggle-focused" && focused) { toggle(focused.id, !state.review.selectedPageIds.includes(focused.id)); return; }
    // One click: a system that looks similar leaves the output; undo brings it back.
    if (action === "review-remove-duplicate" && focused?.similarTo?.reason === "looks_similar") { toggle(focused.id, false); return; }
    if ((action === "review-move-up" || action === "review-move-down") && focused?.kind === "system") {
      const all = state.review.pages;
      const index = all.findIndex(page => page.id === focused.id);
      const target = index + (action === "review-move-up" ? -1 : 1);
      if (index < 0 || target < 0 || target >= all.length) return;
      remember();
      setState(next => {
        const moved = [...next.review.pages];
        [moved[index], moved[target]] = [moved[target], moved[index]];
        next.review.pages = moved;
        return mark(next);
      });
      return;
    }
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
        const filtered = reviewListPages(next.review).navigable;
        if (!filtered.some(page => page.id === next.review.focusedPageId)) next.review.focusedPageId = filtered[0]?.id || "";
        next.review.cropping = false;
      }
      if (action === "review-toggle-alternates") {
        next.review.alternatesExpanded = !next.review.alternatesExpanded;
        const shown = reviewListPages(next.review).navigable;
        if (!shown.some(page => page.id === next.review.focusedPageId)) next.review.focusedPageId = shown[0]?.id || "";
      }
      if (action === "review-toggle-fragments") {
        next.review.fragmentsExpanded = !next.review.fragmentsExpanded;
        // a fragment that is no longer shown is not the viewed item
        const shown = reviewListPages(next.review).navigable;
        if (!shown.some(page => page.id === next.review.focusedPageId)) next.review.focusedPageId = shown[0]?.id || "";
      }
      // From a hypothesis to its system: the list shows it (all filter, its group open) and the viewer focuses it.
      if (action === "review-hypothesis-system" && next.review.pages.some(page => page.id === value)) {
        next.review.hypotheses.open = false;
        next.review.filter = "all";
        if (reviewListPages(next.review).alternates.some(page => page.id === value)) next.review.alternatesExpanded = true;
        if (reviewListPages(next.review).fragments.some(page => page.id === value)) next.review.fragmentsExpanded = true;
        next.review.focusedPageId = value;
      }
      if (action === "review-compare") next.review.compare = !next.review.compare;
      if (action === "review-page-preview") {
        next.review.pagePreview = !next.review.pagePreview && next.review.outputPages.length > 0;
        if (next.review.pagePreview) { next.review.compare = false; next.review.cropping = false; next.review.hypotheses.open = false; }
      }
      if (action === "review-crop") { next.review.cropping = true; next.review.compare = false; next.review.hypotheses.open = false; }
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
    if (event.key === "Escape" && state.review.hypotheses?.open) action = "review-hypotheses";
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
