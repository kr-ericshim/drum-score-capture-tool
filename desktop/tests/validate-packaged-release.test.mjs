import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import asar from "@electron/asar";

const validator = await import("../scripts/validate-packaged-release.js");

test("describeValidationMode distinguishes pack from dist release expectations", () => {
  assert.deepEqual(validator.describeValidationMode("pack"), {
    action: "pack",
    requiresInstallerArtifacts: false,
    requiresReleaseMetadata: false,
  });
  assert.deepEqual(validator.describeValidationMode("dist"), {
    action: "dist",
    requiresInstallerArtifacts: true,
    requiresReleaseMetadata: false,
  });
});

test("findPackagedRuntimeExecutable resolves the packaged frozen backend path", () => {
  const macRuntimePath = validator.findPackagedRuntimeExecutable({
    distDir: "/tmp/dist",
    packagedBackendMainPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/app/main.py",
    platform: "darwin",
  });

  assert.equal(
    macRuntimePath,
    path.posix.join(
      "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend",
      "runtime",
      "drumsheet-backend",
      "drumsheet-backend",
    ),
  );

  assert.equal(
    validator.findPackagedRuntimeExecutable({
      distDir: "C:\\dist",
      packagedBackendMainPath: "C:\\dist\\win-unpacked\\resources\\backend\\app\\main.py",
      platform: "win32",
    }),
    "C:\\dist\\win-unpacked\\resources\\backend\\runtime\\drumsheet-backend\\drumsheet-backend.exe",
  );
});

test("findPackagedBackendToolExecutable resolves bundled ffmpeg/ffprobe payload paths", () => {
  assert.equal(
    validator.findPackagedBackendToolExecutable({
      packagedBackendMainPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/app/main.py",
      toolName: "ffmpeg",
      platform: "darwin",
    }),
    "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/bin/ffmpeg",
  );
  assert.equal(
    validator.findPackagedBackendToolExecutable({
      packagedBackendMainPath: "C:\\dist\\win-unpacked\\resources\\backend\\app\\main.py",
      toolName: "ffprobe",
      platform: "win32",
    }),
    "C:\\dist\\win-unpacked\\resources\\backend\\bin\\ffprobe.exe",
  );
});

test("findPackagedRendererV2Index resolves the packaged renderer-v2 entry path", () => {
  assert.equal(
    validator.findPackagedRendererV2Index({
      packagedBackendMainPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/app/main.py",
      platform: "darwin",
    }),
    "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/renderer-v2/index.html",
  );

  assert.equal(
    validator.findPackagedRendererV2Index({
      packagedBackendMainPath: "C:\\dist\\win-unpacked\\resources\\backend\\app\\main.py",
      platform: "win32",
    }),
    "C:\\dist\\win-unpacked\\resources\\renderer-v2\\index.html",
  );
});

test("findPackagedAppAsar resolves the packaged asar next to resources", () => {
  assert.equal(
    validator.findPackagedAppAsar({
      packagedBackendMainPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/app/main.py",
      platform: "darwin",
    }),
    "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/app.asar",
  );

  assert.equal(
    validator.findPackagedAppAsar({
      packagedBackendMainPath: "C:\\dist\\win-unpacked\\resources\\backend\\app\\main.py",
      platform: "win32",
    }),
    "C:\\dist\\win-unpacked\\resources\\app.asar",
  );
});

test("hasPackagedRendererV2Index accepts renderer-v2 inside app.asar", async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "drumsheet-asar-"));
  const sourceRoot = path.join(tempRoot, "source");
  const rendererRoot = path.join(sourceRoot, "renderer-v2");
  fs.mkdirSync(rendererRoot, { recursive: true });
  fs.writeFileSync(path.join(rendererRoot, "index.html"), "<div id=\"app\"></div>");

  const appAsarPath = path.join(tempRoot, "app.asar");
  await asar.createPackage(sourceRoot, appAsarPath);

  assert.equal(
    validator.hasPackagedRendererV2Index({
      rendererV2IndexPath: path.join(tempRoot, "missing", "renderer-v2", "index.html"),
      appAsarPath,
    }),
    true,
  );
});

test("hasPackagedRendererV2Index accepts Windows-style paths inside app.asar", () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "drumsheet-asar-"));
  const appAsarPath = path.join(tempRoot, "app.asar");
  fs.writeFileSync(appAsarPath, "");

  const originalListPackage = asar.listPackage;
  asar.listPackage = () => ["\\renderer-v2", "\\renderer-v2\\index.html"];

  try {
    assert.equal(
      validator.hasPackagedRendererV2Index({
        rendererV2IndexPath: path.join(tempRoot, "missing", "renderer-v2", "index.html"),
        appAsarPath,
      }),
      true,
    );
  } finally {
    asar.listPackage = originalListPackage;
  }
});

test("findPackagedVenvPath resolves platform-specific packaged virtualenv paths", () => {
  assert.equal(
    validator.findPackagedVenvPath(
      "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/app/main.py",
      "darwin",
    ),
    "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/.venv",
  );

  assert.equal(
    validator.findPackagedVenvPath(
      "C:\\dist\\win-unpacked\\resources\\backend\\app\\main.py",
      "win32",
    ),
    "C:\\dist\\win-unpacked\\resources\\backend\\.venv",
  );
});

test("assertRuntimeContract rejects source-only packaged backends", () => {
  assert.throws(
    () =>
      validator.assertRuntimeContract({
        packagedBackendMainPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/app/main.py",
        runtimeExecutablePath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/runtime/drumsheet-backend/drumsheet-backend",
        runtimeExecutableExists: false,
        packagedFfmpegPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/bin/ffmpeg",
        packagedFfmpegExists: true,
        packagedFfprobePath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/bin/ffprobe",
        packagedFfprobeExists: true,
        packagedVenvExists: false,
      }),
    /frozen backend runtime/i,
  );
});

test("assertRuntimeContract rejects packaged releases missing bundled ffmpeg", () => {
  assert.throws(
    () =>
      validator.assertRuntimeContract({
        packagedBackendMainPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/app/main.py",
        runtimeExecutablePath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/runtime/drumsheet-backend/drumsheet-backend",
        runtimeExecutableExists: true,
        packagedFfmpegPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/bin/ffmpeg",
        packagedFfmpegExists: false,
        packagedFfprobePath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/bin/ffprobe",
        packagedFfprobeExists: true,
        packagedVenvExists: false,
      }),
    /ffmpeg/i,
  );
});

test("assertRuntimeContract rejects packaged releases missing bundled ffprobe", () => {
  assert.throws(
    () =>
      validator.assertRuntimeContract({
        packagedBackendMainPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/app/main.py",
        runtimeExecutablePath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/runtime/drumsheet-backend/drumsheet-backend",
        runtimeExecutableExists: true,
        packagedFfmpegPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/bin/ffmpeg",
        packagedFfmpegExists: true,
        packagedFfprobePath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/bin/ffprobe",
        packagedFfprobeExists: false,
        packagedVenvExists: false,
      }),
    /ffprobe/i,
  );
});

test("assertRuntimeContract rejects packaged virtualenv payloads", () => {
  assert.throws(
    () =>
      validator.assertRuntimeContract({
        packagedBackendMainPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/app/main.py",
        runtimeExecutablePath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/runtime/drumsheet-backend/drumsheet-backend",
        runtimeExecutableExists: true,
        packagedFfmpegPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/bin/ffmpeg",
        packagedFfmpegExists: true,
        packagedFfprobePath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/bin/ffprobe",
        packagedFfprobeExists: true,
        packagedVenvExists: true,
      }),
    /virtualenv/i,
  );
});

test("assertRuntimeFreshness accepts a frozen runtime that is at least as new as backend source", () => {
  assert.doesNotThrow(() =>
    validator.assertRuntimeFreshness({
      runtimeExecutablePath: "/tmp/runtime/drumsheet-backend",
      sourceEntryPath: "/tmp/backend/app/main.py",
      runtimeMtimeMs: Date.parse("2026-05-18T04:00:00.000Z"),
      sourceMtimeMs: Date.parse("2026-05-18T03:59:59.000Z"),
    }),
  );
});

test("assertRuntimeFreshness rejects a frozen runtime older than backend source", () => {
  assert.throws(
    () =>
      validator.assertRuntimeFreshness({
        runtimeExecutablePath: "/tmp/runtime/drumsheet-backend",
        sourceEntryPath: "/tmp/backend/app/main.py",
        runtimeMtimeMs: Date.parse("2026-05-18T03:59:59.000Z"),
        sourceMtimeMs: Date.parse("2026-05-18T04:00:00.000Z"),
      }),
    /runtime is older than backend source/i,
  );
});

test("assertPackagedSourceTextCompatibility compares packaged YouTube strategy to current source", () => {
  assert.doesNotThrow(() =>
    validator.assertPackagedSourceTextCompatibility({
      sourceMainText: "PREVIEW_SOURCE_CACHE_NAMESPACE = YOUTUBE_DOWNLOAD_STRATEGY_VERSION",
      packagedMainText: "PREVIEW_SOURCE_CACHE_NAMESPACE = YOUTUBE_DOWNLOAD_STRATEGY_VERSION",
      sourceExtractText: [
        'YOUTUBE_DOWNLOAD_STRATEGY_VERSION = "yt-v4"',
        'base_opts["ffmpeg_location"] = ffmpeg_location',
        'format": "bestvideo+bestaudio/best"',
      ].join("\n"),
      packagedExtractText: [
        'YOUTUBE_DOWNLOAD_STRATEGY_VERSION = "yt-v4"',
        'base_opts["ffmpeg_location"] = ffmpeg_location',
        'format": "bestvideo+bestaudio/best"',
      ].join("\n"),
    }),
  );

  assert.throws(
    () =>
      validator.assertPackagedSourceTextCompatibility({
        sourceMainText: "PREVIEW_SOURCE_CACHE_NAMESPACE = YOUTUBE_DOWNLOAD_STRATEGY_VERSION",
        packagedMainText: "PREVIEW_SOURCE_CACHE_NAMESPACE = YOUTUBE_DOWNLOAD_STRATEGY_VERSION",
        sourceExtractText: 'YOUTUBE_DOWNLOAD_STRATEGY_VERSION = "yt-v4"',
        packagedExtractText: 'YOUTUBE_DOWNLOAD_STRATEGY_VERSION = "yt-v3"',
      }),
    /does not match source yt-v4/i,
  );
});

test("assertPackagedSourceTextCompatibility labels source-text proxy marker failures", () => {
  assert.throws(
    () =>
      validator.assertPackagedSourceTextCompatibility({
        sourceMainText: "PREVIEW_SOURCE_CACHE_NAMESPACE = YOUTUBE_DOWNLOAD_STRATEGY_VERSION",
        packagedMainText: "PREVIEW_SOURCE_CACHE_NAMESPACE = YOUTUBE_DOWNLOAD_STRATEGY_VERSION",
        sourceExtractText: [
          'YOUTUBE_DOWNLOAD_STRATEGY_VERSION = "yt-v4"',
          'base_opts["ffmpeg_location"] = ffmpeg_location',
        ].join("\n"),
        packagedExtractText: 'YOUTUBE_DOWNLOAD_STRATEGY_VERSION = "yt-v4"',
      }),
    /source-text compatibility check failed: missing bundled ffmpeg handoff marker/i,
  );
});

test("assertRendererContract rejects packaged releases missing renderer-v2 assets", () => {
  assert.throws(
    () =>
      validator.assertRendererContract({
        rendererV2IndexPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/renderer-v2/index.html",
        rendererV2Exists: false,
      }),
    /renderer-v2\/index\.html/i,
  );
});

test("assertInstallerArtifacts requires a platform installer with the desktop version", () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "drumsheet-installer-"));
  fs.writeFileSync(path.join(tempRoot, "Drum Sheet Capture-0.9.0-arm64.dmg"), "stale");
  fs.mkdirSync(path.join(tempRoot, "nested"));
  fs.writeFileSync(path.join(tempRoot, "Drum Sheet Capture-1.0.0-empty.dmg"), "");
  fs.writeFileSync(path.join(tempRoot, "nested", "Drum Sheet Capture-1.0.0-arm64.dmg"), "nested");

  assert.throws(
    () =>
      validator.assertInstallerArtifacts({
        candidateDistDir: tempRoot,
        desktopVersion: "1.0.0",
        platform: "darwin",
      }),
    /root-level.*installer artifact/i,
  );

  const installerPath = path.join(tempRoot, "Drum Sheet Capture-1.0.0-arm64.dmg");
  fs.writeFileSync(installerPath, "ok");

  assert.deepEqual(
    validator.assertInstallerArtifacts({
      candidateDistDir: tempRoot,
      desktopVersion: "1.0.0",
      platform: "darwin",
    }),
    [installerPath],
  );
});
