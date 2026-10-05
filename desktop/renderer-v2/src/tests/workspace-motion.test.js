import test from 'node:test';
import assert from 'node:assert/strict';
import { createWorkspaceMotion } from '../ui/shell/workspaceMotion.js';

function fixture(t) {
  const listeners = new Map();
  const calls = [];
  let cancelled = 0;
  const media = { matches: false, addEventListener: (_, fn) => { media.change = fn; }, removeEventListener: () => {} };
  t.mock.method(globalThis, 'getComputedStyle', () => ({ getPropertyValue: key => key === '--ease-out' ? 'cubic-bezier(0.23, 1, 0.32, 1)' : '180ms' }));
  t.mock.method(globalThis, 'matchMedia', () => media);
  const node = { animate(frames, options) {
    calls.push({ frames, options });
    return { finished: new Promise(() => {}), cancel() { cancelled++; } };
  } };
  const root = { addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name) };
  const shell = { appShell: {}, stagePane: { querySelectorAll: () => [node] } };
  const motion = createWorkspaceMotion(root, shell);
  return { motion, node, listeners, calls, media, cancelled: () => cancelled };
}
// Browser APIs are optional in the existing Node renderer harness.
globalThis.getComputedStyle ??= () => {};
globalThis.matchMedia ??= () => {};

test('workflow motion cancels on keyboard input and resumes only after pointer input', t => {
  const f = fixture(t);
  f.motion.step();
  assert.equal(f.calls.length, 1);
  assert.equal(f.calls[0].options.duration, 180);
  f.listeners.get('keydown')();
  assert.equal(f.cancelled(), 1);
  f.motion.step();
  assert.equal(f.calls.length, 1);
  f.listeners.get('pointerdown')();
  f.motion.step();
  assert.equal(f.calls.length, 2);
  f.motion.destroy();
  assert.equal(f.cancelled(), 2);
  assert.equal(f.listeners.size, 0);
});

test('changing reduced motion cancels running transitions and prevents new dialog entry', t => {
  const f = fixture(t);
  f.motion.enter({ ...f.node, querySelector: () => f.node });
  assert.equal(f.calls.length, 2);
  f.media.matches = true;
  f.media.change();
  assert.equal(f.cancelled(), 2);
  f.motion.step();
  f.motion.enter({ ...f.node, querySelector: () => f.node });
  assert.equal(f.calls.length, 2);
  f.motion.destroy();
});
