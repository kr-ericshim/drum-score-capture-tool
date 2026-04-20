import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";

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
    requiresReleaseMetadata: true,
  });
});

test("findPackagedRuntimeExecutable resolves the packaged frozen backend path", () => {
  const runtimePath = validator.findPackagedRuntimeExecutable({
    distDir: "/tmp/dist",
    packagedBackendMainPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/app/main.py",
    platform: "darwin",
  });

  assert.equal(
    runtimePath,
    path.join(
      "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend",
      "runtime",
      "drumsheet-backend",
      "drumsheet-backend",
    ),
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
