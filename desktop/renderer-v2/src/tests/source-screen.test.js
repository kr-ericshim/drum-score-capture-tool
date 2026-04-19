import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState } from "../app/session/selectors.js";
import { buildSourceScreenModel, renderSourceScreen } from "../features/source/SourceScreen.js";
import { t } from "../lib/i18n.js";

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

test("source screen promotes file selection before metadata", () => {
  const state = createInitialSessionState();
  const model = buildSourceScreenModel(state);

  assert.equal(model.primaryAction.disabled, false);
  assert.match(model.primaryAction.label, /영상 선택|Choose Video/);
  assert.equal(model.fileMeta.length, 0);
  assert.equal(model.secondaryAction, null);
});

test("source screen exposes compact metadata after file selection", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.source.filePath = "/tmp/song.mp4";
  state.source.displayName = "song.mp4";
  state.source.metadata = { durationLabel: "02:31", resolutionLabel: "1920x1080" };

  const model = buildSourceScreenModel(state);

  assert.deepEqual(model.fileMeta, [
    { label: "파일", value: "song.mp4" },
    { label: "길이", value: "02:31" },
    { label: "해상도", value: "1920x1080" },
  ]);
});

test("source screen keeps only the real file-pick action", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.source.filePath = "/tmp/song.mp4";
  state.source.displayName = "song.mp4";
  state.source.metadata = { durationLabel: "02:31", resolutionLabel: "1920x1080" };

  const markup = renderSourceScreen(state);

  assert.match(markup, /data-action="select-source-file"/);
  assert.doesNotMatch(markup, /SCAN DIRECTORY|폴더 스캔/);
  assert.doesNotMatch(markup, /<button[^>]*>LOAD<\/button>/);
  assert.match(markup, /현재 선택|Current/);
});

test("source registry reflects the actual selected file directory instead of a placeholder path", () => {
  const state = createInitialSessionState();
  state.source.filePath = "/Users/tester/Videos/song.mp4";
  state.source.displayName = "song.mp4";
  state.source.metadata = { durationLabel: "02:31", resolutionLabel: "1920x1080" };

  const markup = renderSourceScreen(state);

  assert.match(markup, /\/Users\/tester\/Videos\//);
  assert.doesNotMatch(markup, /\/local\/session\//);
  assert.doesNotMatch(markup, /session_capture\.mp4/);
});

test("source registry renders persisted items with reload actions on inactive rows", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.registryItems = [
    {
      filePath: "/Users/tester/Library/Application Support/DrumSheet/jobs/cache-a.mkv",
      displayName: "cache-a.mkv",
      directory: "/Users/tester/Library/Application Support/DrumSheet/jobs/cache-a",
      resolutionLabel: "1920x1080",
      durationLabel: "04:12",
      hasScore: true,
    },
  ];

  const markup = renderSourceScreen(state);

  assert.match(markup, /cache-a\.mkv/);
  assert.match(markup, /data-action="load-registry-source"/);
  assert.match(markup, />Open</);
  assert.match(markup, /1920x1080/);
  assert.match(markup, /04:12/);
});

test("source registry exposes per-cell column labels for narrow-width restyling", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.filePath = "/Users/tester/Videos/current-score.mp4";
  state.source.displayName = "current-score.mp4";
  state.source.metadata = { durationLabel: "03:21", resolutionLabel: "1280x720" };
  state.source.registryItems = [
    {
      filePath: "/Users/tester/Videos/current-score.mp4",
      displayName: "current-score.mp4",
      directory: "/Users/tester/Videos/",
      resolutionLabel: "1280x720",
      durationLabel: "03:21",
      hasScore: true,
    },
    {
      filePath: "/Users/tester/Videos/archive-score.mp4",
      displayName: "archive-score.mp4",
      directory: "/Users/tester/Videos/",
      resolutionLabel: "1920x1080",
      durationLabel: "04:12",
      hasScore: true,
    },
  ];

  const markup = renderSourceScreen(state);
  const filenameLabel = t("source.registryFilename", { locale: "en" });
  const pathLabel = t("source.registryPath", { locale: "en" });
  const resLabel = t("source.registryRes", { locale: "en" });
  const lengthLabel = t("source.registryLength", { locale: "en" });
  const actionLabel = t("source.registryAction", { locale: "en" });

  assert.match(markup, /<th scope="col" data-column="filename">/);
  assert.match(markup, /<th scope="col" data-column="action">/);
  assert.match(markup, new RegExp(`data-column="filename" data-column-label="${escapeRegExp(filenameLabel)}"`));
  assert.match(markup, new RegExp(`data-column="path" data-column-label="${escapeRegExp(pathLabel)}"`));
  assert.match(markup, new RegExp(`data-column="resolution" data-column-label="${escapeRegExp(resLabel)}"`));
  assert.match(markup, new RegExp(`data-column="duration" data-column-label="${escapeRegExp(lengthLabel)}"`));
  assert.match(markup, new RegExp(`data-column="action" data-column-label="${escapeRegExp(actionLabel)}"`));
  assert.match(markup, /<tr class="registry-row is-selected"[^>]*data-selected="true"/);
  assert.match(markup, /<tr class="registry-row"[^>]*data-selected="false"/);
  assert.match(markup, /data-action="load-registry-source"/);
  assert.match(markup, />Current</);
});

test("source screen renders english helper copy when locale is en", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";

  const markup = renderSourceScreen(state);

  assert.match(markup, /Choose Video|Open Local Video|Local Media Registry/i);
  assert.doesNotMatch(markup, /현재 1차 플로우는|로컬 영상 불러오기/);
});

test("source screen renders youtube controls and preparation log region", () => {
  const state = createInitialSessionState();

  const markup = renderSourceScreen(state);

  assert.match(markup, /YouTube|유튜브/i);
  assert.match(markup, /prepare-source-youtube/);
  assert.match(markup, /youtube-log|source-prepare-log|Preparation Log|준비 로그/i);
  assert.match(markup, /type="url"/);
  assert.match(markup, /inputmode="url"/);
});

test("source screen marks the ingest card as a drag-and-drop target with helper copy", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";

  const markup = renderSourceScreen(state);

  assert.match(markup, /data-drop-zone="source-ingest"/);
  assert.match(markup, /You can also drag a video file here to import it right away\./);
  assert.match(markup, /Drop now to import it immediately\./);
});

test("source screen gives the youtube field an explicit accessible label", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";

  const markup = renderSourceScreen(state);

  assert.match(markup, /for="sourceYoutubeUrl"/);
  assert.match(markup, /id="sourceYoutubeUrl"/);
  assert.match(markup, /aria-describedby="sourceYoutubeHint"/);
  assert.doesNotMatch(markup, /aria-describedby="[^"]*sourceYoutubeLog/);
});

test("source screen only adds the invalid-url note to the youtube field description chain", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.youtubeUrl = "not-a-youtube-link";

  const markup = renderSourceScreen(state);

  assert.match(markup, /aria-describedby="sourceYoutubeHint sourceYoutubeNote"/);
  assert.doesNotMatch(markup, /aria-describedby="[^"]*sourceYoutubeLog/);
  assert.match(markup, /id="sourceYoutubeNote"/);
  assert.match(markup, /id="sourceYoutubeLog"/);
});

test("source screen escapes user-controlled values before inserting markup", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.filePath = "/tmp/<clip>.mp4";
  state.source.displayName = "<clip>.mp4";
  state.source.metadata = {
    durationLabel: "02:31",
    resolutionLabel: "1920x1080",
  };
  state.source.youtubeUrl = 'https://youtu.be/demo" xssattr="1';
  state.source.prepareStatus = "failed";
  state.source.prepareErrorDetail = 'low resolution <script>alert("x")</script>';
  state.source.prepareLogs = ['<script>alert("log")</script>'];
  state.source.error = '<strong>bad</strong>';

  const markup = renderSourceScreen(state);

  assert.match(markup, /value="https:\/\/youtu\.be\/demo&quot; xssattr=&quot;1"/);
  assert.match(markup, /&lt;clip&gt;\.mp4/);
  assert.match(markup, /&lt;script&gt;alert\(&quot;log&quot;\)&lt;\/script&gt;/);
  assert.match(markup, /&lt;script&gt;alert\(&quot;x&quot;\)&lt;\/script&gt;/);
  assert.match(markup, /&lt;strong&gt;bad&lt;\/strong&gt;/);
  assert.doesNotMatch(markup, /<script>alert\("log"\)<\/script>/);
  assert.doesNotMatch(markup, /<script>alert\("x"\)<\/script>/);
  assert.doesNotMatch(markup, /<strong>bad<\/strong>/);
  assert.doesNotMatch(markup, /xssattr="1"/);
});

test("source screen disables youtube prepare while loading and shows low-quality warning copy", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.prepareStatus = "loading";
  state.source.prepareStage = "download";
  state.source.prepareProgress = 0.42;
  state.source.prepareProgressMode = "determinate";
  state.source.prepareMessage = "downloading video 42%";
  state.source.error = "YouTube preparation stopped because only a low-resolution video was available: low resolution 640x360";
  state.source.prepareErrorDetail = "low resolution 640x360";
  state.source.prepareLogs = ["low resolution 640x360"];

  const markup = renderSourceScreen(state);

  assert.match(markup, /prepare-source-youtube\" disabled/);
  assert.match(markup, /low-resolution warning|quality gate|640x360/i);
});

test("source screen renders determinate youtube progress with stage summary", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.youtubeUrl = "https://youtu.be/demo";
  state.source.prepareStatus = "loading";
  state.source.prepareStage = "download";
  state.source.prepareProgress = 0.42;
  state.source.prepareProgressMode = "determinate";
  state.source.prepareMessage = "downloading video 42%";
  state.source.prepareLogs = ["yt-dlp: download 42%"];

  const markup = renderSourceScreen(state);

  assert.match(markup, /42%/);
  assert.match(markup, /progressbar/);
  assert.match(markup, /Downloading|다운로드/i);
});

test("source screen keeps youtube prepare disabled until a youtube link is entered", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.youtubeUrl = "not-a-youtube-link";

  const markup = renderSourceScreen(state);

  assert.match(markup, /prepare-source-youtube\" disabled/);
  assert.match(markup, /Paste a valid YouTube link/i);
});
