function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function isValidRect(rect) {
  return Array.isArray(rect) && rect.length === 4;
}

function pointsToRect(points, width, height) {
  const xs = points.map((point) => Number(point[0]));
  const ys = points.map((point) => Number(point[1]));
  return {
    x1: clamp(Math.min(...xs), 0, width),
    y1: clamp(Math.min(...ys), 0, height),
    x2: clamp(Math.max(...xs), 0, width),
    y2: clamp(Math.max(...ys), 0, height),
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

function normalize(rect, width, height) {
  return {
    x1: Math.round(clamp(Math.min(rect.x1, rect.x2), 0, width)),
    y1: Math.round(clamp(Math.min(rect.y1, rect.y2), 0, height)),
    x2: Math.round(clamp(Math.max(rect.x1, rect.x2), 0, width)),
    y2: Math.round(clamp(Math.max(rect.y1, rect.y2), 0, height)),
  };
}

export function mountRoiEditor({ image, canvas, input, initialPoints = null, onDraftChange }) {
  if (!image || !canvas || !input) {
    return {
      applyDraft() {
        return null;
      },
      destroy() {},
    };
  }

  const ctx = canvas.getContext("2d");
  const abort = new AbortController();
  const MIN_KEYBOARD_STEP = 1;
  const FAST_KEYBOARD_STEP = 10;
  let rect = null;
  let dragMode = "";
  let dragOffset = null;
  let keyboardMode = "move";

  function getCanvasPoint(clientX, clientY) {
    const bounds = canvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) {
      return null;
    }
    return {
      x: clamp((clientX - bounds.left) * (canvas.width / bounds.width), 0, canvas.width),
      y: clamp((clientY - bounds.top) * (canvas.height / bounds.height), 0, canvas.height),
    };
  }

  function getDisplayScale() {
    const bounds = canvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height || !canvas.width || !canvas.height) {
      return 1;
    }
    return Math.max(canvas.width / bounds.width, canvas.height / bounds.height);
  }

  function getHandleSize() {
    return clamp(Math.round(12 * getDisplayScale()), 10, 48);
  }

  function handlesFor(current) {
    return {
      nw: { x: current.x1, y: current.y1 },
      ne: { x: current.x2, y: current.y1 },
      se: { x: current.x2, y: current.y2 },
      sw: { x: current.x1, y: current.y2 },
    };
  }

  function handleAt(point) {
    if (!rect) {
      return "";
    }
    const handleSize = getHandleSize();
    const handles = handlesFor(rect);
    return Object.entries(handles).find(([, handle]) => {
      return Math.abs(point.x - handle.x) <= handleSize && Math.abs(point.y - handle.y) <= handleSize;
    })?.[0] || "";
  }

  function inside(point) {
    return rect && point.x >= rect.x1 && point.x <= rect.x2 && point.y >= rect.y1 && point.y <= rect.y2;
  }

  function setCursor(point) {
    if (!canvas?.style) {
      return;
    }
    if (!point) {
      canvas.style.cursor = "crosshair";
      return;
    }
    const handle = handleAt(point);
    if (handle) {
      canvas.style.cursor = handle === "nw" || handle === "se" ? "nwse-resize" : "nesw-resize";
      return;
    }
    canvas.style.cursor = inside(point) ? "move" : "crosshair";
  }

  function syncA11yState() {
    if (typeof canvas?.setAttribute !== "function") {
      return;
    }
    canvas.setAttribute("data-roi-keyboard-mode", keyboardMode);
    canvas.setAttribute("aria-keyshortcuts", "ArrowLeft ArrowRight ArrowUp ArrowDown Shift+ArrowLeft Shift+ArrowRight Shift+ArrowUp Shift+ArrowDown 0 1 2 3 4");
  }

  function moveRect(deltaX, deltaY) {
    const normalized = normalize(rect, canvas.width, canvas.height);
    const width = normalized.x2 - normalized.x1;
    const height = normalized.y2 - normalized.y1;
    normalized.x1 = clamp(normalized.x1 + deltaX, 0, canvas.width - width);
    normalized.y1 = clamp(normalized.y1 + deltaY, 0, canvas.height - height);
    normalized.x2 = normalized.x1 + width;
    normalized.y2 = normalized.y1 + height;
    rect = normalized;
  }

  function resizeRect(handle, deltaX, deltaY) {
    const normalized = normalize(rect, canvas.width, canvas.height);
    if (handle.includes("n")) normalized.y1 = clamp(normalized.y1 + deltaY, 0, normalized.y2 - 1);
    if (handle.includes("s")) normalized.y2 = clamp(normalized.y2 + deltaY, normalized.y1 + 1, canvas.height);
    if (handle.includes("w")) normalized.x1 = clamp(normalized.x1 + deltaX, 0, normalized.x2 - 1);
    if (handle.includes("e")) normalized.x2 = clamp(normalized.x2 + deltaX, normalized.x1 + 1, canvas.width);
    rect = normalized;
  }

  function paint() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!rect) {
      return;
    }
    const normalized = normalize(rect, canvas.width, canvas.height);
    const handleSize = getHandleSize();
    rect = normalized;
    ctx.strokeStyle = "#d0a95e";
    ctx.lineWidth = 3;
    ctx.fillStyle = "rgba(208, 169, 94, 0.18)";
    ctx.strokeRect(normalized.x1 + 0.5, normalized.y1 + 0.5, normalized.x2 - normalized.x1, normalized.y2 - normalized.y1);
    ctx.fillRect(normalized.x1, normalized.y1, normalized.x2 - normalized.x1, normalized.y2 - normalized.y1);
    ctx.fillStyle = "#d0a95e";
    for (const [handle, point] of Object.entries(handlesFor(normalized))) {
      ctx.fillRect(point.x - handleSize / 2, point.y - handleSize / 2, handleSize, handleSize);
      if (keyboardMode === handle) {
        ctx.strokeRect(point.x - handleSize * 0.75, point.y - handleSize * 0.75, handleSize * 1.5, handleSize * 1.5);
      }
    }
  }

  function emit() {
    if (!rect) {
      return;
    }
    const points = rectToPoints(normalize(rect, canvas.width, canvas.height));
    input.value = JSON.stringify(points);
    if (typeof onDraftChange === "function") {
      onDraftChange(points);
    }
  }

  function setRect(nextPoints, emitChange = true) {
    if (!isValidRect(nextPoints)) {
      rect = {
        x1: Math.round(canvas.width * 0.1),
        y1: Math.round(canvas.height * 0.1),
        x2: Math.round(canvas.width * 0.9),
        y2: Math.round(canvas.height * 0.9),
      };
    } else {
      rect = pointsToRect(nextPoints, canvas.width, canvas.height);
    }
    syncA11yState();
    paint();
    if (emitChange) {
      emit();
    }
  }

  canvas.addEventListener("pointerdown", (event) => {
    const point = getCanvasPoint(event.clientX, event.clientY);
    if (!point) {
      return;
    }
    const handle = handleAt(point);
    if (handle) {
      dragMode = `resize:${handle}`;
      keyboardMode = handle;
    } else if (inside(point)) {
      dragMode = "move";
      keyboardMode = "move";
      dragOffset = { x: point.x - rect.x1, y: point.y - rect.y1 };
    } else {
      dragMode = "draw";
      keyboardMode = "move";
      rect = { x1: point.x, y1: point.y, x2: point.x, y2: point.y };
    }
    canvas.focus?.();
    canvas.setPointerCapture(event.pointerId);
    paint();
  }, { signal: abort.signal });

  canvas.addEventListener("pointermove", (event) => {
    const point = getCanvasPoint(event.clientX, event.clientY);
    setCursor(point);
    if (!point || !dragMode) {
      return;
    }
    if (dragMode === "draw") {
      rect.x2 = point.x;
      rect.y2 = point.y;
    } else if (dragMode === "move") {
      const normalized = normalize(rect, canvas.width, canvas.height);
      const width = normalized.x2 - normalized.x1;
      const height = normalized.y2 - normalized.y1;
      normalized.x1 = clamp(point.x - dragOffset.x, 0, canvas.width - width);
      normalized.y1 = clamp(point.y - dragOffset.y, 0, canvas.height - height);
      normalized.x2 = normalized.x1 + width;
      normalized.y2 = normalized.y1 + height;
      rect = normalized;
    } else if (dragMode.startsWith("resize:")) {
      const handle = dragMode.split(":")[1];
      const normalized = normalize(rect, canvas.width, canvas.height);
      if (handle.includes("n")) normalized.y1 = clamp(point.y, 0, normalized.y2 - 1);
      if (handle.includes("s")) normalized.y2 = clamp(point.y, normalized.y1 + 1, canvas.height);
      if (handle.includes("w")) normalized.x1 = clamp(point.x, 0, normalized.x2 - 1);
      if (handle.includes("e")) normalized.x2 = clamp(point.x, normalized.x1 + 1, canvas.width);
      rect = normalized;
    }
    paint();
  }, { signal: abort.signal });

  canvas.addEventListener("pointerleave", () => {
    setCursor(null);
  }, { signal: abort.signal });

  canvas.addEventListener("pointerup", (event) => {
    if (dragMode) {
      canvas.releasePointerCapture(event.pointerId);
      dragMode = "";
      dragOffset = null;
      paint();
      emit();
    }
  }, { signal: abort.signal });

  canvas.addEventListener("keydown", (event) => {
    if (!rect) {
      return;
    }
    const key = String(event.key || "");
    const handleKeyMap = {
      "0": "move",
      "1": "nw",
      "2": "ne",
      "3": "se",
      "4": "sw",
    };
    if (handleKeyMap[key]) {
      keyboardMode = handleKeyMap[key];
      syncA11yState();
      paint();
      event.preventDefault?.();
      return;
    }
    const delta = { x: 0, y: 0 };
    const step = event.shiftKey ? FAST_KEYBOARD_STEP : MIN_KEYBOARD_STEP;
    if (key === "ArrowLeft") delta.x = -step;
    if (key === "ArrowRight") delta.x = step;
    if (key === "ArrowUp") delta.y = -step;
    if (key === "ArrowDown") delta.y = step;
    if (!delta.x && !delta.y) {
      return;
    }
    if (keyboardMode === "move") {
      moveRect(delta.x, delta.y);
    } else {
      resizeRect(keyboardMode, delta.x, delta.y);
    }
    syncA11yState();
    paint();
    emit();
    event.preventDefault?.();
  }, { signal: abort.signal });

  if (image.complete && image.naturalWidth && image.naturalHeight) {
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    setRect(initialPoints);
  } else {
    image.addEventListener("load", () => {
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      setRect(initialPoints);
    }, { signal: abort.signal, once: true });
  }

  return {
    applyDraft() {
      if (!rect) {
        return null;
      }
      return rectToPoints(normalize(rect, canvas.width, canvas.height));
    },
    setDraft(nextPoints) {
      if (!canvas.width || !canvas.height || !isValidRect(nextPoints)) {
        return;
      }
      const currentPoints = rect ? rectToPoints(normalize(rect, canvas.width, canvas.height)) : null;
      if (JSON.stringify(currentPoints) === JSON.stringify(nextPoints)) {
        return;
      }
      setRect(nextPoints, false);
      input.value = JSON.stringify(nextPoints);
      syncA11yState();
    },
    destroy() {
      abort.abort();
    },
  };
}
