import React, { useEffect, useRef, useState } from "react";
import { Film, Link2, Loader2, Trash2, UploadCloud, Wand2, Zap, Languages, Captions } from "lucide-react";
import { api, desktop, fmtTime, url } from "../api.js";
import { useToast } from "../App.jsx";

const STATUS = {
  queued: ["Queued", "warn"],
  working: ["Working", "warn"],
  ready: ["Ready", "ok"],
  error: ["Failed", "bad"],
};

export default function Home({ onOpen }) {
  const toast = useToast();
  const [projects, setProjects] = useState([]);
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const timer = useRef(null);

  const load = async () => {
    try {
      setProjects(await api.projects());
    } catch (e) { /* engine busy */ }
  };

  useEffect(() => {
    load();
    timer.current = setInterval(load, 2500);
    return () => clearInterval(timer.current);
  }, []);

  const start = async (source) => {
    if (!source) return;
    setBusy(true);
    try {
      const r = await api.createProject(source);
      onOpen(r.project.id);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const pick = async () => {
    if (desktop) {
      const p = await desktop.pickVideo();
      if (p) start(p);
    } else {
      const p = prompt("Full path of the video file:");
      if (p) start(p);
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (!f) return;
    const p = desktop ? desktop.pathForFile(f) : f.path;
    if (!p) return toast("Couldn't read that file's location. Use 'Choose video' instead.", "error");
    start(p);
  };

  const del = async (e, id) => {
    e.stopPropagation();
    if (!confirm("Delete this project? Exported clips stay in your folder.")) return;
    await api.deleteProject(id);
    load();
  };

  return (
    <div className="page home">
      <section className="hero">
        <div className="hero-text">
          <div className="eyebrow"><Zap size={14} /> AI clipping studio</div>
          <h1>Turn long videos into <span className="grad">viral Shorts</span>.</h1>
          <p className="muted big">
            Drop a gameplay video or stream. Clipsworld listens, finds the funniest and most hype moments,
            adds animated captions in Hindi, Hinglish or English, and exports ready-to-upload Shorts.
          </p>
          <div className="hero-feats">
            <span><Wand2 size={15} /> AI moment finder</span>
            <span><Captions size={15} /> Word-by-word captions</span>
            <span><Languages size={15} /> Hindi · Hinglish · English</span>
            <span><Zap size={15} /> Zooms · Replays · SFX</span>
            <span><Film size={15} /> Facecam & voiceover</span>
            <span><Captions size={15} /> Originality check</span>
          </div>
        </div>

        <div
          className={"dropzone" + (drag ? " drag" : "")}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
        >
          <div className="dz-glow" />
          <UploadCloud size={44} className="dz-icon" />
          <h3>Drop your video here</h3>
          <p className="muted">MP4, MKV, MOV, stream recordings — any length</p>
          <button className="btn primary lg" onClick={pick} disabled={busy}>
            {busy ? <Loader2 className="spin" size={18} /> : <Film size={18} />} Choose video
          </button>
          <div className="or"><span>or paste a link</span></div>
          <form className="link-row" onSubmit={(e) => { e.preventDefault(); start(link.trim()); }}>
            <Link2 size={17} />
            <input value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://youtube.com/watch?v=…" />
            <button className="btn" disabled={!link.trim() || busy}>Start</button>
          </form>
          <p className="fine">Only use links to your own videos or videos you have permission to clip.</p>
        </div>
      </section>

      <section>
        <div className="section-head">
          <h2>Your projects</h2>
          <span className="muted">{projects.length ? `${projects.length} video${projects.length > 1 ? "s" : ""}` : ""}</span>
        </div>
        {projects.length === 0 ? (
          <div className="empty">No projects yet. Your first video will show up here.</div>
        ) : (
          <div className="proj-grid">
            {projects.map((p) => {
              const [label, kind] = STATUS[p.status] || ["", ""];
              return (
                <div key={p.id} className="proj-card" onClick={() => onOpen(p.id)}>
                  <div className="proj-thumb">
                    {p.thumb ? <img src={url.cover(p.id, p.updated)} alt="" /> : <div className="thumb-ph"><Film size={30} /></div>}
                    <span className={"badge " + kind}>{p.status === "working" && <Loader2 size={12} className="spin" />}{label}</span>
                    {p.info && <span className="dur">{fmtTime(p.info.duration)}</span>}
                  </div>
                  <div className="proj-body">
                    <div className="proj-name" title={p.name}>{p.name}</div>
                    <div className="proj-meta">
                      {p.status === "working" || p.status === "queued" ? <span className="muted">{p.stage}</span> : (
                        <span className="muted">{p.clip_count} clips · {p.export_count} exported</span>
                      )}
                      <button className="icon-btn" onClick={(e) => del(e, p.id)} title="Delete project"><Trash2 size={15} /></button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
