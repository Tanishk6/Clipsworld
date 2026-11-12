// Talks to the local Clipsworld engine (Python, 127.0.0.1).
const params = new URLSearchParams(window.location.search);
export const desktop = window.clipsworld || null;
export const PORT = (desktop && desktop.port) || Number(params.get("port")) || 8765;
export const BASE = `http://127.0.0.1:${PORT}`;

async function req(method, path, body) {
  const r = await fetch(BASE + path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      msg = j.detail || msg;
    } catch (_) { /* not json */ }
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  health: () => req("GET", "/health"),
  settings: () => req("GET", "/settings"),
  saveSettings: (s) => req("PUT", "/settings", s),
  testKey: (s) => req("POST", "/settings/test-key", s || {}),
  styles: () => req("GET", "/styles"),
  gpu: () => req("GET", "/gpu"),
  installGpu: () => req("POST", "/gpu/install"),
  projects: () => req("GET", "/projects"),
  createProject: (source) => req("POST", "/projects", { source }),
  project: (id) => req("GET", `/projects/${id}`),
  deleteProject: (id) => req("DELETE", `/projects/${id}`),
  reanalyze: (id, from) => req("POST", `/projects/${id}/analyze`, { from }),
  waveform: (id) => req("GET", `/projects/${id}/waveform?points=4000`),
  addClip: (id, start, end) => req("POST", `/projects/${id}/clips`, { start, end }),
  updateClip: (id, cid, patch) => req("PUT", `/projects/${id}/clips/${cid}`, patch),
  deleteClip: (id, cid) => req("DELETE", `/projects/${id}/clips/${cid}`),
  rebuildCaptions: (id, cid) => req("POST", `/projects/${id}/clips/${cid}/captions/rebuild`),
  translate: (id, cid, target) => req("POST", `/projects/${id}/clips/${cid}/translate`, { target }),
  exportClips: (id, clip_ids) => req("POST", `/projects/${id}/export`, { clip_ids }),
  exports: () => req("GET", "/exports"),
  updateProject: (id, patch) => req("PUT", `/projects/${id}`, patch),
  preview: (id, cid) => req("POST", `/projects/${id}/clips/${cid}/preview`),
  autoEdit: (id, cid) => req("POST", `/projects/${id}/clips/${cid}/auto-edit`),
  metadata: (id, cid, language) => req("POST", `/projects/${id}/clips/${cid}/metadata`, { language }),
  originality: (id, cid) => req("GET", `/projects/${id}/clips/${cid}/originality`),
  importVoiceover: (id, cid, path) => req("POST", `/projects/${id}/clips/${cid}/voiceover/import`, { path }),
  deleteVoiceover: (id, cid) => req("DELETE", `/projects/${id}/clips/${cid}/voiceover`),
  uploadVoiceover: async (id, cid, blob, ext, hasVideo) => {
    const r = await fetch(`${BASE}/projects/${id}/clips/${cid}/voiceover?ext=${ext}&video=${hasVideo ? 1 : 0}`, {
      method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: blob,
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "Upload failed");
    return r.json();
  },
  sfx: () => req("GET", "/sfx"),
  effectDefaults: () => req("GET", "/effects/defaults"),
  jobs: () => req("GET", "/jobs"),
  job: (id) => req("GET", `/jobs/${id}`),
  cancelJob: (id) => req("POST", `/jobs/${id}/cancel`),
};

export const url = {
  media: (id) => `${BASE}/projects/${id}/media`,
  cover: (id, v = "") => `${BASE}/projects/${id}/cover?v=${v}`,
  thumb: (id, cid, v = "") => `${BASE}/projects/${id}/thumb/${cid}?v=${v}`,
  file: (p) => `${BASE}/file?path=${encodeURIComponent(p)}`,
  font: (n) => `${BASE}/fonts/${n}`,
  sfx: (id) => `${BASE}/sfx/${encodeURIComponent(id)}`,
  frame: (id, t) => `${BASE}/projects/${id}/frame?t=${t}`,
};

export function waitForJob(id, onTick, interval = 700) {
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const j = await api.job(id);
        onTick && onTick(j);
        if (j.status === "running") return setTimeout(tick, interval);
        if (j.status === "done") resolve(j);
        else reject(new Error(j.error || j.status));
      } catch (e) {
        setTimeout(tick, interval * 2);
      }
    };
    tick();
  });
}

export function fmtTime(t, withMs = false) {
  if (t == null || isNaN(t)) return "0:00";
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = t % 60;
  const ss = withMs ? s.toFixed(1).padStart(4, "0") : String(Math.floor(s)).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}
