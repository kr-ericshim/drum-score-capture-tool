import test from "node:test";
import assert from "node:assert/strict";

import { mountRoiEditor } from "../features/roi/roiEditor.js";

function createEventTarget() {
  const listeners = new Map();
  return {
    style: {},
    listeners,
    dataset: {},
    addEventListener(type, handler) {
      if (!listeners.has(type)) {
        listeners.set(type, []);
      }
      listeners.get(type).push(handler);
    },
    dispatch(type, event = {}) {
      for (const handler of listeners.get(type) || []) {
        handler({
          preventDefault() {},
          ...event,
        });
      }
    },
    setAttribute(name, value) {
      this[name] = value;
    },
    focus() {
      this.focused = true;
    },
  };
}

function createCanvas({ width = 1000, height = 1000, displayWidth = width, displayHeight = height } = {}) {
  const canvas = createEventTarget();
  canvas.width = width;
  canvas.height = height;
  canvas.getContext = () => ({
    clearRect() {},
    strokeRect() {},
    fillRect() {},
  });
  canvas.getBoundingClientRect = () => ({
    left: 0,
    top: 0,
    width: displayWidth,
    height: displayHeight,
  });
  canvas.setPointerCapture = () => {};
  canvas.releasePointerCapture = () => {};
  return canvas;
}

function createImage(width = 1000, height = 1000) {
  return {
    complete: true,
    naturalWidth: width,
    naturalHeight: height,
    addEventListener() {},
  };
}

test("roi editor supports keyboard nudging for the current roi selection", () => {
  const image = createImage();
  const canvas = createCanvas();
  const input = { value: "" };
  const editor = mountRoiEditor({
    image,
    canvas,
    input,
    initialPoints: [[100, 100], [300, 100], [300, 300], [100, 300]],
  });

  canvas.dispatch("keydown", { key: "ArrowRight" });
  canvas.dispatch("keydown", { key: "ArrowDown", shiftKey: true });

  assert.deepEqual(editor.applyDraft(), [[101, 110], [301, 110], [301, 310], [101, 310]]);
});

test("roi editor starts new selections on the bottom score strip", () => {
  const image = createImage(1920, 1080);
  const canvas = createCanvas({ width: 1920, height: 1080 });
  const input = { value: "" };
  const editor = mountRoiEditor({
    image,
    canvas,
    input,
    initialPoints: null,
  });

  const expected = [[77, 799], [1843, 799], [1843, 1058], [77, 1058]];

  assert.deepEqual(editor.applyDraft(), expected);
  assert.equal(input.value, JSON.stringify(expected));
});

test("roi editor enlarges handle hit targets when the preview is visually downscaled", () => {
  const image = createImage();
  const canvas = createCanvas({ width: 1000, height: 1000, displayWidth: 250, displayHeight: 250 });
  const input = { value: "" };
  const editor = mountRoiEditor({
    image,
    canvas,
    input,
    initialPoints: [[100, 100], [900, 100], [900, 900], [100, 900]],
  });

  canvas.dispatch("pointerdown", {
    clientX: 35,
    clientY: 35,
    pointerId: 1,
  });
  canvas.dispatch("pointermove", {
    clientX: 45,
    clientY: 45,
    pointerId: 1,
  });
  canvas.dispatch("pointerup", {
    clientX: 45,
    clientY: 45,
    pointerId: 1,
  });

  assert.deepEqual(editor.applyDraft(), [[180, 180], [900, 180], [900, 900], [180, 900]]);
});
