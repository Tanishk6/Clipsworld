import React, { useEffect, useState } from "react";
import { Captions, Download, FolderOpen, Languages, LayoutTemplate, Loader2, Play, RefreshCw, Sparkles, Type } from "lucide-react";
import { api, desktop, fmtTime, url, waitForJob } from "../api.js";
import { useApp, useToast } from "../App.jsx";

const LANGS = [
  { id: "original", label: "Original (as spoken)" },
  { id: "hinglish", label: "Hinglish (Roman Hindi)" },
  { id: "hi", label: "Hindi (हिंदी)" },
  { id: "en", label: "English" },
];

function Seg({ value, options, onChange }) {
  return (
    <div className="segmented">
      {options.map((o) => (
        <button key={o.id} className={value === o.id ? "on" : ""} onClick={() => onChange(o.id)}>{o.label}</button>
      ))}
    </div>
  );
}

function Toggle({ on, onChange, label }) {
  return (
    <label className="toggle" onClick={() => onChange(!on)}>
      <span className={"sw" + (on ? " on" : "")}><span /></span>
      {label}
    </label>
  );
}

function StyleCard({ id, def, active, onClick }) {
  const sample = def.upper ? "BHAI KYA HUA" : "bhai kya hua";
  const words = sample.split(" ");
  return (
    <button className={"style-card" + (active ? " on" : "")} onClick={onClick}>
      <div className="sc-prev">
        <span style={{
          fontFamily: `"${def.font}", sans-serif`, color: def.color, fontSize: Math.min(26, Math.max(11, def.size * 0.2)),
          WebkitTextStroke: def.box ? 0 : `${Math.max(1.5, def.bord / 3)}px ${def.outline}`, paintOrder: "stroke fill",
          background: def.box ? "rgba(0,0,0,.6)" : "none", padding: def.box ? "2px 8px" : 0, borderRadius: 4,
          textShadow: def.blur ? `0 0 8px ${def.color}` : "none",
        }}>
          {words.map((w, i) => (
            <React.Fragment key={i}>
              <span style={i === 1 && def.active ? { color: def.active, display: "inline-block", transform: "scale(1.12)", margin: "0 0.14em" } : i === 2 && def.karaoke ? { color: def.karaoke } : {}}>{w}</span>
              {i < words.length - 1 ? " " : ""}
            </React.Fragment>
          ))}
        </span>
      </div>
      <div className="sc-name">{def.label}</div>
    </button>
  );
}

export default function Inspector({ project, clip, patch, replaceClip, time }) {
  const toast = useToast();
  const { styles, settings } = useApp();
  const [tab, setTab] = useState("captions");
  const [busy, setBusy] = useState(null); // {kind, progress, stage}
  const cap = clip.captions || {};
  const lay = clip.layout || {};
  const [title, setTitle] = useState(clip.title);
  const [hook, setHook] = useState(clip.hook || "");

  useEffect(() => { setTitle(clip.title); setHook(clip.hook || ""); }, [clip.id, clip.title, clip.hook]);

  const translate = async (target) => {
    if (target !== "original" && !settings.has_api_key) return toast("Add your Claude API key in Settings to translate captions.", "error");
    setBusy({ kind: "translate", progress: 0, stage: "Translating…" });
    try {
      const j = await api.translate(project.id, clip.id, target);
      const done = await waitForJob(j.id, (x) => setBusy({ kind: "translate", progress: x.progress, stage: x.stage }));
      replaceClip(done.result);
      toast("Captions translated", "ok");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(null);
    }
  };

  const exportClip = async () => {
    if (title !== clip.title) await patch({ title });
    setBusy({ kind: "export", progress: 0, stage: "Starting render…" });
    try {
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
    } finally {
      setBusy(null);
    }
  };

  const rebuild = async () => {
    try {
      replaceClip(await api.rebuildCaptions(project.id, clip.id));
      toast("Captions rebuilt from speech", "ok");
    } catch (e) { toast(e.message, "error"); }
  };

  const editCue = (i, text) => {
    const cues = cap.cues.map((q, j) => (j === i ? { ...q, text, edited: true } : q));
    patch({ captions: { cues } }, true);
  };

  const styleDefs = styles?.styles || {};
  const activeCue = (cap.cues || []).findIndex((q) => time >= q.start && time < q.end);

  return (
    <div className="inspector">
      <div className="seg-tabs">
        <button className={tab === "captions" ? "on" : ""} onClick={() => setTab("captions")}><Captions size={15} /> Captions</button>
        <button className={tab === "layout" ? "on" : ""} onClick={() => setTab("layout")}><LayoutTemplate size={15} /> Layout</button>
        <button className={tab === "export" ? "on" : ""} onClick={() => setTab("export")}><Download size={15} /> Export</button>
      </div>

      <div className="insp-scroll">
        {tab === "captions" && (
          <>
            <div className="field row">
              <Toggle on={cap.enabled !== false} onChange={(v) => patch({ captions: { enabled: v } })} label="Show captions" />
            </div>
            <div className="field">
              <label>Style</label>
              <div className="style-grid">
                {Object.entries(styleDefs).map(([id, def]) => (
                  <StyleCard key={id} id={id} def={def} active={cap.style === id} onClick={() => patch({ captions: { style: id } })} />
                ))}
              </div>
            </div>
            <div className="field">
              <label>Position</label>
              <Seg value={cap.position || "bottom"} onChange={(v) => patch({ captions: { position: v } })}
                options={[{ id: "top", label: "Top" }, { id: "middle", label: "Middle" }, { id: "bottom", label: "Bottom" }]} />
            </div>
            <div className="field row">
              <Toggle on={cap.uppercase == null ? !!styleDefs[cap.style]?.upper : cap.uppercase} onChange={(v) => patch({ captions: { uppercase: v } })} label="ALL CAPS" />
            </div>
            <div className="field">
              <label><Languages size={14} /> Caption language</label>
              <div className="lang-row">
                <select value={cap.language || "original"} onChange={(e) => translate(e.target.value)} disabled={!!busy}>
                  {LANGS.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
                </select>
                {busy?.kind === "translate" && <Loader2 size={16} className="spin" />}
              </div>
              {!settings.has_api_key && <p className="hint"><Sparkles size={12} /> Translation uses Claude — add your API key in Settings.</p>}
            </div>
            <div className="field">
              <div className="row between">
                <Toggle on={!!cap.show_hook} onChange={(v) => patch({ captions: { show_hook: v } })} label="Hook text (first 3 sec)" />
              </div>
              {cap.show_hook && (
                <input className="input" value={hook} placeholder="e.g. Creeper ne sab uda diya 💀" maxLength={60}
                  onChange={(e) => setHook(e.target.value)} onBlur={() => hook !== (clip.hook || "") && patch({ hook })} />
              )}
            </div>
            <div className="field">
              <div className="row between">
                <label><Type size={14} /> Caption text</label>
                <button className="btn ghost sm" onClick={rebuild} title="Throw away edits and make captions again from the speech"><RefreshCw size={13} /> Rebuild</button>
              </div>
              <div className="cue-list">
                {(cap.cues || []).length === 0 && <div className="empty sm">No speech in this part.</div>}
                {(cap.cues || []).map((q, i) => (
                  <div key={i + ":" + q.start} className={"cue" + (i === activeCue ? " on" : "")}>
                    <span className="mono">{fmtTime(q.start - clip.start, true)}</span>
                    <input defaultValue={q.text} onBlur={(e) => e.target.value !== q.text && editCue(i, e.target.value)} />
                  </div>
                ))}
              </div>
            </div>
          </>
        )}

        {tab === "layout" && (
          <>
            <div className="field">
              <label>Format</label>
              <Seg value={lay.format || "short"} onChange={(v) => patch({ layout: { format: v } })}
                options={[{ id: "short", label: "Short 9:16" }, { id: "square", label: "Square 1:1" }, { id: "landscape", label: "Video 16:9" }]} />
            </div>
            <div className="field">
              <label>Fill mode</label>
              <Seg value={lay.mode || "blur"} onChange={(v) => patch({ layout: { mode: v } })}
                options={[{ id: "blur", label: "Blur fill" }, { id: "crop", label: "Crop" }, { id: "fit", label: "Fit" }]} />
              <p className="hint">{lay.mode === "crop" ? "Zooms into one part of the video. Move it with the slider." : lay.mode === "fit" ? "Whole video with black bars." : "Whole video in the middle, blurred copy behind it."}</p>
            </div>
            {lay.mode === "crop" && (
              <div className="field">
                <label>Crop position <span className="muted">{Math.round((lay.crop_x ?? 0.5) * 100)}%</span></label>
                <input type="range" min="0" max="1" step="0.01" value={lay.crop_x ?? 0.5}
                  onChange={(e) => patch({ layout: { crop_x: Number(e.target.value) } }, true)} />
                <div className="row between muted tiny"><span>Left</span><span>Center</span><span>Right</span></div>
              </div>
            )}
            <div className="field">
              <label>Zoom <span className="muted">{(lay.zoom || 1).toFixed(2)}×</span></label>
              <input type="range" min="1" max="2" step="0.05" value={lay.zoom || 1}
                onChange={(e) => patch({ layout: { zoom: Number(e.target.value) } }, true)} />
            </div>
          </>
        )}

        {tab === "export" && (
          <>
            <div className="field">
              <label>Title (used as file name)</label>
              <input className="input" value={title} maxLength={90} onChange={(e) => setTitle(e.target.value)} onBlur={() => title !== clip.title && patch({ title })} />
            </div>
            <div className="field two">
              <div>
                <label>Start</label>
                <input className="input mono" type="number" step="0.1" value={clip.start} onChange={(e) => patch({ start: Number(e.target.value) }, true)} />
              </div>
              <div>
                <label>End</label>
                <input className="input mono" type="number" step="0.1" value={clip.end} onChange={(e) => patch({ end: Number(e.target.value) }, true)} />
              </div>
            </div>
            <div className="export-box">
              <div className="row between"><span className="muted">Length</span><b>{(clip.end - clip.start).toFixed(1)} s</b></div>
              <div className="row between"><span className="muted">Format</span><b>{{ short: "1080×1920 Short", square: "1080×1080", landscape: "1920×1080" }[lay.format || "short"]}</b></div>
              <div className="row between"><span className="muted">Captions</span><b>{cap.enabled === false ? "Off" : styleDefs[cap.style]?.label}</b></div>
              {(clip.end - clip.start) > 180 && (lay.format || "short") === "short" && <p className="warn-line">Shorts can be up to 3 minutes. This clip is longer.</p>}
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
                      <div className="muted tiny">{new Date(e.at * 1000).toLocaleString()}</div>
                    </div>
                    {desktop && <button className="icon-btn" title="Play" onClick={() => desktop.openPath(e.path)}><Play size={15} /></button>}
                    {desktop && <button className="icon-btn" title="Show in folder" onClick={() => desktop.showItem(e.path)}><FolderOpen size={15} /></button>}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
