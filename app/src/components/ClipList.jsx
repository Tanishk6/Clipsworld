import React, { useState } from "react";
import { Plus, Sparkles, Trash2, Cpu, ScrollText, Scissors } from "lucide-react";
import { fmtTime, url } from "../api.js";

const CAT = {
  funny: "😂 Funny", shock: "😱 Shock", hype: "🔥 Hype", rage: "😡 Rage", skill: "🎯 Skill",
  wholesome: "💛 Wholesome", story: "📖 Story", panic: "😨 Panic", loud: "📢 Reaction",
  laugh: "😂 Funny", banter: "😄 Banter",
};

function ScoreRing({ score }) {
  const r = 15, c = 2 * Math.PI * r;
  const col = score >= 80 ? "#4dffb8" : score >= 60 ? "#ffd23f" : "#ff8a5c";
  return (
    <svg className="ring" width="38" height="38" viewBox="0 0 38 38">
      <circle cx="19" cy="19" r={r} stroke="rgba(255,255,255,.1)" strokeWidth="3.5" fill="none" />
      <circle cx="19" cy="19" r={r} stroke={col} strokeWidth="3.5" fill="none" strokeDasharray={c}
        strokeDashoffset={c * (1 - score / 100)} strokeLinecap="round" transform="rotate(-90 19 19)" />
      <text x="19" y="23" textAnchor="middle" fill="#fff" fontSize="11" fontWeight="700">{score}</text>
    </svg>
  );
}

export default function ClipList({ project, selected, onSelect, onDelete, onNewClip, onSeek }) {
  const [tab, setTab] = useState("clips");
  const segs = project.transcript?.segments || [];
  return (
    <div className="cliplist">
      <div className="seg-tabs">
        <button className={tab === "clips" ? "on" : ""} onClick={() => setTab("clips")}><Scissors size={15} /> Clips <b>{project.clips.length}</b></button>
        <button className={tab === "text" ? "on" : ""} onClick={() => setTab("text")}><ScrollText size={15} /> Transcript</button>
      </div>
      {tab === "clips" ? (
        <div className="cl-scroll">
          <button className="new-clip" onClick={onNewClip}><Plus size={16} /> New clip at playhead</button>
          {project.clips.length === 0 && <div className="empty sm">No clips found. Try "Find clips again" or make one from the transcript.</div>}
          {project.clips.map((c, i) => (
            <div key={c.id} className={"clip-card" + (c.id === selected ? " on" : "")} onClick={() => onSelect(c.id)}>
              <div className="cc-thumb">
                <img src={url.thumb(project.id, c.id, `${c.start}`)} alt="" loading="lazy" />
                <span className="dur">{fmtTime(c.end - c.start)}</span>
                <span className="rank">#{i + 1}</span>
              </div>
              <div className="cc-body">
                <div className="cc-title" title={c.title}>{c.title}</div>
                <div className="cc-reason">{c.reason || "Manual clip"}</div>
                <div className="cc-tags">
                  <span className="chip">{CAT[c.category] || c.category}</span>
                  {c.source === "claude" ? <span className="chip ai"><Sparkles size={11} /> Claude</span> : c.source === "local" ? <span className="chip"><Cpu size={11} /> Offline</span> : null}
                  {c.exports?.length > 0 && <span className="chip ok">✓ Exported</span>}
                </div>
              </div>
              <div className="cc-side">
                <ScoreRing score={c.score ?? 50} />
                <button className="icon-btn" onClick={(e) => { e.stopPropagation(); onDelete(c.id); }} title="Delete clip"><Trash2 size={14} /></button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="cl-scroll transcript">
          {segs.length === 0 && <div className="empty sm">No speech found.</div>}
          {segs.map((s, i) => (
            <div key={i} className="tr-line" onClick={() => onSeek(s.start)}>
              <span className="mono t">{fmtTime(s.start)}</span>
              <span className="tx">{s.text}</span>
              <button className="icon-btn" title="Make a clip starting here" onClick={(e) => { e.stopPropagation(); onNewClip(s.start); }}><Plus size={14} /></button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
