import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, Loader2, Pause, Play, RotateCcw } from "lucide-react";
import { api } from "../api.js";

const Ctx = createContext({ list: [], refresh: () => {} });
export const useDownloads = () => useContext(Ctx);

// Polls the engine for background downloads (GPU pack, speech model) for the whole app.
export function DownloadsProvider({ children }) {
  const [list, setList] = useState([]);
  const refresh = useCallback(async () => {
    try { setList(await api.downloads()); } catch (_) { /* engine busy */ }
  }, []);
  useEffect(() => {
    let alive = true;
    let timer;
    const loop = async () => {
      await refresh();
      if (!alive) return;
      const active = (window.__cwDownloads || []).some((d) => d.state === "downloading" || d.state === "preparing");
      timer = setTimeout(loop, active ? 1200 : 5000);
    };
    loop();
    return () => { alive = false; clearTimeout(timer); };
  }, [refresh]);
  useEffect(() => { window.__cwDownloads = list; }, [list]);
  return <Ctx.Provider value={{ list, refresh }}>{children}</Ctx.Provider>;
}

const mb = (b) => (b / 1048576).toFixed(b > 1048576 * 100 ? 0 : 1);

export function DownloadRow({ dkey, title, hint, startLabel = "Download" }) {
  const { list, refresh } = useDownloads();
  const d = list.find((x) => x.key === dkey) || { state: "idle", done_bytes: 0, total_bytes: 0 };
  const [busy, setBusy] = useState(false);
  const act = async (fn) => {
    setBusy(true);
    try { await fn(dkey); await refresh(); } catch (_) { /* shown via state */ }
    finally { setTimeout(() => setBusy(false), 600); }
  };
  const pct = Math.round((d.progress || 0) * 100);
  const running = d.state === "downloading" || d.state === "preparing";
  return (
    <div className={"dl-row " + d.state}>
      <div className="dl-top">
        <div className="dl-title">
          {d.state === "done" ? <CheckCircle2 size={16} className="ok" /> : d.state === "error" ? <AlertTriangle size={16} className="bad" /> : running ? <Loader2 size={16} className="spin" /> : <Download size={16} />}
          <span>{title}</span>
        </div>
        <div className="dl-actions">
          {d.state === "done" && <span className="chip ok">Ready ✓</span>}
          {d.state === "idle" && <button className="btn primary sm" disabled={busy} onClick={() => act(api.startDownload)}><Download size={13} /> {startLabel}</button>}
          {d.state === "downloading" && <button className="btn sm" disabled={busy} onClick={() => act(api.pauseDownload)}><Pause size={13} /> Pause</button>}
          {d.state === "paused" && <button className="btn primary sm" disabled={busy} onClick={() => act(api.startDownload)}><Play size={13} /> Resume</button>}
          {d.state === "error" && <button className="btn primary sm" disabled={busy} onClick={() => act(api.startDownload)}><RotateCcw size={13} /> Retry</button>}
          {d.state === "preparing" && <span className="chip">Installing…</span>}
        </div>
      </div>
      {d.state !== "done" && d.state !== "idle" && (
        <>
          <div className="pbar"><span style={{ width: `${pct}%` }} /></div>
          <div className="dl-meta muted tiny">
            <span>{d.total_bytes ? `${mb(d.done_bytes)} / ${mb(d.total_bytes)} MB · ${pct}%` : "Starting…"}</span>
            <span>{d.state === "downloading" && d.speed ? `${(d.speed / 1048576).toFixed(1)} MB/s` : d.stage}</span>
          </div>
        </>
      )}
      {d.state === "error" && <p className="err-small">{d.error}</p>}
      {hint && d.state !== "done" && <p className="hint">{hint}</p>}
    </div>
  );
}

// Small indicator in the sidebar while something downloads in the background.
export function DownloadsBadge({ onClick }) {
  const { list } = useDownloads();
  const active = list.filter((d) => d.state === "downloading" || d.state === "preparing" || d.state === "paused");
  if (!active.length) return null;
  const done = active.reduce((a, d) => a + d.done_bytes, 0);
  const total = active.reduce((a, d) => a + d.total_bytes, 0) || 1;
  const pct = Math.round((done / total) * 100);
  const paused = active.every((d) => d.state === "paused");
  const C = 2 * Math.PI * 15;
  return (
    <button className="dl-badge" onClick={onClick} title={active.map((d) => `${d.label}: ${d.state}`).join("\n")}>
      <svg width="38" height="38" viewBox="0 0 38 38">
        <circle cx="19" cy="19" r="15" stroke="rgba(255,255,255,.12)" strokeWidth="3.5" fill="none" />
        <circle cx="19" cy="19" r="15" stroke={paused ? "#ffd23f" : "#2de2ff"} strokeWidth="3.5" fill="none" strokeLinecap="round"
          strokeDasharray={C} strokeDashoffset={C * (1 - pct / 100)} transform="rotate(-90 19 19)" />
      </svg>
      <span className="dl-badge-ic">{paused ? <Pause size={13} /> : <Download size={13} />}</span>
      <span className="dl-badge-txt">{pct}%</span>
    </button>
  );
}
