import React, { useEffect, useState } from "react";
import { Captions, Download, Languages, LayoutTemplate, Loader2, Mic, RefreshCw, Sparkles, Type, Wand2 } from "lucide-react";
import { api, fmtTime, waitForJob } from "../api.js";
import { useApp, useToast } from "../App.jsx";
import EffectsPanel from "./EffectsPanel.jsx";
import AudioPanel from "./AudioPanel.jsx";
import ExportPanel from "./ExportPanel.jsx";
import CamPicker from "./CamPicker.jsx";

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

export default function Inspector({ project, setProject, clip, patch, replaceClip, time, seek, videoRef, onPreview, previewBusy }) {
  const toast = useToast();
  const { styles, settings } = useApp();
  const [tab, setTab] = useState("captions");
  const [busy, setBusy] = useState(null); // {kind, progress, stage}
  const cap = clip.captions || {};
  const lay = clip.layout || {};
  const [hook, setHook] = useState(clip.hook || "");

  useEffect(() => { setHook(clip.hook || ""); }, [clip.id, clip.hook]);

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
        {[["captions", Captions, "Captions"], ["effects", Wand2, "Effects"], ["audio", Mic, "Voice"], ["layout", LayoutTemplate, "Layout"], ["export", Download, "Export"]].map(([id, Icon, label]) => (
          <button key={id} className={"vt " + (tab === id ? "on" : "")} onClick={() => setTab(id)}><Icon size={16} /><span>{label}</span>
            {id === "effects" && clip.effects?.length > 0 && <i className="dotn">{clip.effects.length}</i>}
            {id === "audio" && clip.audio?.vo_file && <i className="dotn">●</i>}
          </button>
        ))}
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
              <Toggle on={cap.replay_captions !== false} onChange={(v) => patch({ captions: { replay_captions: v } })} label="Show captions again in replays" />
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
                options={[{ id: "blur", label: "Blur" }, { id: "crop", label: "Crop" }, { id: "split", label: "Facecam" }, { id: "fit", label: "Fit" }]} />
              <p className="hint">{lay.mode === "crop" ? "Zooms into one part of the video. Move it with the slider." : lay.mode === "fit" ? "Whole video with black bars." : lay.mode === "split" ? "Streamer's webcam on top, gameplay below — the classic stream-clip layout." : "Whole video in the middle, blurred copy behind it."}</p>
            </div>
            {lay.mode === "split" && (
              <>
                <div className="field">
                  <label>Box the streamer's webcam</label>
                  <CamPicker projectId={project.id} t={clip.start + Math.min(2, (clip.end - clip.start) / 2)} cam={lay.cam || { x: 0.7, y: 0, w: 0.3, h: 0.3 }}
                    onChange={(cam) => patch({ layout: { cam } })} />
                  <p className="hint">Drag the box over the webcam. Drag the corner to resize.</p>
                </div>
                <div className="field">
                  <label>Webcam height <span className="muted">{Math.round((lay.split ?? 0.42) * 100)}%</span></label>
                  <input type="range" min="0.25" max="0.6" step="0.01" value={lay.split ?? 0.42} onChange={(e) => patch({ layout: { split: Number(e.target.value) } }, true)} />
                </div>
              </>
            )}
            {(lay.mode === "crop" || lay.mode === "split") && (
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

        {tab === "effects" && (
          <EffectsPanel project={project} clip={clip} patch={patch} replaceClip={replaceClip} time={time} seek={seek}
            onPreview={onPreview} previewBusy={previewBusy} />
        )}
        {tab === "audio" && (
          <AudioPanel project={project} clip={clip} patch={patch} replaceClip={replaceClip} videoRef={videoRef} time={time} />
        )}
        {tab === "export" && (
          <ExportPanel project={project} clip={clip} patch={patch} replaceClip={replaceClip} setProject={setProject} />
        )}
      </div>
    </div>
  );
}
