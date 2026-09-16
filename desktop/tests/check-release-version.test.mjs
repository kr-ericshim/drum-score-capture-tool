import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const { assertReleaseVersions } = createRequire(import.meta.url)("../scripts/check-release-version.js");
const versions = { manifestVersion: "0.1.31", lockVersion: "0.1.31", lockRootVersion: "0.1.31", backendVersion: "0.1.31" };

test("branch preflight accepts matching versions without a release tag", () => {
  assert.doesNotThrow(() => assertReleaseVersions({ ...versions, ref: "refs/heads/codex/release-check" }));
});

test("release tags require an exact version match, not a substring", () => {
  assert.doesNotThrow(() => assertReleaseVersions({ ...versions, ref: "refs/tags/v0.1.31" }));
  assert.throws(() => assertReleaseVersions({ ...versions, ref: "refs/tags/v0.1.3" }), /must match/);
});

test("stale backend or lockfile versions fail before packaging", () => {
  for (const field of ["backendVersion", "lockVersion", "lockRootVersion"]) {
    assert.throws(() => assertReleaseVersions({ ...versions, [field]: "0.1.30" }), /mismatch/);
  }
});
