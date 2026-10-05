// Motion follows workflow transitions, not DOM replacement or job polling.
export function createWorkspaceMotion(root, shell) {
  const media = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)');
  const active = new Set();
  const departures = new Set();
  let keyboard = false;
  const stop = () => {
    for (const animation of active) animation.cancel();
    active.clear();
    for (const node of departures) node.remove();
    departures.clear();
  };
  const onKeyboard = () => { keyboard = true; stop(); };
  const onPointer = () => { keyboard = false; };
  const onPreference = () => { if (media.matches) stop(); };
  root.addEventListener('keydown', onKeyboard, true);
  root.addEventListener('pointerdown', onPointer, true);
  media?.addEventListener?.('change', onPreference);

  function play(element, frames, durationToken = '--dur-enter') {
    if (!element?.animate || keyboard || media?.matches) return null;
    const style = globalThis.getComputedStyle(shell.appShell);
    const animation = element.animate(frames, {
      duration: Number.parseFloat(style.getPropertyValue(durationToken)),
      easing: style.getPropertyValue('--ease-out').trim(),
    });
    active.add(animation);
    animation.finished.then(() => active.delete(animation), () => active.delete(animation));
    return animation;
  }

  return {
    step() {
      // Leave backgrounds and the score still; transform only panel contents.
      const selectors = '.screen-headline > :not(.screen-inline-actions), .source-ingest > *, .roi-controls > *, .export-config-stack > *, .review-grid-shell > :not(.review-grid)';
      for (const node of shell.stagePane.querySelectorAll?.(selectors) || []) {
        play(node, [{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'translateY(0)' }]);
      }
    },
    enter(overlay) {
      if (!overlay) return;
      play(overlay, [{ opacity: 0 }, { opacity: 1 }]);
      play(overlay.querySelector?.('.archive-modal, .export-metadata-modal'), [
        { transform: 'translateY(6px) scale(0.985)' }, { transform: 'translateY(0) scale(1)' },
      ]);
    },
    leave(overlay) {
      if (!overlay?.cloneNode || keyboard || media?.matches || !overlay.animate) return;
      // A visual-only copy must never keep a dialog active or delay focus restoration.
      const host = root.ownerDocument.createElement('div');
      host.className = 'motion-departure';
      host.inert = true;
      host.setAttribute('aria-hidden', 'true');
      const copy = overlay.cloneNode(true);
      for (const node of [copy, ...copy.querySelectorAll('*')]) {
        for (const name of [...node.getAttributeNames()]) {
          if (name === 'id' || name === 'name' || name === 'autofocus' || name === 'role' || name.startsWith('aria-') || name.startsWith('data-')) node.removeAttribute(name);
        }
      }
      host.append(copy);
      shell.appShell.append(host);
      departures.add(host);
      const animation = play(host, [{ opacity: 1 }, { opacity: 0 }], '--dur-press');
      const remove = () => { host.remove(); departures.delete(host); };
      if (animation) animation.finished.then(remove, remove);
      else remove();
    },
    destroy() {
      stop();
      root.removeEventListener?.('keydown', onKeyboard, true);
      root.removeEventListener?.('pointerdown', onPointer, true);
      media?.removeEventListener?.('change', onPreference);
    },
  };
}
