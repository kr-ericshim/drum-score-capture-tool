import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState, deriveLineReview, deriveReflowInfo } from "../app/session/selectors.js";
import { createReviewController } from "../features/review/reviewController.js";
import { renderReviewScreen } from "../features/review/ReviewScreen.js";
import { lineCheckOpen, lineSourceTimes, pendingSeamRejections, seamChecks } from "../features/review/lineCheck.js";
import { reviewExport } from "../lib/api.js";

const LINES = [
  { line_id: "line-001", page: 1, rect: [200, 300, 2000, 200], page_size: [2480, 3508], measures: 4,
    sources: [{ system_id: "jmp-01-001", display: "ep-0000", t_start: 0, t_end: 9.6 }],
    seams: [], attention: null },
  { line_id: "line-002", page: 1, rect: [200, 560, 2000, 200], page_size: [2480, 3508], measures: 4,
    sources: [{ system_id: "jmp-01-001", display: "ep-0003", t_start: 23.5, t_end: 27.4 },
      { system_id: "jmp-01-001", display: "ep-0004", t_start: 27.5, t_end: 31.4 }],
    seams: [{ id: "seam-ep-0003-ep-0004", status: "resolved", evidence: ["forward", "typical_jump"], low_ink: false, x_frac: 0.4 }],
    attention: "seam_inferred" },
  { line_id: "line-003", page: 2, rect: [200, 300, 2000, 200], page_size: [2480, 3508], measures: 3,
    sources: [{ system_id: "jmp-01-001", display: "ep-0005", t_start: 31.5, t_end: 35.4 }],
    seams: [{ id: "seam-ep-0004-ep-0005", status: "verified", evidence: [], low_ink: false, x_frac: 0.1 }], attention: null },
];

function reviewState(locale = "ko", lineReview = LINES) {
  const state = createInitialSessionState();
  state.ui.locale = locale;
  state.exportConfig.jobId = "job-1";
  state.exportConfig.runStatus = "done";
  state.source.filePath = "/v.webm";
  state.roi.appliedRect = [[0, 826], [1470, 826], [1470, 1080], [0, 1080]];
  state.roi.imageWidth = 1920;
  state.roi.imageHeight = 1080;
  state.review.pages = [{ id: "a", kind: "system", systemId: "jmp-01-001", title: "줄 1", capturePath: "/s1.png", previewPath: "/s1.png" }];
  state.review.selectedPageIds = ["a"];
  state.review.focusedPageId = "a";
  state.review.outputPages = [{ index: 1, path: "/p1.jpg" }, { index: 2, path: "/p2.jpg" }];
  state.review.reflow = deriveReflowInfo({ output_model: "clean_reflow_v1", source_video_path: "/src/v.webm",
    reflow: { revision: 1, line_review: lineReview } });
  return state;
}

function harness(state, api = {}) {
  const box = { state };
  const controller = createReviewController({ getState: () => box.state, setState: update => { box.state = update(structuredClone(box.state)); },
    api, root: {}, mountEditor() {} });
  return { box, controller };
}

test("line review entries are parsed and malformed ones dropped", () => {
  const lines = deriveLineReview([...LINES, { line_id: "bad", page: 0, rect: [0, 0, 1, 1], page_size: [10, 10] },
    { line_id: "bad2", page: 1, rect: [0, 0, 10], page_size: [10, 10] }, null,
    { line_id: "odd", page: 1, rect: [0, 0, 10, 5], page_size: [10, 10], seams: [{ id: "s", status: "weird" }, { id: "t", status: "verified", x_frac: 4 }],
      sources: [{ t_start: 5, t_end: 2 }], attention: "other" }]);
  assert.deepEqual(lines.map(line => line.id), ["line-001", "line-002", "line-003", "odd"]);
  assert.equal(lines[1].seams[0].status, "resolved");
  assert.equal(lines[1].attention, "seam_inferred");
  assert.deepEqual(lines[3].seams.map(seam => [seam.id, seam.xFrac]), [["t", 1]]);
  assert.deepEqual(lines[3].sources, []);
  assert.equal(lines[3].attention, "");
  assert.deepEqual(deriveLineReview(undefined), []);
  assert.deepEqual(lineSourceTimes(lines[1]), [25.5, 29.5]);
});

test("the inferred seams become the places to check, with the video around each jump", () => {
  const lines = deriveLineReview(LINES);
  const checks = seamChecks(lines);
  assert.deepEqual(checks.map(check => check.seam.id), ["seam-ep-0003-ep-0004"]);
  assert.equal(checks[0].jump, 27.4);
  assert.deepEqual(checks[0].clip, [22.4, 32.4]);
  assert.equal(checks[0].lineNumber, 2);
  assert.deepEqual(checks[0].around.map(line => line.id), ["line-002"]);
  // a seam near the start of a line also shows the end of the line before it
  const near = deriveLineReview(LINES.map(line => line.line_id === "line-002"
    ? { ...line, seams: [{ ...line.seams[0], x_frac: 0.1 }] } : line));
  assert.deepEqual(seamChecks(near)[0].around.map(line => line.id), ["line-001", "line-002"]);
});

test("a chart with inferred seams opens on the join check, in Korean and English", () => {
  for (const locale of ["ko", "en"]) {
    const state = reviewState(locale);
    assert.equal(lineCheckOpen(state), true);
    const html = renderReviewScreen(state);
    assert.match(html, /review-viewer-surface is-lines/);
    assert.match(html, locale === "ko" ? /<h2>이음새 확인<\/h2>/ : /<h2>Check the joins<\/h2>/);
    assert.match(html, locale === "ko" ? /1곳 중 0곳 확인/ : /0 of 1 checked/);
    assert.match(html, locale === "ko" ? /이음새 확인 1</ : /Check joins 1</);
    assert.equal((html.match(/<article class="review-seam-check /g) || []).length, 1);
    // the clip of the source video, cropped to the score region, with its play button
    assert.match(html, /<video data-seam-video="seam-ep-0003-ep-0004" data-start="22.40" data-end="32.40" src="file:\/\/\/src\/v\.webm#t=22\.40"/);
    assert.match(html, /review-seam-video is-cropped" style="aspect-ratio:1470\.0 \/ 254\.0"/);
    assert.match(html, locale === "ko" ? /▶ 이 부분 재생 \(0:22–0:32\)/ : /▶ Play this part \(0:22–0:32\)/);
    assert.match(html, /review-line-seam is-resolved" style="left:40\.000%"/);
    assert.match(html, /data-action="review-seam-answer" data-value="seam-ep-0003-ep-0004\|ok"/);
    // the full list is folded away
    assert.doesNotMatch(html, /<article class="review-line /);
    assert.match(html, locale === "ko" ? /전체 줄 보기 \(3줄\)/ : /Show all lines \(3\)/);
  }
});

test("answers show progress, and a bad join points to a problem report", async () => {
  const { box, controller } = harness(reviewState("en"));
  await controller.handleAction("review-seam-answer", "seam-ep-0003-ep-0004|ok");
  let html = renderReviewScreen(box.state);
  assert.match(html, /1 of 1 checked/);
  assert.match(html, /review-seam-check is-ok/);
  assert.match(html, /class="review-seam-done">Checked</);
  await controller.handleAction("review-seam-answer", "seam-ep-0003-ep-0004|bad");
  html = renderReviewScreen(box.state);
  assert.match(html, /review-seam-check is-bad/);
  assert.match(html, /data-action="open-bug-report"/);
  await controller.handleAction("review-seam-answer", "seam-ep-0003-ep-0004|maybe");
  assert.equal(box.state.review.lineCheck.answers["seam-ep-0003-ep-0004"], "bad");
  // "hard to tell" stays unchecked: not counted, not taken for a fine join, and asks to compare again
  await controller.handleAction("review-seam-answer", "seam-ep-0003-ep-0004|unsure");
  html = renderReviewScreen(box.state);
  assert.match(html, /0 of 1 checked/);
  assert.match(html, /review-seam-check is-unsure/);
  assert.match(html, /class="review-seam-done is-unconfirmed">Not checked</);
  assert.match(html, /This place stays unchecked/);
  assert.match(html, /\|unsure" aria-pressed="true">Hard to tell</);
  assert.equal(pendingSeamRejections(box.state), null, "only a wrong join is rebuilt");
});

test("with every join verified it opens on the pages and lists all lines when asked; with no seams it waits to be asked", async () => {
  const plain = LINES.map(line => ({ ...line, seams: line.seams.map(seam => ({ ...seam, status: "verified" })), attention: null }));
  const { box, controller } = harness(reviewState("en", plain));
  assert.equal(lineCheckOpen(box.state), true); // verified seams: nothing to check
  // nothing to check: the review opens on the pages; asking shows the full list
  let html = renderReviewScreen(box.state);
  assert.match(html, /is-pages/);
  await controller.handleAction("review-lines");
  html = renderReviewScreen(box.state);
  assert.match(html, /every join was verified automatically/);
  assert.equal((html.match(/<article class="review-line /g) || []).length, 3);
  assert.match(html, /Check lines 3</);
  const none = harness(reviewState("en", LINES.map(line => ({ ...line, seams: [], attention: null }))));
  assert.equal(lineCheckOpen(none.box.state), false);
  await none.controller.handleAction("review-lines");
  assert.match(renderReviewScreen(none.box.state), /You can compare the PDF&#39;s 3 lines with the video\./);
  await none.controller.handleAction("review-page-preview");
  assert.match(renderReviewScreen(none.box.state), /is-pages/);
  await none.controller.handleAction("review-lines");
  assert.equal(none.box.state.review.pagePreview, false);
  await none.controller.handleAction("review-lines");
  assert.equal(lineCheckOpen(none.box.state), false);
  assert.doesNotMatch(renderReviewScreen(reviewState("en", [])), /review-lines/);
});

test("the play button plays the clip from its start and stops at its end", async () => {
  const listeners = {};
  const video = { dataset: { seamVideo: "seam-ep-0003-ep-0004", start: "22.40", end: "32.40" }, paused: true, currentTime: 0,
    pause() { this.paused = true; listeners.onpause?.(); }, play() { this.paused = false; this.onplay?.(); return Promise.resolve(); } };
  Object.defineProperty(video, "onpause", { set(fn) { listeners.onpause = fn; }, get() { return listeners.onpause; } });
  const button = { dataset: { value: "seam-ep-0003-ep-0004", labelPlay: "Play", labelPause: "Pause" }, textContent: "Play" };
  const root = { querySelectorAll: selector => (selector.startsWith("video") ? [video] : [button]) };
  const state = reviewState("en");
  const controller = createReviewController({ getState: () => state, setState() {}, api: {}, root, mountEditor() {} });
  await controller.handleAction("review-seam-play", "seam-ep-0003-ep-0004");
  assert.equal(video.currentTime, 22.4);
  assert.equal(video.paused, false);
  assert.equal(button.textContent, "Pause");
  video.currentTime = 32.5;
  video.ontimeupdate();
  assert.equal(video.paused, true);
  assert.equal(video.currentTime, 22.4);
  assert.equal(button.textContent, "Play");
});

test("the full list loads one still per display on request, cropped to the score region, and handles a failure", async () => {
  const calls = [];
  const api = { async requestPreviewFrame({ filePath, startSec }) {
    calls.push([filePath, startSec]);
    if (startSec > 29) throw new Error("ffmpeg failed");
    return { imagePath: `blob:frame-${startSec}` };
  } };
  const { box, controller } = harness(reviewState("en"), api);
  await controller.handleAction("review-lines-all");
  await controller.handleAction("review-line-source", "line-002");
  assert.deepEqual(calls, [["/src/v.webm", 25.5], ["/src/v.webm", 29.5]]);
  const html = renderReviewScreen(box.state);
  assert.match(html, /Page 1, line 2 · <span class="review-line-time">0:23–0:31<\/span>/);
  assert.match(html, /aria-expanded="true">Hide source/);
  assert.match(html, /src="blob:frame-25\.5"/);
  assert.match(html, /Could not load the video frame\./);
  await controller.handleAction("review-line-source", "line-002");
  await controller.handleAction("review-line-source", "line-002");
  assert.deepEqual(calls.map(call => call[1]), [25.5, 29.5, 29.5]);
});

test("a join answered wrong waits for a rebuild, which sends every rejected join", async () => {
  const state = reviewState("ko");
  state.review.status = "applied";
  const { box, controller } = harness(state);
  assert.equal(pendingSeamRejections(box.state), null);
  await controller.handleAction("review-seam-answer", "seam-ep-0003-ep-0004|bad");
  assert.equal(box.state.review.status, "idle", "the files no longer match the review");
  assert.deepEqual(pendingSeamRejections(box.state), ["seam-ep-0003-ep-0004"]);
  // joins kept by an earlier rebuild stay in the set
  box.state.review.reflow.rejectedSeamIds = ["seam-ep-0009-ep-0010"];
  assert.deepEqual(pendingSeamRejections(box.state), ["seam-ep-0003-ep-0004", "seam-ep-0009-ep-0010"]);
  await controller.handleAction("review-seam-answer", "seam-ep-0003-ep-0004|ok");
  assert.equal(pendingSeamRejections(box.state), null, "nothing new: the request leaves the kept joins alone");

  const previousWindow = globalThis.window;
  const bodies = [];
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { drumSheetAPI: { async requestJson(pathname, options) { bodies.push(JSON.parse(options.body)); return { ok: true, status: 200, data: {} }; } } },
  });
  try {
    await reviewExport("job-1", { keepCaptures: ["/a.png"], formats: ["pdf"] });
    await reviewExport("job-1", { keepCaptures: ["/a.png"], formats: ["pdf"], rejectedSeamIds: ["seam-ep-0003-ep-0004"], baseRevision: 3 });
    await reviewExport("job-1", { keepCaptures: ["/a.png"], formats: ["pdf"], rejectedSeamIds: [] });
  } finally {
    Object.defineProperty(globalThis, "window", { configurable: true, value: previousWindow });
  }
  assert.equal("rejected_seam_ids" in bodies[0], false);
  assert.equal("base_revision" in bodies[0], false);
  assert.deepEqual([bodies[1].rejected_seam_ids, bodies[1].base_revision], [["seam-ep-0003-ep-0004"], 3]);
  assert.deepEqual(bodies[2].rejected_seam_ids, []);
});

test("a rebuilt join shows both printed lines and says both views were kept, in Korean and English", () => {
  const rebuilt = [LINES[0],
    { ...LINES[1], seams: [{ id: "seam-ep-0003-ep-0004", status: "unverified", user_rejected: true, boundary: "end", x_frac: 1 }], attention: "seam_unverified" },
    { ...LINES[2], seams: [{ id: "seam-ep-0003-ep-0004", status: "unverified", user_rejected: true, boundary: "start", x_frac: 0 }] }];
  const lines = deriveLineReview(rebuilt);
  assert.deepEqual([lines[1].seams[0].userRejected, lines[1].seams[0].boundary], [true, "end"]);
  assert.equal(deriveLineReview(LINES)[1].seams[0].userRejected, false);
  const checks = seamChecks(lines);
  assert.equal(checks.length, 1, "one card per join, not per printed end");
  assert.deepEqual(checks[0].around.map(line => line.id), ["line-002", "line-003"]);
  assert.equal(checks[0].jump, 27.4);
  for (const [locale, note, tag] of [["ko", "앞뒤 화면을 모두 남겼어요", "연결 미확정 · 양쪽 화면 보존"], ["en", "so it kept both", "Join unconfirmed · both views kept"]]) {
    const state = reviewState(locale, rebuilt);
    state.review.reflow = deriveReflowInfo({ output_model: "clean_reflow_v1", source_video_path: "/src/v.webm",
      reflow: { revision: 2, line_review: rebuilt, rejected_seam_ids: ["seam-ep-0003-ep-0004"] } });
    assert.deepEqual(state.review.reflow.rejectedSeamIds, ["seam-ep-0003-ep-0004"]);
    state.review.lineCheck = { answers: { "seam-ep-0003-ep-0004": "bad" } };
    const html = renderReviewScreen(state);
    assert.match(html, new RegExp(note));
    // kept, not fixed: the tag reads as unconfirmed, not as done
    assert.match(html, new RegExp(`class="review-seam-done is-unconfirmed">${tag}<`));
    assert.doesNotMatch(html, /data-action="review-seam-answer"/, "no question on a join already rebuilt");
    assert.equal(pendingSeamRejections(state), null);
  }
});

test("from the default pages, system view and compare show the system, not the line list; zoom only for one system", async () => {
  const plain = LINES.map(line => ({ ...line, seams: line.seams.map(seam => ({ ...seam, status: "verified" })), attention: null }));
  const { box, controller } = harness(reviewState("en", plain));
  let html = renderReviewScreen(box.state);
  assert.match(html, /is-pages/);
  assert.doesNotMatch(html, /data-action="review-zoom-in"/);
  await controller.handleAction("review-page-preview");
  html = renderReviewScreen(box.state);
  assert.doesNotMatch(html, /is-pages|class="review-lines"/);
  assert.match(html, /review-full-image/);
  assert.match(html, /data-action="review-zoom-in"/);
  // compare from the pages
  const similar = harness(reviewState("en", plain));
  similar.box.state.review.pages = [
    { id: "a", kind: "system", systemId: "jmp-01-001", title: "System 1", capturePath: "/s1.png", previewPath: "/s1.png" },
    { id: "b", kind: "system", systemId: "jmp-01-002", title: "System 2", capturePath: "/s2.png", previewPath: "/s2.png", similarTo: { referenceId: "a", reason: "looks_similar" } },
  ];
  similar.box.state.review.focusedPageId = "b";
  await similar.controller.handleAction("review-compare");
  html = renderReviewScreen(similar.box.state);
  assert.match(html, /is-comparing/);
  assert.doesNotMatch(html, /class="review-lines"/);
});
