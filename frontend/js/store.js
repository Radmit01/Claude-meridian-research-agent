// Minimal shared state with subscriptions. Holds what more than one
// component needs: the active run and a cached corpus listing.
import { api } from "./api.js";

const listeners = new Map();
const state = { activeRun: null, corpus: null, health: null };

export function getState() {
  return state;
}

export function setState(patch) {
  Object.assign(state, patch);
  Object.keys(patch).forEach((k) => (listeners.get(k) || []).forEach((fn) => fn(state[k])));
}

/** Subscribe to one key; returns an unsubscribe function. */
export function subscribe(key, fn) {
  if (!listeners.has(key)) listeners.set(key, new Set());
  listeners.get(key).add(fn);
  return () => listeners.get(key).delete(fn);
}

let corpusPromise = null;
/** Cached corpus listing; pass force=true after an upload/sync. */
export function loadCorpus(force = false) {
  if (force || !corpusPromise) {
    corpusPromise = api.corpus.list().then((c) => { setState({ corpus: c }); return c; })
      .catch((e) => { corpusPromise = null; throw e; });
  }
  return corpusPromise;
}

export function updateCorpus(listing) {
  corpusPromise = Promise.resolve(listing);
  setState({ corpus: listing });
}

let healthPromise = null;
/** Cached /api/health — used to gate corpus-edit controls on
 * allow_corpus_edits (the fixed-corpus hackathon rule; off by default). */
export function loadHealth(force = false) {
  if (force || !healthPromise) {
    healthPromise = api.health().then((h) => { setState({ health: h }); return h; })
      .catch((e) => { healthPromise = null; throw e; });
  }
  return healthPromise;
}

export async function pollActiveRun() {
  try {
    const { active } = await api.runs.list();
    setState({ activeRun: active && (active.status === "running" || active.status === "queued") ? active : null });
  } catch (_) {
    setState({ activeRun: null });
  }
}
