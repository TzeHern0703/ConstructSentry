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
export const getForecast = () => jget("/api/forecast");
export const getCarbon = () => jget("/api/carbon");

export const runScan = () => jpost("/api/scan");
export const runAttack = () => jpost("/api/attack");
export const runRemediate = () => jpost("/api/remediate");
export const runReset = () => jpost("/api/reset");
export const applyAction = (serverId, type) =>
  jpost(`/api/action?server_id=${encodeURIComponent(serverId)}&type=${type}`);
export const setAutopilot = (on) => jpost(`/api/autopilot?on=${on}`);
export const approveAction = (serverId) =>
  jpost(`/api/approve?server_id=${encodeURIComponent(serverId)}`);
export const denyAction = (serverId) =>
  jpost(`/api/deny?server_id=${encodeURIComponent(serverId)}`);

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
