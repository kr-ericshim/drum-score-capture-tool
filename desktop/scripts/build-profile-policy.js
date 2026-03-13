"use strict";

const SUPPORTED_BUILD_PROFILES = new Set(["full", "compact", "lean", "release"]);

function resolveBuildProfilePolicy(profile) {
  const requestedProfile = String(profile || "full").toLowerCase();
  if (!SUPPORTED_BUILD_PROFILES.has(requestedProfile)) {
    throw new Error(`unsupported build profile: ${requestedProfile}`);
  }

  return {
    requestedProfile,
    builderProfile: requestedProfile === "release" ? "compact" : requestedProfile,
    requiresFrozenBackend: true,
  };
}

module.exports = {
  SUPPORTED_BUILD_PROFILES,
  resolveBuildProfilePolicy,
};
