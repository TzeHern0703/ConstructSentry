// Thin client for the ConstructSentry FastAPI layer. Paths are relative so the
// Vite dev proxy (vite.config.js) forwards them to the backend on :8000.

async function jget(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

async function jpost(path) {
  const res = await fetch(path, { method: "POST" });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export const getSummary = () => jget("/api/summary");
export const getState = () => jget("/api/state");
export const getFindings = () => jget("/api/findings");
export const getRegions = () => jget("/api/regions");

export const runScan = () => jpost("/api/scan");
export const runAttack = () => jpost("/api/attack");
export const runRemediate = () => jpost("/api/remediate");
export const runReset = () => jpost("/api/reset");

// Subscribe to the live agent-thought SSE stream. Returns the EventSource so
// the caller can close it on unmount.
export function openStream(onEvent) {
  const es = new EventSource("/api/stream");
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch {
      /* ignore keepalives / malformed frames */
    }
  };
  return es;
}
