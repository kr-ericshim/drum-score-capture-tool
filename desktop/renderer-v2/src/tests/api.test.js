import test from "node:test";
import assert from "node:assert/strict";

import { createPreviewSourceJob, getPreviewSourceJob, preparePreviewSource } from "../lib/api.js";

test("preparePreviewSource posts youtube payload and maps the backend response", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;

  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      drumSheetAPI: {
        apiBase: "http://127.0.0.1:8000",
        apiToken: "",
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
        apiToken: "",
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
        apiToken: "",
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
  } finally {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: previousWindow,
    });
    globalThis.fetch = previousFetch;
  }
});
