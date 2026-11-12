import React, { useEffect, useRef, useState } from "react";
import { Eye, Loader2, Music2, Pause, Play, Snowflake, Sparkles, Trash2, Type, Vibrate, Wand2, ZoomIn, Rewind } from "lucide-react";
import { api, fmtTime, url, waitForJob } from "../api.js";
import { useToast } from "../App.jsx";

export const FX_META = {
  zoom: { label: "Zoom punch-in", icon: ZoomIn, color: "#2de2ff" },
  shake: { label: "Camera shake", icon: Vibrate, color: "#ff8a5c" },
  freeze: { label: "Freeze + text", icon: Snowflake, color: "#ffd23f" },
  replay: { label: "Slow-mo replay", icon: Rewind, color: "#ff4fd8" },
  text: { label: "Text pop", icon: Type, color: "#ffffff" },
  sfx: { label: "Sound effect", icon: Music2, color: "#4dffb8" },
};

const TEXT_PRESETS = ["WAIT WHAT?!", "BRUH", "NO WAY", "LMAO", "BHAI KYA", "LET'S GOOO", "OYE HOYE", "BHAAGOOO!!", "EMOTIONAL DAMAGE", "GG"];

let audioEl = null;
export function playSfx(id) {
  if (!id) return;
  if (audioEl) audioEl.pause();
  audioEl = new Audio(url.sfx(id));
  audioEl.volume = 0.8;
  audioEl.play().catch(() => {});
}

function SfxSelect({ value, onChange, list, allowNone = true }) {
  return (
    <div className="sfx-sel">
      <select value={value || ""} onChange={(e) => onChange(e.target.value)}>
        {allowNone && <option value="">No sound</option>}
        {list.map((s) => <option key={s.id} value={s.id}>{s.name}{s.source === "user" ? " (mine)" : ""}</option>)}
      </select>
      <button className="icon-btn" title="Listen" disabled={!value} onClick={() => playSfx(value)}><Play size={14} /></button>
    </div>
  );
}

function Num({ label, value, onChange, min, max, step = 0.1, suffix = "" }) {
  return (
    <label className="num">
      <span>{label}</span>
      <input type="number" value={value} min={min} max={max} step={step}
        onChange={(e) => onChange(Number(e.target.value))} />
      {suffix && <em>{suffix}</em>}
    </label>
  );
}

export default function EffectsPanel({ project, clip, patch, replaceClip, time, seek, onPreview, previewBusy }) {
  const toast = useToast();
  const [sfx, setSfx] = useState([]);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(null);
  const effects = clip.effects || [];
  const rel = Math.max(0, Math.min(clip.end - clip.start, time - clip.start));
  const listRef = useRef(null);

  useEffect(() => { api.sfx().then(setSfx).catch(() => {}); }, []);

  const save = (list) => patch({ effects: list });
  const add = async (type) => {
    const d = await api.effectDefaults().catch(() => null);
    const base = d?.defaults?.[type] || {};
    const e = { id: Math.random().toString(36).slice(2, 8), type, t: Math.round(rel * 100) / 100, ...base };
    if (type === "replay") e.t = Math.max(1, Math.round(rel * 100) / 100);
    const list = [...effects, e].sort((a, b) => a.t - b.t);
    await save(list);
    setOpen(e.id);
  };
  const upd = (id, ch) => save(effects.map((e) => (e.id === id ? { ...e, ...ch } : e)));
  const del = (id) => save(effects.filter((e) => e.id !== id));

  const auto = async () => {
    if (effects.length && !confirm("Replace the current effects with an automatic edit?")) return;
    setBusy(true);
    try {
      const j = await api.autoEdit(project.id, clip.id);
      const done = await waitForJob(j.id);
      replaceClip(done.result.clip);
      toast(done.result.source === "claude" ? "Claude edited your clip ✨" : "Auto edit done (offline)", "ok");
    } catch (e) { toast(e.message, "error"); }
    finally { setBusy(false); }
  };

  return (
    <>
      <div className="fx-actions">
        <button className="btn primary full" onClick={auto} disabled={busy}>
          {busy ? <Loader2 size={16} className="spin" /> : <Wand2 size={16} />} Auto edit
        </button>
        <button className="btn full" onClick={onPreview} disabled={previewBusy} title="Render a quick preview with all effects">
          {previewBusy ? <Loader2 size={16} className="spin" /> : <Eye size={16} />} Preview with effects
        </button>
      </div>
      <p className="hint"><Sparkles size={12} /> Auto edit adds zooms, shake, replay, text pops and sounds on the best moments.</p>

      <div className="field">
        <label><Music2 size={14} /> Sound effects volume <span className="muted">{Math.round((clip.audio?.sfx_volume ?? 1) * 100)}%</span></label>
        <input type="range" min="0" max="2" step="0.05" value={clip.audio?.sfx_volume ?? 1}
          onChange={(e) => patch({ audio: { sfx_volume: Number(e.target.value) } }, true)} />
        <div className="row between muted tiny"><span>Off</span><span>Normal</span><span>Loud</span></div>
      </div>

      <div className="field">
        <label>Add at playhead <span className="muted mono">{fmtTime(rel, true)}</span></label>
        <div className="fx-add">
          {Object.entries(FX_META).map(([k, m]) => {
            const Icon = m.icon;
            return (
              <button key={k} className="fx-add-btn" onClick={() => add(k)} style={{ "--fx": m.color }}>
                <Icon size={16} /><span>{m.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="field" ref={listRef}>
        <label>Effects in this clip <span className="muted">{effects.length}</span></label>
        {effects.length === 0 && <div className="empty sm">No effects yet. Press Auto edit or add one above.</div>}
        <div className="fx-list">
          {effects.map((e) => {
            const m = FX_META[e.type] || {};
            const Icon = m.icon || Sparkles;
            const isOpen = open === e.id;
            return (
              <div key={e.id} className={"fx-item" + (isOpen ? " open" : "")} style={{ "--fx": m.color }}>
                <div className="fx-row" onClick={() => setOpen(isOpen ? null : e.id)}>
                  <span className="fx-ic"><Icon size={15} /></span>
                  <span className="fx-name">{m.label}{e.text ? ` · “${e.text}”` : e.label ? ` · ${e.label}` : ""}</span>
                  <button className="mono fx-time" title="Jump here" onClick={(ev) => { ev.stopPropagation(); seek(clip.start + e.t); }}>{fmtTime(e.t, true)}</button>
                  <button className="icon-btn" onClick={(ev) => { ev.stopPropagation(); del(e.id); }}><Trash2 size={14} /></button>
                </div>
                {isOpen && (
                  <div className="fx-body">
                    <div className="fx-grid">
                      <Num label="At (s)" value={e.t} min={0} max={clip.end - clip.start} onChange={(v) => upd(e.id, { t: v })} />
                      {e.type !== "sfx" && <Num label={e.type === "replay" ? "Replay (s)" : "Length (s)"} value={e.dur} min={0.2} max={5} onChange={(v) => upd(e.id, { dur: v })} />}
                      {e.type === "zoom" && <Num label="Zoom ×" value={e.scale} min={1.05} max={2.5} step={0.05} onChange={(v) => upd(e.id, { scale: v })} />}
                      {e.type === "replay" && <Num label="Speed ×" value={e.speed} min={0.5} max={1} step={0.05} onChange={(v) => upd(e.id, { speed: v })} />}
                      {e.type === "shake" && <Num label="Strength" value={e.strength} min={0.3} max={3} step={0.1} onChange={(v) => upd(e.id, { strength: v })} />}
                      {e.type === "freeze" && <Num label="Zoom ×" value={e.zoom} min={1} max={1.6} step={0.02} onChange={(v) => upd(e.id, { zoom: v })} />}

                    </div>
                    {e.type === "zoom" && (
                      <div className="fx-grid">
                        <label className="num"><span>Style</span>
                          <select value={e.ease} onChange={(ev) => upd(e.id, { ease: ev.target.value })}>
                            <option value="snap">Snap (punch)</option><option value="smooth">Smooth</option>
                          </select>
                        </label>
                        <Num label="Focus X" value={e.fx} min={0} max={1} step={0.05} onChange={(v) => upd(e.id, { fx: v })} />
                        <Num label="Focus Y" value={e.fy} min={0} max={1} step={0.05} onChange={(v) => upd(e.id, { fy: v })} />
                      </div>
                    )}
                    {(e.type === "text" || e.type === "freeze") && (
                      <>
                        <input className="input" defaultValue={e.text} maxLength={40} placeholder="Text"
                          onBlur={(ev) => ev.target.value !== e.text && upd(e.id, { text: ev.target.value })} />
                        <div className="chips">
                          {TEXT_PRESETS.map((t) => <button key={t} className="chip btnchip" onClick={() => upd(e.id, { text: t })}>{t}</button>)}
                        </div>
                      </>
                    )}
                    {e.type === "text" && (
                      <div className="fx-grid">
                        <label className="num"><span>Place</span>
                          <select value={e.position} onChange={(ev) => upd(e.id, { position: ev.target.value })}>
                            <option value="top">Top</option><option value="middle">Middle</option><option value="bottom">Bottom</option>
                          </select>
                        </label>
                        <label className="num"><span>Color</span>
                          <input type="color" value={e.color || "#FFE600"} onChange={(ev) => upd(e.id, { color: ev.target.value })} />
                        </label>
                      </div>
                    )}
                    {e.type === "replay" && (
                      <input className="input" defaultValue={e.label} maxLength={20} placeholder="Badge text (e.g. REPLAY)"
                        onBlur={(ev) => ev.target.value !== e.label && upd(e.id, { label: ev.target.value })} />
                    )}
                    <label className="num full"><span>Sound</span>
                      <SfxSelect value={e.sfx} list={sfx} onChange={(v) => upd(e.id, { sfx: v })} allowNone={e.type !== "sfx"} />
                    </label>
                    {e.sfx && (
                      <label className="num full"><span>Sound volume · {Math.round((e.volume ?? 0.85) * 100)}%</span>
                        <input type="range" min="0" max="2" step="0.05" value={e.volume ?? 0.85}
                          onChange={(ev) => upd(e.id, { volume: Number(ev.target.value) })} />
                      </label>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className="field">
        <label><Music2 size={14} /> Sound library</label>
        <div className="sfx-grid">
          {sfx.map((s) => (
            <button key={s.id} className="sfx-chip" onClick={() => playSfx(s.id)} title="Click to listen">
              <Play size={11} /> {s.name}
            </button>
          ))}
        </div>
        <p className="hint">Add your own sounds: put .wav/.mp3 files in %APPDATA%\Clipsworld\sfx</p>
      </div>
    </>
  );
}

export { Pause };
