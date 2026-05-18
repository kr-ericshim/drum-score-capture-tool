import test from "node:test";
import assert from "node:assert/strict";

import { createPreviewSourceJob, getPreviewSourceJob, preparePreviewSource, requestPreviewFrame } from "../lib/api.js";

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
