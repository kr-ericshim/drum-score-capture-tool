const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function walkJsFiles(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const nextPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walkJsFiles(nextPath));
      continue;
    }
    if (entry.isFile() && nextPath.endsWith(".js")) {
      files.push(nextPath);
    }
  }

  return files.sort();
}

function read(filePath) {
  return fs.readFileSync(filePath, "utf8");
}

const rendererDir = path.join(__dirname, "..", "renderer-v2");
const indexHtmlPath = path.join(rendererDir, "index.html");
const srcDir = path.join(rendererDir, "src");
const appShellPath = path.join(srcDir, "ui", "shell", "AppShell.js");
const topBarPath = path.join(srcDir, "ui", "shell", "TopBar.js");
const processRailPath = path.join(srcDir, "ui", "shell", "ProcessRail.js");
const contextLanePath = path.join(srcDir, "ui", "shell", "ContextLane.js");
const sourceScreenPath = path.join(srcDir, "features", "source", "SourceScreen.js");
const roiScreenPath = path.join(srcDir, "features", "roi", "RoiScreen.js");
const exportScreenPath = path.join(srcDir, "features", "export", "ExportScreen.js");
const reviewScreenPath = path.join(srcDir, "features", "review", "ReviewScreen.js");
const baseCssPath = path.join(srcDir, "styles", "base.css");
const layoutCssPath = path.join(srcDir, "styles", "layout.css");
const componentsCssPath = path.join(srcDir, "styles", "components.css");
const jsFiles = walkJsFiles(srcDir);

for (const filePath of jsFiles) {
  execFileSync(process.execPath, ["--check", filePath], { stdio: "pipe" });
}

const indexHtml = read(indexHtmlPath);
const appShell = read(appShellPath);
const topBar = read(topBarPath);
const processRail = read(processRailPath);
const contextLane = read(contextLanePath);
const sourceScreen = read(sourceScreenPath);
const roiScreen = read(roiScreenPath);
const exportScreen = read(exportScreenPath);
const reviewScreen = read(reviewScreenPath);
const baseCss = read(baseCssPath);
const layoutCss = read(layoutCssPath);
const componentsCss = read(componentsCssPath);

assert(indexHtml.includes('id="app"'), "renderer-v2 index.html is missing the root app mount.");
assert(indexHtml.includes('./src/main.js'), "renderer-v2 index.html is missing the main module entry.");

assert(appShell.includes('data-shell="renderer-v2"'), "renderer-v2 shell marker is missing.");
assert(appShell.includes('id="topBar"'), "renderer-v2 top bar landmark is missing.");
assert(appShell.includes('id="processRail"'), "renderer-v2 process rail landmark is missing.");
assert(appShell.includes('id="stagePane"'), "renderer-v2 stage pane landmark is missing.");
assert(appShell.includes('id="contextLane"'), "renderer-v2 context lane landmark is missing.");
assert(appShell.includes('id="statusBar"'), "renderer-v2 status bar landmark is missing.");

assert(
  topBar.includes('t("topbar.brandTitle"') || topBar.includes('const BRAND_TITLE = "Drum Sheet Capture"'),
  "renderer-v2 top bar brand identity is missing.",
);
assert(!topBar.includes("Core Workflow v2"), "renderer-v2 still exposes the old generic shell identity.");
assert(!topBar.includes("Local score capture workflow"), "renderer-v2 top bar still hardcodes the old subtitle framing.");
assert(processRail.includes('t("rail.pipeline"') || processRail.includes('const PIPELINE = "Steps"'), "renderer-v2 process rail step heading is missing.");
assert(processRail.includes('data-action="open-step"'), "renderer-v2 process rail step action is missing.");
assert(contextLane.includes('t("lane.sourceSummary"') || contextLane.includes('const SOURCE_SUMMARY = "Source facts"'), "renderer-v2 context lane source summary is missing.");
assert(!processRail.includes("Workflow"), "renderer-v2 process rail still hardcodes generic workflow copy.");
assert(!processRail.includes("System status"), "renderer-v2 process rail still hardcodes generic system-status copy.");
assert(!contextLane.includes("Inspection view"), "renderer-v2 context lane still hardcodes generic inspection-view copy.");
assert(!contextLane.includes("Target Framerate"), "renderer-v2 still exposes fabricated ingest metadata.");

assert(sourceScreen.includes('data-screen="source"'), "source screen marker is missing.");
assert(sourceScreen.includes('data-stitch-region="source-ingest"'), "source screen Stitch ingest region is missing.");
assert(sourceScreen.includes('data-stitch-region="source-registry"'), "source screen Stitch registry region is missing.");
assert(sourceScreen.includes('data-action="select-source-file"'), "source screen primary action is missing.");
assert(roiScreen.includes('data-screen="roi"'), "ROI screen marker is missing.");
assert(roiScreen.includes('data-stitch-region="roi-toolbar"'), "ROI toolbar region is missing.");
assert(roiScreen.includes('data-stitch-region="roi-actions"'), "ROI action region is missing.");
assert(!roiScreen.includes("ROI RECT"), "ROI screen still exposes the removed mode pill.");
assert(roiScreen.includes('data-action="load-preview-frame"'), "ROI preview action is missing.");
assert(roiScreen.includes('data-action="apply-roi"'), "ROI apply action is missing.");
assert(exportScreen.includes('data-screen="export"'), "export screen marker is missing.");
assert(exportScreen.includes('data-stitch-region="export-config"'), "export config workbench region is missing.");
assert(exportScreen.includes('data-stitch-region="export-preview"'), "export preview workbench region is missing.");
assert(exportScreen.includes('data-action="run-export"'), "export run action is missing.");
assert(exportScreen.includes("Processing Profile") || exportScreen.includes('t("export.processingProfile"'), "export processing profile summary is missing.");
assert(exportScreen.includes("ROI Preview") || exportScreen.includes('t("export.previewTitle"'), "export roi preview heading is missing.");
assert(!exportScreen.includes("DISCARD ANALYSIS"), "export screen still exposes a non-functional discard control.");
assert(reviewScreen.includes('data-screen="review"'), "review screen marker is missing.");
assert(reviewScreen.includes('data-stitch-region="review-grid"'), "review grid-first Stitch region is missing.");
assert(!reviewScreen.includes("Add Frame"), "review screen still exposes the non-functional add-frame tile.");
assert(
  reviewScreen.includes('data-action="apply-review"')
    || reviewScreen.includes("검토 반영 완료")
    || reviewScreen.includes('t("review.appliedNote"'),
  "review screen is missing its finalize affordance.",
);
assert(processRail.includes('data-action="open-output-dir"'), "review rail output-folder action is missing.");
assert(processRail.includes('data-action="open-output-pdf"'), "review rail output-pdf action is missing.");

assert(baseCss.includes(":focus-visible"), "renderer-v2 base styles are missing visible focus treatment.");
assert(layoutCss.includes(".workspace-shell"), "renderer-v2 layout is missing the workstation shell grid.");
assert(layoutCss.includes(".status-bar"), "renderer-v2 layout is missing the footer status strip.");
assert(layoutCss.includes(".export-workbench"), "renderer-v2 layout is missing the export workbench split.");
assert(layoutCss.includes(".review-grid"), "renderer-v2 layout is missing the review grid layout.");
assert(componentsCss.includes(".button"), "renderer-v2 component styles are missing button treatment.");
assert(componentsCss.includes(".inline-error"), "renderer-v2 component styles are missing inline error treatment.");
assert(componentsCss.includes(".topbar-brand"), "renderer-v2 component styles are missing Stitch chrome treatment.");
assert(componentsCss.includes(".review-card"), "renderer-v2 component styles are missing review card treatment.");

console.log(`renderer-v2 checks passed (${jsFiles.length} JS modules parsed).`);
