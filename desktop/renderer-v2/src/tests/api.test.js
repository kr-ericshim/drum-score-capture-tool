import test from "node:test";
import assert from "node:assert/strict";

import { cancelReviewExport, createPreviewSourceJob, getJob, getPreviewSourceJob, getReviewExportTask, preparePreviewSource, requestAutoRoi, requestPreviewFrame, reviewExport, startReviewExport } from "../lib/api.js";

test("requestPreviewFrame loads protected preview assets without putting the token in the image url", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  const previousCreateObjectUrl = globalThis.URL.createObjectURL;
  const requestCalls = [];
  const assetCalls = [];
  const objectUrls = [];

  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      drumSheetAPI: {
        apiBase: "http://127.0.0.1:8000",
        async requestJson(pathname, options) {
          requestCalls.push({ pathname, options });
          return {
            ok: true,
            status: 200,
            data: {
              image_path: "/tmp/cache/preview.png",
              image_url: "/jobs-files/_preview/preview.png",
              diagnostics: [],
            },
          };
        },
        async readJobAsset(pathname) {
          assetCalls.push(pathname);
          return {
            bytes: new Uint8Array([1, 2, 3]).buffer,
            contentType: "image/png",
          };
        },
      },
    },
  });

  globalThis.URL.createObjectURL = (blob) => {
    objectUrls.push(blob);
    return "blob:preview-frame";
  };

  globalThis.fetch = async () => {
    throw new Error("renderer should use the preload bridge for authenticated preview requests");
  };

  try {
    const result = await requestPreviewFrame({ filePath: "/tmp/source.mp4", startSec: 12 });

    assert.equal(result.imagePath, "blob:preview-frame");
    assert.equal(result.sourcePath, "/tmp/cache/preview.png");
    assert.deepEqual(requestCalls, [
      {
        pathname: "/preview/frame",
        options: {
          method: "POST",
          body: JSON.stringify({
            source_type: "file",
            file_path: "/tmp/source.mp4",
            start_sec: 12,
          }),
        },
      },
    ]);
    assert.deepEqual(assetCalls, ["/jobs-files/_preview/preview.png"]);
    assert.equal(objectUrls.length, 1);
  } finally {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: previousWindow,
    });
    globalThis.fetch = previousFetch;
    globalThis.URL.createObjectURL = previousCreateObjectUrl;
  }
});

test("requestAutoRoi posts the prepared file and maps a conservative suggestion", async () => {
  const previousWindow = globalThis.window;
  const calls = [];
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      drumSheetAPI: {
        async requestJson(pathname, options) {
          calls.push({ pathname, options });
          return {
            ok: true,
            status: 200,
            data: {
              status: "suggested",
              roi: [[10, 20], [310, 20], [310, 160], [10, 160]],
              evidence_level: "high",
              layout_hint: "bottom_bar",
              is_dark_mode: false,
              diagnostics: { supporting_frames: 3 },
            },
          };
        },
      },
    },
  });

  try {
    const result = await requestAutoRoi({ filePath: "/tmp/source.mp4", startSec: 12 });

    assert.equal(result.status, "suggested");
    assert.equal(result.evidenceLevel, "high");
    assert.deepEqual(result.roi, [[10, 20], [310, 20], [310, 160], [10, 160]]);
    assert.deepEqual(JSON.parse(calls[0].options.body), {
      source_type: "file",
      file_path: "/tmp/source.mp4",
      youtube_url: null,
      start_sec: 12,
    });
  } finally {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: previousWindow,
    });
  }
});

test("preparePreviewSource posts youtube payload and maps the backend response", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;

  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      drumSheetAPI: {
        apiBase: "http://127.0.0.1:8000",
      },
    },
  });

  globalThis.fetch = async (url, options) => {
    assert.match(String(url), /\/preview\/source$/);
    assert.equal(options.method, "POST");
    assert.deepEqual(JSON.parse(options.body), {
      source_type: "youtube",
      file_path: null,
      youtube_url: "https://youtu.be/demo",
    });

    return {
      ok: true,
      async json() {
        return {
          video_path: "/tmp/cache/demo.mp4",
          video_url: "/jobs-files/_preview/demo.mp4",
          from_cache: true,
          log_lines: ["youtube download saved: /tmp/cache/demo.mp4"],
        };
      },
    };
  };

  try {
    const result = await preparePreviewSource({
      sourceType: "youtube",
      youtubeUrl: "https://youtu.be/demo",
    });

    assert.equal(result.videoPath, "/tmp/cache/demo.mp4");
    assert.equal(result.videoUrl, "http://127.0.0.1:8000/jobs-files/_preview/demo.mp4");
    assert.doesNotMatch(result.videoUrl, /token-123/);
    assert.equal(result.fromCache, true);
    assert.equal(result.logLines.length, 1);
  } finally {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: previousWindow,
    });
    globalThis.fetch = previousFetch;
  }
});

test("createPreviewSourceJob posts the youtube url and returns a job id", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;

  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      drumSheetAPI: {
        apiBase: "http://127.0.0.1:8000",
      },
    },
  });

  globalThis.fetch = async (url, options) => {
    assert.match(String(url), /\/preview\/source-jobs$/);
    assert.equal(options.method, "POST");
    assert.deepEqual(JSON.parse(options.body), {
      youtube_url: "https://youtu.be/demo",
    });

    return {
      ok: true,
      async json() {
        return { job_id: "source-1" };
      },
    };
  };

  try {
    const result = await createPreviewSourceJob({ youtubeUrl: "https://youtu.be/demo" });
    assert.equal(result, "source-1");
  } finally {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: previousWindow,
    });
    globalThis.fetch = previousFetch;
  }
});

test("getPreviewSourceJob maps stage, progress, logs, and result payload", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;

  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      drumSheetAPI: {
        apiBase: "http://127.0.0.1:8000",
      },
    },
  });

  globalThis.fetch = async (url, options) => {
    assert.match(String(url), /\/preview\/source-jobs\/source-1$/);
    assert.equal(options?.method || "GET", "GET");

    return {
      ok: true,
      async json() {
        return {
          job_id: "source-1",
          status: "running",
          stage: "download",
          message: "downloading video 42%",
          progress: 0.42,
          progress_mode: "determinate",
          log_tail: ["yt-dlp: download 42%"],
          result: {
            video_path: "/tmp/cache/demo.mp4",
            video_url: "/jobs-files/_preview/demo.mp4",
            from_cache: false,
          },
        };
      },
    };
  };

  try {
    const result = await getPreviewSourceJob("source-1");
    assert.equal(result.jobId, "source-1");
    assert.equal(result.stage, "download");
    assert.equal(result.progressMode, "determinate");
    assert.equal(result.logLines.length, 1);
    assert.equal(result.result.videoPath, "/tmp/cache/demo.mp4");
    assert.equal(result.result.videoUrl, "http://127.0.0.1:8000/jobs-files/_preview/demo.mp4");
    assert.doesNotMatch(result.result.videoUrl, /token-123/);
  } finally {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: previousWindow,
    });
    globalThis.fetch = previousFetch;
  }
});

test("a rebuild uses the normal request timeout and error details stay readable", async () => {
  const previousWindow = globalThis.window;
  const calls = [];
  let reply = { ok: true, status: 200, data: { kept_count: 14 } };
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      drumSheetAPI: {
        apiBase: "http://127.0.0.1:8000",
        async requestJson(pathname, options) {
          calls.push({ pathname, options });
          if (reply instanceof Function) return reply();
          return reply;
        },
      },
    },
  });
  try {
    // the rebuild runs in the background on the backend: its start answers at once
    await reviewExport("job-1", { keepCaptures: ["/a.png"], formats: ["pdf"] });
    assert.equal(calls[0].options.timeoutMs, undefined);
    await getJob("job-1");
    assert.equal(calls[1].options.timeoutMs, undefined);

    // FastAPI validation detail (a list of objects)
    reply = { ok: false, status: 422, data: { detail: [{ loc: ["body"], msg: "field required" }] } };
    await assert.rejects(getJob("job-1"), (error) => error.message === "field required" && error.status === 422);
    // an object detail with nothing readable falls back to the request's own message
    reply = { ok: false, status: 409, data: { detail: { code: 7 } } };
    await assert.rejects(getJob("job-1"), (error) => !/\[object Object\]/.test(error.message) && error.status === 409);
    // a rejection that crossed the preload bridge as a plain object
    reply = () => { throw {}; };
    await assert.rejects(reviewExport("job-1", { keepCaptures: ["/a.png"], formats: ["pdf"] }), (error) => error instanceof Error && error.message === "검토 반영에 실패했습니다.");
  } finally {
    Object.defineProperty(globalThis, "window", { configurable: true, value: previousWindow });
  }
});

function withBridge(handler) {
  const previousWindow = globalThis.window;
  const calls = [];
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { drumSheetAPI: { apiBase: "http://127.0.0.1:8000", async requestJson(pathname, options) { calls.push({ pathname, options }); return handler(pathname, options, calls); } } },
  });
  return { calls, restore: () => Object.defineProperty(globalThis, "window", { configurable: true, value: previousWindow }) };
}

function taskReply(fields) {
  return { ok: true, status: fields.state === "queued" && !fields.polled ? 202 : 200,
    data: { task_id: "t1", job_id: "job-1", revision: 3, state: "running", stage: "planning", progress: 0, cancel_requested: false, ...fields } };
}

test("reviewExport starts a background rebuild, polls it with backoff and returns its result", async () => {
  const snapshots = [
    taskReply({ state: "queued", stage: "queued" }),
    taskReply({ stage: "planning", progress: 0.1 }),
    { ok: false, status: 0, get data() { throw new Error("unused"); } },
    taskReply({ stage: "sizing", progress: 0.45 }),
    taskReply({ state: "done", stage: "done", progress: 1, result: { pdf: "/x/sheet_export.pdf", kept_count: 4, revision: 3 } }),
  ];
  let step = 0;
  const bridge = withBridge(() => {
    const reply = snapshots[step++];
    if (reply.status === 0) throw new Error("REQUEST_FAILED: connection reset");  // one dropped poll is retried
    return reply;
  });
  const seen = [];
  const delays = [];
  try {
    const result = await reviewExport("job-1", { keepCaptures: ["/a.png"], formats: ["pdf"] }, {
      onTask: (task) => seen.push(`${task.state}:${task.stage}:${task.progress}`),
      sleep: async (ms) => { delays.push(ms); },
    });
    assert.deepEqual(result, { pdf: "/x/sheet_export.pdf", kept_count: 4, revision: 3 });
    assert.equal(bridge.calls[0].pathname, "/jobs/job-1/review-export");
    assert.equal(bridge.calls[0].options.method, "POST");
    assert.deepEqual(bridge.calls.slice(1).map(call => [call.pathname, call.options.method]),
      Array(4).fill(["/jobs/job-1/review-export/t1", "GET"]));
    assert.deepEqual(seen, ["queued:queued:0", "running:planning:0.1", "running:sizing:0.45", "done:done:1"]);
    assert.deepEqual(delays, [500, 500, 750, 1000]);
  } finally {
    bridge.restore();
  }
});

test("a failed or cancelled background rebuild rejects with the backend's code and detail", async () => {
  let final = taskReply({ state: "failed", stage: "rendering", error_code: "LAYOUT_CONFLICT", error: "LAYOUT_CONFLICT: sys-002 do not fit the page at 1.5 mm", error_status: 409 });
  const bridge = withBridge((pathname) => (pathname.endsWith("/review-export") ? taskReply({ state: "queued", stage: "queued" }) : final));
  const options = { sleep: async () => {} };
  try {
    await assert.rejects(reviewExport("job-1", { keepCaptures: ["/a.png"] }, options),
      (error) => error.message.startsWith("LAYOUT_CONFLICT:") && error.status === 409 && error.code === "LAYOUT_CONFLICT");
    final = taskReply({ state: "cancelled", stage: "cancelled", cancel_requested: true, error_code: "EXPORT_CANCELLED" });
    await assert.rejects(reviewExport("job-1", { keepCaptures: ["/a.png"] }, options),
      (error) => error.code === "EXPORT_CANCELLED" && error.cancelled === true && !error.status);
    final = taskReply({ state: "failed", stage: "interrupted", error_code: "EXPORT_INTERRUPTED", error: "EXPORT_INTERRUPTED: 처리기가 다시 시작되어 ... / The processor restarted", error_status: 500 });
    await assert.rejects(reviewExport("job-1", { keepCaptures: ["/a.png"] }, options), (error) => error.code === "EXPORT_INTERRUPTED");
    // polling stops when the caller leaves (another source was opened)
    final = taskReply({ stage: "sizing" });
    await assert.rejects(reviewExport("job-1", { keepCaptures: ["/a.png"] }, { ...options, shouldStop: () => true }),
      (error) => error.code === "EXPORT_POLL_STOPPED");
  } finally {
    bridge.restore();
  }
});

test("review export task helpers: busy start, latest task, cancel, and an older backend's direct answer", async () => {
  let mode = "busy";
  const bridge = withBridge((pathname, options) => {
    if (mode === "busy") return { ok: false, status: 409, data: { detail: "EXPORT_IN_PROGRESS: 이 악보의 PDF를 이미 다시 만들고 있습니다. / This score's PDF is already being rebuilt. [task t1]" } };
    if (mode === "none") return { ok: false, status: 404, data: { detail: "EXPORT_TASK_NOT_FOUND: no review export for this job" } };
    if (mode === "legacy") return { ok: true, status: 200, data: { images: [], pdf: "/x.pdf", output_dir: "/x", kept_count: 2 } };
    if (pathname.endsWith("/cancel")) return taskReply({ cancel_requested: true, stage: "sizing" });
    return taskReply({ stage: "rendering", progress: 0.7 });
  });
  try {
    await assert.rejects(startReviewExport("job-1", { keepCaptures: ["/a.png"] }), (error) => error.code === "EXPORT_IN_PROGRESS" && error.status === 409);
    mode = "none";
    assert.equal(await getReviewExportTask("job-1"), null);
    mode = "task";
    const latest = await getReviewExportTask("job-1");
    assert.equal(bridge.calls.at(-1).pathname, "/jobs/job-1/review-export");
    assert.deepEqual([latest.taskId, latest.state, latest.stage, latest.progress], ["t1", "running", "rendering", 0.7]);
    const cancelled = await cancelReviewExport("job-1", "t1");
    assert.equal(bridge.calls.at(-1).pathname, "/jobs/job-1/review-export/t1/cancel");
    assert.equal(bridge.calls.at(-1).options.method, "POST");
    assert.equal(cancelled.cancelRequested, true);
    mode = "legacy";
    assert.equal((await reviewExport("job-1", { keepCaptures: ["/a.png"] })).kept_count, 2);
  } finally {
    bridge.restore();
  }
});

test("review export sends explicit size mode including 1.5 mm, and automatic mode when requested", async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  const calls = [];
  Object.defineProperty(globalThis, "window", { configurable: true, value: { drumSheetAPI: { requestJson: async (_path, options) => {
    calls.push(JSON.parse(options.body));
    return { ok: true, data: { images: [] } };
  } } } });
  try {
    for (const options of [{ staffGapMm: 1.5 }, { staffGapMm: 1.4 }, { staffGapMm: 1.5, staffGapMmExplicit: false }, {}, { staffGapMmExplicit: false }]) {
      await startReviewExport("job", { keepCaptures: ["/tmp/strip.png"], ...options });
    }
    assert.deepEqual(calls.map(body => body.staff_gap_mm_explicit), [true, true, false, undefined, false]);
    assert.deepEqual(calls.slice(0, 3).map(body => body.staff_gap_mm), [1.5, 1.4, 1.5]);
  } finally { if (previous) Object.defineProperty(globalThis, "window", previous); else delete globalThis.window; }
});

test("new jobs send explicit mode when a staff size is picked, preserving automatic choices", async () => {
  const { createJob } = await import("../lib/api.js");
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  const calls = [];
  Object.defineProperty(globalThis, "window", { configurable: true, value: { drumSheetAPI: { requestJson: async (_path, options) => {
    calls.push(JSON.parse(options.body)); return { ok: true, data: { job_id: "job" } };
  } } } });
  try {
    for (const options of [{}, { staff_gap_mm: 1.5 }, { staff_gap_mm: 1.4 }, { staff_gap_mm: 1.5, staff_gap_mm_explicit: false }]) {
      await createJob({ source_type: "file", file_path: "/tmp/v.mp4", options });
    }
    assert.deepEqual(calls.map(body => body.options.staff_gap_mm_explicit), [undefined, true, true, false]);
  } finally { if (previous) Object.defineProperty(globalThis, "window", previous); else delete globalThis.window; }
});
