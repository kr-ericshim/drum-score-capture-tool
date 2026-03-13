const NON_REVIEW_STEPS = new Set(["source", "roi", "export"]);
const ALL_STEPS = new Set(["source", "roi", "export", "review"]);

export function resolveWorkflowActiveStep({
  manualOpenStep,
  progressStep,
  hasResultOutput = false,
  openedStep = "",
} = {}) {
  const normalizedManual = String(manualOpenStep || "").trim();
  const normalizedProgress = String(progressStep || "").trim();
  const normalizedOpened = String(openedStep || "").trim();
  const fallbackStep = NON_REVIEW_STEPS.has(normalizedOpened)
    ? normalizedOpened
    : NON_REVIEW_STEPS.has(normalizedProgress)
      ? normalizedProgress
      : "source";

  if (normalizedManual === "review") {
    return hasResultOutput ? "review" : fallbackStep;
  }
  if (ALL_STEPS.has(normalizedManual)) {
    return normalizedManual;
  }
  if (hasResultOutput) {
    return "review";
  }
  return fallbackStep;
}
