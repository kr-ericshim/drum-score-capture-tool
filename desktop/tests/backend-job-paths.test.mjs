import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { resolveBackendJobsDir } = require("../backend-job-paths.js");

test("resolveBackendJobsDir keeps development jobs next to the backend", () => {
  const backendDir = path.join("repo", "backend");

  assert.equal(
    resolveBackendJobsDir({
      app: { isPackaged: false },
      backendDir,
      env: {},
    }),
    path.join(backendDir, "jobs"),
  );
});

test("resolveBackendJobsDir stores packaged jobs under user data", () => {
  const userDataDir = path.join("Users", "eric", "Library", "Application Support", "Drum Sheet Capture");

  assert.equal(
    resolveBackendJobsDir({
      app: {
        isPackaged: true,
        getPath(name) {
          assert.equal(name, "userData");
          return userDataDir;
        },
      },
      backendDir: path.join("Applications", "Drum Sheet Capture.app", "Contents", "Resources", "backend"),
      env: {},
    }),
    path.join(userDataDir, "jobs"),
  );
});

test("resolveBackendJobsDir respects an explicit jobs directory override", () => {
  const override = path.join("tmp", "drumsheet-jobs");

  assert.equal(
    resolveBackendJobsDir({
      app: {
        isPackaged: true,
        getPath() {
          throw new Error("override should not need userData");
        },
      },
      backendDir: path.join("repo", "backend"),
      env: { DRUMSHEET_JOBS_DIR: override },
    }),
    override,
  );
});
