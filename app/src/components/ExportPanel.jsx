import React, { useEffect, useState } from "react";
import { CheckCircle2, Copy, Download, FolderOpen, Loader2, Play, ShieldCheck, Sparkles, XCircle, Info } from "lucide-react";
import { api, desktop, url, waitForJob } from "../api.js";
import { useApp, useToast } from "../App.jsx";

function OriginalityCard({ project, clip }) {
  const [r, setR] = useState(null);
  const [showRules, setShowRules] = useState(false);
  const sig = JSON.stringify([clip.effects?.length, clip.audio?.vo_file, clip.captions?.enabled, clip.captions?.style,
    clip.captions?.language, clip.hook, clip.captions?.show_hook, project.credit, clip.start, clip.end]);
  useEffect(() => {
    const t = setTimeout(() => api.originality(project.id, clip.id).then(setR).catch(() => {}), 350);
    return () => clearTimeout(t);
  }, [project.id, clip.id, sig]);
  if (!r) return <div className="orig-card"><Loader2 size={16} className="spin" /></div>;
  const col = r.level === "great" ? "#4dffb8" : r.level === "ok" ? "#ffd23f" : "#ff5c7a";
  const C = 2 * Math.PI * 26;
  return (
    <div className="orig-card" style={{ "--oc": col }}>
      <div className="orig-head">
        <svg width="64" height="64" viewBox="0 0 64 64">
          <circle cx="32" cy="32" r="26" stroke="rgba(255,255,255,.1)" strokeWidth="6" fill="none" />
          <circle cx="32" cy="32" r="26" stroke={col} strokeWidth="6" fill="none" strokeLinecap="round"
            strokeDasharray={C} strokeDashoffset={C * (1 - r.score / 100)} transform="rotate(-90 32 32)" />
          <text x="32" y="38" textAnchor="middle" fill="#fff" fontSize="17" fontWeight="800">{r.score}</text>
        </svg>
        <div>
          <h4><ShieldCheck size={15} /> Originality check</h4>
          <p>{r.summary}</p>
        </div>
      </div>
      <div className="orig-list">
        {r.checks.map((c, i) => (
          <div key={i} className={"orig-item" + (c.ok ? " ok" : "")}>
            {c.ok ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
            <div>
              <div>{c.label}</div>
              {c.tip && <div className="muted tiny">{c.tip}</div>}
            </div>
          </div>
        ))}
      </div>
      <button className="link-btn" onClick={() => setShowRules((s) => !s)}><Info size={13} /> {showRules ? "Hide" : "Show"} YouTube rules in simple words</button>
      {showRules && <ul className="rules">{r.rules.map((x, i) => <li key={i}>{x}</li>)}</ul>}
      <p className="fine">Guidance only — YouTube reviewers make the final decision.</p>
    </div>
  );
}

function copy(text, toast) {
  navigator.clipboard.writeText(text).then(() => toast("Copied", "ok")).catch(() => {});
}

export default function ExportPanel({ project, clip, patch, replaceClip, setProject }) {
  const toast = useToast();
  const { settings } = useApp();
  const [busy, setBusy] = useState(null);
  const [title, setTitle] = useState(clip.title);
  const [credit, setCredit] = useState(project.credit || "");
  const meta = clip.meta || {};
  const lay = clip.layout || {};
  const cap = clip.captions || {};

  useEffect(() => setTitle(clip.title), [clip.id, clip.title]);
  useEffect(() => setCredit(project.credit || ""), [project.id, project.credit]);

  const saveCredit = async () => {
    if (credit === (project.credit || "")) return;
    const p = await api.updateProject(project.id, { credit });
    setProject((x) => ({ ...x, credit: p.credit }));
  };

  const genMeta = async () => {
    setBusy({ kind: "meta" });
    try {
      const j = await api.metadata(project.id, clip.id, cap.language || "original");
      const d = await waitForJob(j.id);
      replaceClip(d.result.clip);
    } catch (e) { toast(e.message, "error"); }
    finally { setBusy(null); }
  };

  const exportClip = async () => {
    if (title !== clip.title) await patch({ title });
    setBusy({ kind: "export", progress: 0, stage: "Starting render…" });
    try {
      if (!clip.meta?.title) {
        const j = await api.metadata(project.id, clip.id, cap.language || "original");
        await waitForJob(j.id).catch(() => {});
      }
      const j = await api.exportClips(project.id, [clip.id]);
      const done = await waitForJob(j.id, (x) => setBusy({ kind: "export", progress: x.progress, stage: x.stage }));
      const fresh = await api.project(project.id);
      const c = fresh.clips.find((x) => x.id === clip.id);
      if (c) replaceClip(c);
      toast("Clip exported! 🎉", "ok");
      const f = done.result?.files?.[0];
      if (f && desktop) desktop.showItem(f.path);
    } catch (e) {
      toast(e.message, "error");
    } finally { setBusy(null); }
  };

  const tags = (meta.hashtags || []).join(" ");

  return (
    <>
      <OriginalityCard project={project} clip={clip} />

      <div className="field">
        <label>Original creator (credit)</label>
        <input className="input" value={credit} placeholder="e.g. @CreatorName — used in the description" maxLength={100}
          onChange={(e) => setCredit(e.target.value)} onBlur={saveCredit} />
      </div>

      <div className="field">
        <label>File name</label>
        <input className="input" value={title} maxLength={90} onChange={(e) => setTitle(e.target.value)} onBlur={() => title !== clip.title && patch({ title })} />
      </div>
      <div className="field two">
        <div><label>Start</label><input className="input mono" type="number" step="0.1" value={clip.start} onChange={(e) => patch({ start: Number(e.target.value) }, true)} /></div>
        <div><label>End</label><input className="input mono" type="number" step="0.1" value={clip.end} onChange={(e) => patch({ end: Number(e.target.value) }, true)} /></div>
      </div>

      <div className="field">
        <div className="row between">
          <label>Upload details</label>
          <button className="btn ghost sm" onClick={genMeta} disabled={!!busy}>
            {busy?.kind === "meta" ? <Loader2 size={13} className="spin" /> : <Sparkles size={13} />} {meta.title ? "Regenerate" : "Generate"}
          </button>
        </div>
        {!settings.has_api_key && <p className="hint">Without a Claude key, simple details are made offline.</p>}
        <div className="meta-box">
          <div className="meta-row">
            <span className="muted tiny">Title</span>
            <input className="input" value={meta.title || ""} placeholder="Shorts title" maxLength={100}
              onChange={(e) => patch({ meta: { title: e.target.value } }, true)} />
            <button className="icon-btn" onClick={() => copy(meta.title || "", toast)}><Copy size={14} /></button>
          </div>
          <div className="meta-row">
            <span className="muted tiny">Description</span>
            <textarea className="input ta" value={meta.description || ""} rows={3}
              onChange={(e) => patch({ meta: { description: e.target.value } }, true)} />
            <button className="icon-btn" onClick={() => copy(meta.description || "", toast)}><Copy size={14} /></button>
          </div>
          <div className="meta-row">
            <span className="muted tiny">Hashtags</span>
            <input className="input" value={tags} onChange={(e) => patch({ meta: { hashtags: e.target.value.split(/\s+/).filter(Boolean) } }, true)} />
            <button className="icon-btn" onClick={() => copy(tags, toast)}><Copy size={14} /></button>
          </div>
        </div>
        <p className="hint">Saved next to the video as a .txt file when you export.</p>
      </div>

      <div className="export-box">
        <div className="row between"><span className="muted">Format</span><b>{{ short: "1080×1920 Short", square: "1080×1080", landscape: "1920×1080" }[lay.format || "short"]}</b></div>
        <div className="row between"><span className="muted">Effects</span><b>{clip.effects?.length || 0}</b></div>
        <div className="row between"><span className="muted">Voice / reaction</span><b>{clip.audio?.vo_file ? (clip.audio.vo_has_video ? "Camera + mic" : "Mic") : "None"}</b></div>
        <button className="btn primary lg full" onClick={exportClip} disabled={!!busy}>
          {busy?.kind === "export" ? <Loader2 size={18} className="spin" /> : <Download size={18} />}
          {busy?.kind === "export" ? `${Math.round(busy.progress * 100)}%` : "Export clip"}
        </button>
        {busy?.kind === "export" && (
          <>
            <div className="pbar"><span style={{ width: `${busy.progress * 100}%` }} /></div>
            <p className="hint">{busy.stage}</p>
          </>
        )}
      </div>

      {clip.exports?.length > 0 && (
        <div className="field">
          <label>Exported files</label>
          {clip.exports.slice().reverse().map((e, i) => (
            <div key={i} className="exp-row">
              {e.thumb && <img src={url.file(e.thumb)} alt="" />}
              <div className="exp-info">
                <div className="exp-name" title={e.path}>{e.path.split(/[\\/]/).pop()}</div>
                <div className="muted tiny">{new Date(e.at * 1000).toLocaleString()} · {e.duration}s</div>
              </div>
              {desktop && <button className="icon-btn" title="Play" onClick={() => desktop.openPath(e.path)}><Play size={15} /></button>}
              {desktop && <button className="icon-btn" title="Show in folder" onClick={() => desktop.showItem(e.path)}><FolderOpen size={15} /></button>}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
