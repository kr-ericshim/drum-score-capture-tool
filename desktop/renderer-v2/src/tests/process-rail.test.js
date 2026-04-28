import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createInitialSessionState, getProcessRailItems } from "../app/session/selectors.js";
import { renderContextLane } from "../ui/shell/ContextLane.js";
import { renderProcessRail } from "../ui/shell/ProcessRail.js";
import { renderTopBar } from "../ui/shell/TopBar.js";

test("roi rail drops the workbench footer and keeps only the step guidance", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.ui.activeStep = "roi";
  state.source.filePath = "/tmp/video.mp4";

  const markup = renderProcessRail(state, getProcessRailItems(state));

  assert.doesNotMatch(markup, /WORKBENCH STATUS|Ready now|지금 준비된 항목|준비 상태/);
  assert.match(markup, /대표 프레임을 불러온 뒤 ROI를 잡고 다음으로/);
});

test("review rail footer renders output paths in a dedicated wrapping block", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.ui.activeStep = "review";
  state.exportConfig.formats = ["png", "pdf"];
  state.review.outputDir = "/Users/ericshim/Documents/myproject/score_capture_program/backend/jobs/1aadbac1-e23b-471f-ad06-a554f290c9f5/export";
  state.review.selectedPageIds = ["1"];

  const markup = renderProcessRail(state, getProcessRailItems(state));

  assert.match(markup, /rail-path-block/);
  assert.match(markup, /data-path-kind="output-dir"/);
  assert.doesNotMatch(markup, /<span>OUTPUT<\/span>\s*<strong>\/Users\/ericshim/);
  assert.match(markup, />Open PDF</);
});

test("process rail exposes the current step with aria-current", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.ui.activeStep = "export";
  state.source.filePath = "/tmp/video.mp4";
  state.source.metadata = { durationSec: 120 };
  state.roi.frameTime = 5;
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];

  const markup = renderProcessRail(state, getProcessRailItems(state));

  assert.match(markup, /data-step="export" aria-current="step"/);
});

test("context lane uses definition-list semantics for fact groups and escapes dynamic source text", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.ui.activeStep = "source";
  state.source.filePath = "/tmp/<unsafe>&/capture.mp4";
  state.source.displayName = "<img src=x onerror=alert(1)>";
  state.source.metadata = {
    resolutionLabel: "1920x1080",
    durationLabel: "01:24",
  };

  const markup = renderContextLane(state);

  assert.match(markup, /<dl class="inspector-grid">/);
  assert.match(markup, /<dl class="inspector-list">/);
  assert.match(markup, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(markup, /\/tmp\/&lt;unsafe&gt;&amp;/);
  assert.doesNotMatch(markup, /<strong><img/);
});

test("shell renderers escape dynamic summaries and path text before injecting HTML", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.ui.activeStep = "review";
  state.review.outputDir = "/tmp/<review>&\"'output";
  state.review.selectedPageIds = ["1"];

  const items = getProcessRailItems(state).map((item) => (
    item.id === "review"
      ? { ...item, summary: "<strong>unsafe & summary</strong>" }
      : item
  ));

  const railMarkup = renderProcessRail(state, items);
  const topBarMarkup = renderTopBar(state, {
    sourceLabel: "<b>unsafe & source</b>",
  });

  assert.match(railMarkup, /&lt;strong&gt;unsafe &amp; summary&lt;\/strong&gt;/);
  assert.doesNotMatch(railMarkup, /<small><strong>unsafe/);
  assert.match(railMarkup, /\/tmp\/&lt;review&gt;&amp;&quot;&#39;output/);
  assert.match(topBarMarkup, /&lt;b&gt;unsafe &amp; source&lt;\/b&gt;/);
  assert.doesNotMatch(topBarMarkup, /<span class="topbar-source"><b>/);
});

test("english shell copy uses plain labels instead of machine-style strings", () => {
  const sourceState = createInitialSessionState();
  sourceState.ui.locale = "en";
  sourceState.ui.activeStep = "source";
  sourceState.ui.backend = { ready: true };
  sourceState.source.filePath = "/tmp/video.mp4";
  sourceState.source.displayName = "video.mp4";
  sourceState.source.metadata = {
    resolutionLabel: "1920x1080",
    durationLabel: "01:24",
  };

  const reviewState = createInitialSessionState();
  reviewState.ui.locale = "en";
  reviewState.ui.activeStep = "review";
  reviewState.review.outputDir = "/tmp/export";
  reviewState.review.selectedPageIds = ["1"];

  const topBarMarkup = renderTopBar(sourceState, {
    sourceLabel: "video.mp4",
  });
  const railMarkup = renderProcessRail(sourceState, getProcessRailItems(sourceState));
  const laneMarkup = renderContextLane(reviewState);

  assert.match(topBarMarkup, />Drum Sheet Capture</);
  assert.match(topBarMarkup, />Source</);
  assert.match(topBarMarkup, />Processor ready</);
  assert.doesNotMatch(topBarMarkup, /VIDEO SOURCE|ENGINE_READY|PRECISION MEDIA WORKBENCH/);
  assert.doesNotMatch(topBarMarkup, /Personal score capture/);

  assert.match(railMarkup, />Steps</);
  assert.match(railMarkup, />Ready</);
  assert.match(railMarkup, /<span>Source<\/span><strong>Loaded<\/strong>/);
  assert.doesNotMatch(railMarkup, /PIPELINE|WORKBENCH STATUS|<span>SOURCE<\/span><strong>LOADED<\/strong>/);

  assert.match(laneMarkup, />Selected result</);
  assert.match(laneMarkup, />Selection state</);
  assert.match(laneMarkup, />Nothing selected</);
  assert.doesNotMatch(laneMarkup, /INSPECTION VIEW|EXPORT STATE|NO SELECTION/);
});

test("shell css keeps review toolbar left-aligned at medium widths and exposes segmented-control focus styling", () => {
  const componentsCss = readFileSync(new URL("../styles/components.css", import.meta.url), "utf8");

  assert.match(
    componentsCss,
    /@media \(max-width: 1320px\) \{[\s\S]*?\.review-toolbar \{[\s\S]*?justify-content:\s*flex-start;/
  );
  assert.doesNotMatch(
    componentsCss,
    /\.review-toolbar \{\s*justify-items:\s*start;/
  );
  assert.match(componentsCss, /\.segment:focus-within\s*\{/);
});

test("roi top bar css reserves a centered lane while anchoring locale controls to the right", () => {
  const componentsCss = readFileSync(new URL("../styles/components.css", import.meta.url), "utf8");

  assert.match(
    componentsCss,
    /\.topbar-roi\s*\{[\s\S]*?display:\s*grid;[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1fr\)\s+auto\s+minmax\(0,\s*1fr\);/
  );
  assert.match(
    componentsCss,
    /\.topbar-tools-compact\s*\{[\s\S]*?grid-column:\s*3;[\s\S]*?justify-self:\s*end;/
  );
});

test("layout css enables independent shell scrolling for short-height viewports", () => {
  const layoutCss = readFileSync(new URL("../styles/layout.css", import.meta.url), "utf8");

  assert.match(layoutCss, /\.app-shell \{[\s\S]*?grid-template-rows:\s*56px minmax\(0, 1fr\) 26px;/);
  assert.match(layoutCss, /\.process-rail \{[\s\S]*?overflow-y:\s*auto;/);
  assert.match(layoutCss, /\.screen-source,\s*[\r\n]+\s*\.screen-export,\s*[\r\n]+\s*\.screen-review \{[\s\S]*?grid-template-rows:\s*auto minmax\(0, 1fr\);/);
});

test("top bar css keeps breathing room around navigation controls", () => {
  const componentsCss = readFileSync(new URL("../styles/components.css", import.meta.url), "utf8");

  assert.match(componentsCss, /\.topbar \{[\s\S]*?gap:\s*20px;[\s\S]*?padding:\s*0 20px;/);
  assert.match(componentsCss, /\.topbar-step \{[\s\S]*?min-height:\s*28px;[\s\S]*?padding:\s*0 12px;/);
});

test("export crop preview css opts out of full-height stretching so roi aspect ratios stay intact", () => {
  const componentsCss = readFileSync(new URL("../styles/components.css", import.meta.url), "utf8");

  assert.match(
    componentsCss,
    /\.export-preview-crop \{[\s\S]*?height:\s*auto;[\s\S]*?aspect-ratio:\s*calc\(var\(--crop-w\) \/ var\(--crop-h\)\);/
  );
});

test("export preview column does not stretch into a dead gray slab", () => {
  const componentsCss = readFileSync(new URL("../styles/components.css", import.meta.url), "utf8");

  assert.match(
    componentsCss,
    /\.export-preview-workbench \{[\s\S]*?align-self:\s*start;[\s\S]*?padding:\s*18px 20px 16px;/
  );
  assert.match(
    componentsCss,
    /\.export-preview-stage \{[\s\S]*?height:\s*clamp\(300px,\s*42vh,\s*440px\);[\s\S]*?padding:\s*24px;/
  );
  assert.match(
    componentsCss,
    /\.export-preview-crop \{[\s\S]*?width:\s*min\(960px,\s*100%\);/
  );
});

test("metadata modal secondary buttons keep explicit visible text color on the paper surface", () => {
  const componentsCss = readFileSync(new URL("../styles/components.css", import.meta.url), "utf8");

  assert.match(
    componentsCss,
    /\.export-metadata-actions \.button-secondary,\s*[\r\n]+\s*\.export-metadata-discard-actions \.button-secondary \{[\s\S]*?color:\s*var\(--accent\);/
  );
});

test("shared visual tokens stay calm and avoid futuristic amber shell effects", () => {
  const tokensCss = readFileSync(new URL("../styles/tokens.css", import.meta.url), "utf8");
  const baseCss = readFileSync(new URL("../styles/base.css", import.meta.url), "utf8");
  const componentsCss = readFileSync(new URL("../styles/components.css", import.meta.url), "utf8");
  const combinedCss = `${tokensCss}\n${baseCss}\n${componentsCss}`;

  assert.match(tokensCss, /--accent:\s*oklch\(0\.48 0\.07 190\);/);
  assert.match(tokensCss, /--bg-app:\s*oklch\(0\.86 0\.006 205\);/);
  assert.match(tokensCss, /--bg-pane:\s*oklch\(0\.905 0\.006 205\);/);
  assert.match(baseCss, /color-scheme:\s*light;/);
  assert.doesNotMatch(componentsCss, /rgba?\(|#[0-9a-fA-F]{3,8}|oklch\(/);
  assert.doesNotMatch(combinedCss, /#d7a347|#e7bd72|236,\s*182,\s*19|215,\s*163,\s*71|radial-gradient/i);
});
