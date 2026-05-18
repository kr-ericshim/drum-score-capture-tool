const fs = require("fs");

const RUNTIME_STALE_GRACE_MS = 60 * 1000;

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
  const staleRuntime = Boolean(
    runtimeMtimeMs &&
    sourceMtimeMs &&
    sourceMtimeMs - runtimeMtimeMs > RUNTIME_STALE_GRACE_MS,
  );

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
  RUNTIME_STALE_GRACE_MS,
};
