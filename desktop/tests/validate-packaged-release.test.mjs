import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";

const validator = await import("../scripts/validate-packaged-release.js");

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

test("assertRuntimeContract rejects source-only packaged backends", () => {
  assert.throws(
    () =>
      validator.assertRuntimeContract({
        packagedBackendMainPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/app/main.py",
        runtimeExecutablePath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/runtime/drumsheet-backend/drumsheet-backend",
        runtimeExecutableExists: false,
        packagedVenvExists: false,
      }),
    /frozen backend runtime/i,
  );
});

test("assertRuntimeContract rejects packaged virtualenv payloads", () => {
  assert.throws(
    () =>
      validator.assertRuntimeContract({
        packagedBackendMainPath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/app/main.py",
        runtimeExecutablePath: "/tmp/dist/mac-arm64/Drum Sheet Capture.app/Contents/Resources/backend/runtime/drumsheet-backend/drumsheet-backend",
        runtimeExecutableExists: true,
        packagedVenvExists: true,
      }),
    /virtualenv/i,
  );
});
