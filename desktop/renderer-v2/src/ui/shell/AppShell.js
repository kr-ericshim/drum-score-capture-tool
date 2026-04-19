export function mountShell(root) {
  root.innerHTML = `
    <main class="app-shell" data-shell="renderer-v2">
      <header id="topBar" class="topbar"></header>
      <section id="workspaceShell" class="workspace-shell">
        <aside id="processRail" class="process-rail" aria-label=""></aside>
        <section id="stagePane" class="stage-pane" tabindex="-1" role="region" aria-label=""></section>
        <aside id="contextLane" class="context-lane" aria-label=""></aside>
      </section>
      <footer id="statusBar" class="status-bar" role="status" aria-live="polite"></footer>
      <div id="shellModalLayer" class="shell-modal-layer"></div>
    </main>
  `;

  return {
    appShell: root.querySelector('[data-shell="renderer-v2"]'),
    topBar: root.querySelector("#topBar"),
    workspaceShell: root.querySelector("#workspaceShell"),
    processRail: root.querySelector("#processRail"),
    stagePane: root.querySelector("#stagePane"),
    contextLane: root.querySelector("#contextLane"),
    statusBar: root.querySelector("#statusBar"),
    modalLayer: root.querySelector("#shellModalLayer"),
  };
}
