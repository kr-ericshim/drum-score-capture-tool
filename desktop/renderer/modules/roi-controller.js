import { clamp, el, fileUrl, parseJsonOrNull } from "./dom.js";

export function createRoiController({ detectMode, onPreviewLoadError }) {
  let roiCanvas = null;
  let roiContext = null;
  let roiImage = null;
  let roiBoundInitialized = false;
  let roiActive = false;
  let roiRect = null;
  let roiDragMode = null;
  let roiDragStart = null;
  let roiImageLoaded = false;

  function initRoiEditor() {
    if (roiBoundInitialized) {
      return;
    }

    roiCanvas = el("roiCanvas");
    roiImage = el("roiImage");
    if (!roiCanvas || !roiImage) {
      return;
    }
    roiContext = roiCanvas.getContext("2d");
    if (!roiContext) {
      return;
    }

    const getPoint = (event) => getCanvasPoint(event.clientX, event.clientY);

    roiCanvas.addEventListener("pointerdown", (event) => {
      const point = getPoint(event);
      if (!point) {
        return;
      }
      if (roiRect && isInsideRect(point)) {
        roiDragMode = "move";
        roiDragStart = {
          x: point.x - roiRect.x1,
          y: point.y - roiRect.y1,
        };
      } else {
        roiDragMode = "draw";
        roiRect = {
          x1: point.x,
          y1: point.y,
          x2: point.x,
          y2: point.y,
        };
      }

      roiActive = true;
      roiCanvas.setPointerCapture(event.pointerId);
      renderRoi();
    });

    roiCanvas.addEventListener("pointermove", (event) => {
      if (!roiActive) {
        return;
      }
      const point = getPoint(event);
      if (!point) {
        return;
      }
      if (roiDragMode === "draw") {
        roiRect.x2 = point.x;
        roiRect.y2 = point.y;
        renderRoi();
        return;
      }
      if (roiDragMode === "move") {
        const width = Math.abs(roiRect.x2 - roiRect.x1);
        const height = Math.abs(roiRect.y2 - roiRect.y1);
        const x1 = clamp(point.x - roiDragStart.x, 0, roiCanvas.width - width);
        const y1 = clamp(point.y - roiDragStart.y, 0, roiCanvas.height - height);
        roiRect.x1 = x1;
        roiRect.y1 = y1;
        roiRect.x2 = x1 + width;
        roiRect.y2 = y1 + height;
        renderRoi();
      }
    });

    roiCanvas.addEventListener("pointerup", (event) => {
      if (!roiActive) {
        return;
      }
      if (event.pointerId != null) {
        roiCanvas.releasePointerCapture(event.pointerId);
      }
      roiActive = false;
      roiDragMode = null;
      roiDragStart = null;
      if (roiRect) {
        roiRect = normalizeRoiRect(roiRect);
        renderRoi();
        syncInputFromRect();
      }
    });

    roiCanvas.addEventListener("pointerleave", () => {
      if (!roiActive) {
        return;
      }
      roiActive = false;
      roiDragMode = null;
      roiDragStart = null;
      if (roiRect) {
        roiRect = normalizeRoiRect(roiRect);
        renderRoi();
        syncInputFromRect();
      }
    });

    el("applyRoi").addEventListener("click", () => {
      syncInputFromRect();
      const manual = el("detectManual");
      if (manual) {
        manual.checked = true;
      }
    });

    roiBoundInitialized = true;
  }

  function getCanvasPoint(clientX, clientY) {
    if (!roiCanvas) {
      return null;
    }
    const rect = roiCanvas.getBoundingClientRect();
    if (!rect.width || !rect.height || !roiCanvas.width || !roiCanvas.height) {
      return null;
    }
    return {
      x: clamp((clientX - rect.left) * (roiCanvas.width / rect.width), 0, roiCanvas.width),
      y: clamp((clientY - rect.top) * (roiCanvas.height / rect.height), 0, roiCanvas.height),
    };
  }

  function isInsideRect(point) {
    if (!roiRect) {
      return false;
    }
    return (
      point.x >= roiRect.x1 &&
      point.x <= roiRect.x2 &&
      point.y >= roiRect.y1 &&
      point.y <= roiRect.y2
    );
  }

  function normalizeRoiRect(rawRect) {
    return {
      x1: Math.round(clamp(Math.min(rawRect.x1, rawRect.x2), 0, roiCanvas.width)),
      y1: Math.round(clamp(Math.min(rawRect.y1, rawRect.y2), 0, roiCanvas.height)),
      x2: Math.round(clamp(Math.max(rawRect.x1, rawRect.x2), 0, roiCanvas.width)),
      y2: Math.round(clamp(Math.max(rawRect.y1, rawRect.y2), 0, roiCanvas.height)),
    };
  }

  function rectToPoints(rect) {
    return [
      [Math.round(rect.x1), Math.round(rect.y1)],
      [Math.round(rect.x2), Math.round(rect.y1)],
      [Math.round(rect.x2), Math.round(rect.y2)],
      [Math.round(rect.x1), Math.round(rect.y2)],
    ];
  }

  function syncInputFromRect() {
    if (!roiRect) {
      return;
    }
    const normalized = normalizeRoiRect(roiRect);
    el("roiInput").value = JSON.stringify(rectToPoints(normalized));
  }

  function clearRoiCanvas() {
    if (!roiCanvas || !roiContext) {
      return;
    }
    roiContext.clearRect(0, 0, roiCanvas.width, roiCanvas.height);
  }

  function clearRoiState() {
    roiRect = null;
    roiActive = false;
    roiDragMode = null;
    roiDragStart = null;
  }

  function clearRoiImageState() {
    if (!roiImage) {
      return;
    }
    roiImage.onload = null;
    roiImage.onerror = null;
    roiImage.removeAttribute("src");
  }

  function renderRoi() {
    if (!roiCanvas || !roiContext) {
      return;
    }
    roiContext.clearRect(0, 0, roiCanvas.width, roiCanvas.height);
    if (!roiRect) {
      return;
    }

    const normalized = normalizeRoiRect(roiRect);
    roiRect = normalized;
    roiContext.strokeStyle = "#00c8a2";
    roiContext.lineWidth = 3;
    roiContext.strokeRect(
      normalized.x1 + 0.5,
      normalized.y1 + 0.5,
      normalized.x2 - normalized.x1,
      normalized.y2 - normalized.y1,
    );
    roiContext.fillStyle = "rgba(0, 200, 162, 0.14)";
    roiContext.fillRect(normalized.x1, normalized.y1, normalized.x2 - normalized.x1, normalized.y2 - normalized.y1);
  }

  function renderManualRoiFromInput() {
    if (detectMode() !== "manual" || !roiCanvas) {
      return false;
    }
    const parsed = parseJsonOrNull(el("roiInput").value);
    if (!Array.isArray(parsed) || parsed.length !== 4) {
      return false;
    }

    const xs = parsed.map((item) => Number(item[0]));
    const ys = parsed.map((item) => Number(item[1]));
    if (
      xs.some((value) => !Number.isFinite(value)) ||
      ys.some((value) => !Number.isFinite(value)) ||
      roiCanvas.width <= 0 ||
      roiCanvas.height <= 0
    ) {
      return false;
    }

    roiRect = {
      x1: clamp(Math.min(...xs), 0, roiCanvas.width),
      y1: clamp(Math.min(...ys), 0, roiCanvas.height),
      x2: clamp(Math.max(...xs), 0, roiCanvas.width),
      y2: clamp(Math.max(...ys), 0, roiCanvas.height),
    };
    renderRoi();
    return true;
  }

  function applyFallbackRoi() {
    const width = Math.max(1, roiCanvas?.width || 0, roiImage?.naturalWidth || 0, 1);
    const height = Math.max(1, roiCanvas?.height || 0, roiImage?.naturalHeight || 0, 1);
    const marginX = Math.round(width * 0.1);
    const marginY = Math.round(height * 0.1);
    roiRect = {
      x1: marginX,
      y1: marginY,
      x2: Math.max(marginX + 1, width - marginX),
      y2: Math.max(marginY + 1, height - marginY),
    };
    renderRoi();
    syncInputFromRect();
  }

  function setRoiEditorVisibility(visible) {
    const wrapper = el("roiEditorWrap");
    if (wrapper) {
      wrapper.style.display = visible ? "block" : "none";
    }
    if (!visible) {
      clearRoiCanvas();
    }
  }

  function setRoiEditMode(visible) {
    const applyButton = el("applyRoi");
    const helpText = document.querySelector(".roi-help");
    if (roiCanvas) {
      roiCanvas.style.display = visible ? "block" : "none";
      roiCanvas.style.pointerEvents = visible ? "auto" : "none";
    }
    if (applyButton) {
      applyButton.style.display = visible ? "inline-block" : "none";
    }
    if (helpText) {
      helpText.style.display = visible ? "block" : "none";
    }
    if (!visible) {
      clearRoiCanvas();
    }
  }

  function resolvePreviewSrc(rawPath) {
    const value = String(rawPath || "").trim();
    if (!value) {
      return "";
    }
    if (value.startsWith("http://") || value.startsWith("https://") || value.startsWith("file://") || value.startsWith("data:")) {
      return value;
    }
    return fileUrl(value);
  }

  function showPreviewWithRoi(imagePath) {
    if (!imagePath) {
      return;
    }
    initRoiEditor();
    if (!roiCanvas || !roiImage) {
      return;
    }

    const manualMode = detectMode() === "manual";
    setRoiEditorVisibility(true);
    setRoiEditMode(manualMode);

    clearRoiState();
    clearRoiCanvas();
    roiImageLoaded = false;
    roiImage.onload = null;
    roiImage.onerror = null;
    roiImage.onload = () => {
      roiImageLoaded = true;
      if (roiCanvas.width !== roiImage.naturalWidth || roiCanvas.height !== roiImage.naturalHeight) {
        roiCanvas.width = roiImage.naturalWidth;
        roiCanvas.height = roiImage.naturalHeight;
        clearRoiCanvas();
      }

      const applied = detectMode() === "manual" && renderManualRoiFromInput();
      if (!applied) {
        applyFallbackRoi();
        return;
      }

      roiRect = normalizeRoiRect(roiRect);
      renderRoi();
    };
    roiImage.onerror = () => {
      roiImageLoaded = false;
      clearRoiCanvas();
      if (typeof onPreviewLoadError === "function") {
        onPreviewLoadError(imagePath);
      }
    };
    roiImage.src = resolvePreviewSrc(imagePath);
  }

  function hasResultImage() {
    return Boolean(roiImage?.getAttribute("src"));
  }

  function isImageReady() {
    return roiImageLoaded;
  }

  function clearPreview() {
    clearRoiState();
    clearRoiCanvas();
    clearRoiImageState();
    roiImageLoaded = false;
    setRoiEditorVisibility(false);
    setRoiEditMode(false);
  }

  function onDetectModeChange() {
    const isManual = detectMode() === "manual";
    const hasImage = hasResultImage();
    setRoiEditMode(isManual && hasImage);
    if (isManual && hasImage && isImageReady()) {
      const applied = renderManualRoiFromInput();
      if (!applied) {
        applyFallbackRoi();
      }
    }
  }

  function onRoiInputChange() {
    const isManual = detectMode() === "manual";
    const hasImage = hasResultImage();
    if (!isManual || !hasImage || !isImageReady()) {
      return;
    }
    const applied = renderManualRoiFromInput();
    if (!applied) {
      applyFallbackRoi();
    }
  }

  return {
    showPreviewWithRoi,
    setRoiEditorVisibility,
    setRoiEditMode,
    clearPreview,
    onDetectModeChange,
    onRoiInputChange,
    hasResultImage,
  };
}
