import React, { useEffect, useState } from "react";
import { Clapperboard, FolderOpen, Play } from "lucide-react";
import { api, desktop, url } from "../api.js";

export default function Exports() {
  const [items, setItems] = useState(null);
  useEffect(() => { api.exports().then(setItems).catch(() => setItems([])); }, []);
  return (
    <div className="page">
      <div className="section-head">
        <h1 className="page-title"><Clapperboard size={26} /> My clips</h1>
        <span className="muted">{items ? `${items.length} exported` : ""}</span>
      </div>
      {items && items.length === 0 && <div className="empty">Nothing exported yet. Open a project and press Export.</div>}
      <div className="exp-grid">
        {(items || []).map((e, i) => (
          <div key={i} className="exp-card">
            <div className={"exp-media " + (e.format || "short")}>
              <video src={url.file(e.path)} poster={e.thumb ? url.file(e.thumb) : undefined} muted loop playsInline preload="none"
                onMouseEnter={(ev) => ev.currentTarget.play().catch(() => {})}
                onMouseLeave={(ev) => { ev.currentTarget.pause(); ev.currentTarget.currentTime = 0; }} />
            </div>
            <div className="exp-body">
              <div className="exp-name" title={e.title}>{e.title}</div>
              <div className="muted tiny">{e.project} · {e.duration}s</div>
              <div className="row gap">
                {desktop && <button className="btn sm" onClick={() => desktop.openPath(e.path)}><Play size={13} /> Play</button>}
                {desktop && <button className="btn ghost sm" onClick={() => desktop.showItem(e.path)}><FolderOpen size={13} /> Folder</button>}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
