const fs = require("fs");

function fileMtimeMs(filePath = "") {
  if (!filePath) {
    return 0;
  }
  try {
    return Number(fs.statSync(filePath).mtimeMs || 0);
  } catch (_) {
    return 0;
  }
}

function decidePackagedBackendLaunchMode({
  runtimeExecutablePath = "",
  sourceEntryPath = "",
  pythonAvailable = false,
} = {}) {
  const runtimeMtimeMs = fileMtimeMs(runtimeExecutablePath);
  const sourceMtimeMs = fileMtimeMs(sourceEntryPath);
  const staleRuntime = Boolean(runtimeMtimeMs && sourceMtimeMs && sourceMtimeMs > runtimeMtimeMs);

  if (staleRuntime && pythonAvailable) {
    return {
      mode: "python",
      reason: "runtime-stale",
      staleRuntime,
      runtimeMtimeMs,
      sourceMtimeMs,
    };
  }

  return {
    mode: "runtime",
    reason: staleRuntime ? "runtime-stale-no-python" : "runtime-current",
    staleRuntime,
    runtimeMtimeMs,
    sourceMtimeMs,
  };
}

module.exports = {
  decidePackagedBackendLaunchMode,
  fileMtimeMs,
};
