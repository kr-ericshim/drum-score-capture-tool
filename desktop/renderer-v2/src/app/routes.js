import { STEP_ORDER } from "./types.js";
import { getAccessibleSteps } from "./session/selectors.js";

export function resolveStep(step) {
  return STEP_ORDER.includes(step) ? step : STEP_ORDER[0];
}

export function canOpenStep(state, step) {
  return getAccessibleSteps(state).includes(resolveStep(step));
}
