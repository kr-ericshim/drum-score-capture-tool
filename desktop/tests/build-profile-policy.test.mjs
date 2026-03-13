import test from "node:test";
import assert from "node:assert/strict";

const policy = await import("../scripts/build-profile-policy.js");

test("release profile maps to compact builder output and requires a frozen backend", () => {
  assert.deepEqual(policy.resolveBuildProfilePolicy("release"), {
    requestedProfile: "release",
    builderProfile: "compact",
    requiresFrozenBackend: true,
  });
});

test("all packaged profiles require a fresh frozen backend runtime build", () => {
  for (const profile of ["full", "compact", "lean", "release"]) {
    assert.equal(
      policy.resolveBuildProfilePolicy(profile).requiresFrozenBackend,
      true,
      `${profile} should rebuild the frozen backend runtime`,
    );
  }
});
