import React, { useEffect, useState } from "react";
import { Image as ImageIcon, Loader2, RefreshCw, Type } from "lucide-react";

const COLORS = { yellow: "#FFE600", white: "#FFFFFF", red: "#FF2D2D", green: "#3DFF6E", cyan: "#2DE2FF", orange: "#FF8A00", pink: "#FF4FD8" };

// Thumbnail preview + quick edits. onMake(body): body = {remake:true} for a new AI design, or {headline, subline, color}.
export default function ThumbEditor({ src, design, onMake, compact = false, emptyLabel = "Make thumbnail" }) {
  const [busy, setBusy] = useState(null);
  const [headline, setHeadline] = useState(design?.headline || "");
  const [subline, setSubline] = useState(design?.subline || "");
  useEffect(() => { setHeadline(design?.headline || ""); setSubline(design?.subline || ""); }, [design?.headline, design?.subline, design?.t]);

  const run = async (kind, body) => {
    setBusy(kind);
    try { await onMake(body); } finally { setBusy(null); }
  };
  const dirty = design && (headline !== (design.headline || "") || subline !== (design.subline || ""));

  if (!src) {
    return (
      <button className="btn sm" disabled={!!busy} onClick={() => run("remake", { remake: true })}>
        {busy ? <Loader2 size={13} className="spin" /> : <ImageIcon size={13} />} {emptyLabel}
      </button>
    );
  }
  return (
    <div className={"thumb-ed" + (compact ? " compact" : "")}>
      <a className="thumb-img" href={src} target="_blank" rel="noreferrer" title="Open full size">
        <img src={src} alt="Thumbnail" />
        {busy && <span className="thumb-busy"><Loader2 size={20} className="spin" /></span>}
      </a>
      <div className="thumb-fields">
        <input className="input" value={headline} maxLength={26} placeholder="Thumbnail text" onChange={(e) => setHeadline(e.target.value)} />
        <input className="input" value={subline} maxLength={18} placeholder="Small banner (optional)" onChange={(e) => setSubline(e.target.value)} />
        <div className="thumb-colors">
          {Object.entries(COLORS).map(([k, v]) => (
            <button key={k} title={k} className={"tc" + (design?.color === k ? " on" : "")} style={{ background: v }}
              disabled={!!busy} onClick={() => run("apply", { headline, subline, color: k })} />
          ))}
        </div>
        <div className="row gap wrap">
          {dirty && <button className="btn primary sm" disabled={!!busy} onClick={() => run("apply", { headline, subline })}><Type size={13} /> Apply text</button>}
          <button className="btn ghost sm" disabled={!!busy} onClick={() => run("remake", { remake: true })} title="Claude picks a new frame and writes new text">
            <RefreshCw size={13} /> New design
          </button>
        </div>
      </div>
    </div>
  );
}
