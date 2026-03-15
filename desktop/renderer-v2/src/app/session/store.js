import { createInitialSessionState } from "./selectors.js";

export function createStore(initialState = createInitialSessionState()) {
  let state = structuredClone(initialState);
  const listeners = new Set();

  function notify() {
    for (const listener of listeners) {
      listener(state);
    }
  }

  return {
    getState() {
      return state;
    },
    setState(updater) {
      const nextState = typeof updater === "function" ? updater(structuredClone(state)) : structuredClone(updater);
      state = nextState;
      notify();
      return state;
    },
    update(path, value) {
      state = structuredClone(state);
      let target = state;
      for (let index = 0; index < path.length - 1; index += 1) {
        target = target[path[index]];
      }
      target[path[path.length - 1]] = value;
      notify();
      return state;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    reset(nextState = createInitialSessionState()) {
      state = structuredClone(nextState);
      notify();
    },
  };
}
