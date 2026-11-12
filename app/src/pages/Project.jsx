import React, { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, AudioLines, Check, Download, Loader2, RefreshCw, Sparkles, X, AlertTriangle, Film, Wand2, Captions as CapIcon } from "lucide-react";
import { api, fmtTime, url, waitForJob } from "../api.js";
import { useApp, useToast } from "../App.jsx";
import ClipList from "../components/ClipList.jsx";
import Preview from "../components/Preview.jsx";
import Timeline from "../components/Timeline.jsx";
import Inspector from "../components/Inspector.jsx";

const STEPS = [
  { key: "Download", icon: Download, match: /download|merging/i },
  { key: "Audio", icon: AudioLines, match: /reading|extract|loudness/i },
  { key: "Transcribe", icon: CapIcon, match: /speech model|listening|transcrib|gpu not/i },
  { key: "Find clips", icon: Wand2, match: /claude|finding|thumbnail|moments/i },
  { key: "Preview", icon: Film, match: /preview/i },
];

function Pipeline({ project, job, onCancel }) {
  const stage = job?.stage || project.stage || "";
  let cur = STEPS.findIndex((s) => s.match.test(stage));
  const steps = project.source_kind === "url" ? STEPS : STEPS.slice(1);
  if (project.source_kind !== "url") cur -= 1;
  if (cur < 0) cur = 0;
  const pct = Math.round((job?.progress || 0) * 100);
  return (
    <div className="pipeline">
      <div className="pl-card">
        <div className="pl-orb"><div className="orb" /><span>{pct}%</span></div>
        <h2>{project.status === "error" ? "Something went wrong" : "Clipsworld is working on your video"}</h2>
        {project.status === "error" ? (
          <p className="err-text"><AlertTriangle size={16} /> {project.error}</p>
        ) : (
          <p className="muted">{stage}</p>
        )}
        <div className="pbar big"><span style={{ width: `${pct}%` }} /></div>
        <div className="steps">
          {steps.map((s, i) => {
            const Icon = s.icon;
            const st = i < cur ? "done" : i === cur ? "now" : "todo";
            return (
              <div key={s.key} className={"step " + st}>
                <div className="step-ic">{st === "done" ? <Check size={16} /> : st === "now" ? <Loader2 size={16} className="spin" /> : <Icon size={16} />}</div>
                <span>{s.key}</span>
              </div>
            );
          })}
        </div>
        {project.status !== "error" && job && <button className="btn ghost" onClick={onCancel}><X size={15} /> Cancel</button>}
        <p className="fine">Long streams take a while the first time. You can leave this page — work continues in the background.</p>
      </div>
    </div>
  );
}

export default function Project({ id, onBack }) {
  const toast = useToast();
  const { styles, settings } = useApp();
  const [project, setProject] = useState(null);
  const [job, setJob] = useState(null);
  const [sel, setSel] = useState(null);
  const [time, setTime] = useState(0);
  const [wave, setWave] = useState(null);
  const [bulk, setBulk] = useState(null);
  const [rendered, setRendered] = useState({}); // clipId -> {url, stale}
  const [previewBusy, setPreviewBusy] = useState(null);
  const videoRef = useRef(null);
  const timers = useRef({});

  const load = useCallback(async () => {
    try {
      const p = await api.project(id);
      setProject(p);
      if (p.status !== "ready" && p.status !== "error") {
        const js = await api.jobs();
        setJob(js.filter((j) => j.project_id === id && j.status === "running").pop() || null);
      } else setJob(null);
      return p;
    } catch (e) {
      toast(e.message, "error");
    }
  }, [id, toast]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!project) return;
    if (project.status === "ready") {
      if (!wave) api.waveform(id).then(setWave).catch(() => {});
      if (!sel && project.clips.length) setSel(project.clips[0].id);
      return;
    }
    if (project.status === "error") return;
    const t = setTimeout(load, 1200);
    return () => clearTimeout(t);
  }, [project, load, id, sel, wave]);

  const clip = project?.clips.find((c) => c.id === sel);

  const replaceClip = useCallback((c) => {
    setProject((p) => ({ ...p, clips: p.clips.map((x) => (x.id === c.id ? c : x)) }));
    setRendered((r) => (r[c.id] ? { ...r, [c.id]: { ...r[c.id], stale: true } } : r));
  }, []);

  const makePreview = async () => {
    if (!sel) return;
    setPreviewBusy({ progress: 0 });
    try {
      const j = await api.preview(id, sel);
      const d = await waitForJob(j.id, (x) => setPreviewBusy({ progress: x.progress }));
      setRendered((r) => ({ ...r, [sel]: { url: url.file(d.result.path) + `&v=${d.result.version}`, stale: false, show: true } }));
    } catch (e) { toast(e.message, "error"); }
    finally { setPreviewBusy(null); }
  };

  const patch = useCallback((p, debounce = false) => {
    if (!sel) return;
    setProject((proj) => ({
      ...proj,
      clips: proj.clips.map((c) => (c.id !== sel ? c : {
        ...c, ...p,
        layout: { ...c.layout, ...(p.layout || {}), cam: { ...(c.layout?.cam || {}), ...(p.layout?.cam || {}) } },
        captions: { ...c.captions, ...(p.captions || {}) },
        audio: { ...c.audio, ...(p.audio || {}), bubble: { ...(c.audio?.bubble || {}), ...(p.audio?.bubble || {}) } },
        meta: { ...c.meta, ...(p.meta || {}) },
      })),
    }));
    const send = async () => {
      try {
        replaceClip(await api.updateClip(id, sel, p));
      } catch (e) { toast(e.message, "error"); }
    };
    const key = sel + Object.keys(p).join() + Object.keys(p.layout || p.captions || {}).join();
    clearTimeout(timers.current[key]);
    if (debounce) timers.current[key] = setTimeout(send, 450);
    else return send();
  }, [id, sel, replaceClip, toast]);

  const seek = (t) => {
    const v = videoRef.current;
    if (v) v.currentTime = t;
    setTime(t);
  };

  const newClip = async (at) => {
    const s = typeof at === "number" ? at : time;
    const dur = project.info.duration;
    const len = Math.min(settings.max_clip_sec || 30, 30);
    try {
      const c = await api.addClip(id, Math.max(0, Math.min(s, dur - 1)), Math.min(dur, s + len));
      setProject((p) => ({ ...p, clips: [c, ...p.clips] }));
      setSel(c.id);
    } catch (e) { toast(e.message, "error"); }
  };

  const delClip = async (cid) => {
    await api.deleteClip(id, cid);
    setProject((p) => {
      const clips = p.clips.filter((c) => c.id !== cid);
      if (cid === sel) setSel(clips[0]?.id || null);
      return { ...p, clips };
    });
  };

  const refind = async () => {
    if (!confirm("Find clips again? Clips you exported or made yourself are kept.")) return;
    try {
      await api.reanalyze(id, "clips");
      setSel(null);
      setTimeout(load, 300);
      setProject((p) => ({ ...p, status: "working", stage: "Finding the best moments…" }));
    } catch (e) { toast(e.message, "error"); }
  };

  const exportAll = async () => {
    if (!project.clips.length) return;
    if (!confirm(`Export all ${project.clips.length} clips?`)) return;
    setBulk({ progress: 0, stage: "Starting…" });
    try {
      const j = await api.exportClips(id, project.clips.map((c) => c.id));
      await waitForJob(j.id, (x) => setBulk({ progress: x.progress, stage: x.stage }));
      toast(`Exported ${project.clips.length} clips 🎉`, "ok");
      load();
    } catch (e) { toast(e.message, "error"); }
    finally { setBulk(null); }
  };

  if (!project) return <div className="page center"><Loader2 className="spin" size={30} /></div>;

  const header = (
    <div className="proj-header">
      <button className="icon-btn lg" onClick={onBack}><ArrowLeft size={20} /></button>
      <div className="ph-title">
        <h2 title={project.name}>{project.name}</h2>
        <div className="muted tiny">
          {project.info && <>{fmtTime(project.info.duration)} · {project.info.width}×{project.info.height}</>}
          {project.transcript && <> · {project.transcript.mixed ? "Hindi + English" : (project.transcript.language || "").toUpperCase()} · {project.transcript.device?.toUpperCase()}</>}
        </div>
      </div>
      <div className="ph-actions">
        {project.status === "ready" && (
          <>
            <button className="btn ghost" onClick={refind}><RefreshCw size={15} /> Find clips again</button>
            <button className="btn primary" onClick={exportAll} disabled={!!bulk || !project.clips.length}>
              {bulk ? <><Loader2 size={15} className="spin" /> {Math.round(bulk.progress * 100)}%</> : <><Download size={15} /> Export all</>}
            </button>
          </>
        )}
      </div>
    </div>
  );

  if (project.status !== "ready") {
    return (
      <div className="page project">
        {header}
        <Pipeline project={project} job={job} onCancel={async () => { if (job) await api.cancelJob(job.id); load(); }} />
        {project.status === "error" && (
          <div className="center-row">
            <button className="btn primary" onClick={async () => { await api.reanalyze(id, project.transcript ? "clips" : "start"); load(); }}><RefreshCw size={15} /> Try again</button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="page project">
      {header}
      {project.warning && <div className={"banner " + (project.warning.startsWith("Tip") ? "tip" : "warn")}><Sparkles size={15} /> {project.warning}</div>}
      {bulk && <div className="banner tip"><Loader2 size={15} className="spin" /> {bulk.stage} <div className="pbar inline"><span style={{ width: `${bulk.progress * 100}%` }} /></div></div>}
      <div className="workspace">
        <ClipList project={project} selected={sel} onSelect={setSel} onDelete={delClip} onNewClip={newClip} onSeek={seek} />
        <div className="center-col">
          {clip ? (
            <>
              <Preview projectId={id} clip={clip} styleDef={styles?.styles?.[clip.captions?.style]} videoRef={videoRef} time={time} setTime={setTime}
                rendered={rendered[clip.id]} previewBusy={previewBusy} onMakePreview={makePreview}
                onToggleRendered={(show) => setRendered((r) => ({ ...r, [clip.id]: { ...r[clip.id], show } }))} />
              <Timeline wave={wave} duration={project.info.duration} clip={clip} clips={project.clips} time={time} onSeek={seek}
                onTrim={(s, e) => patch({ start: s, end: e })} />
            </>
          ) : (
            <div className="empty big">Pick a clip on the left, or make a new one.</div>
          )}
        </div>
        {clip && <Inspector project={project} setProject={setProject} clip={clip} patch={patch} replaceClip={replaceClip} time={time}
          seek={seek} videoRef={videoRef} onPreview={makePreview} previewBusy={!!previewBusy} />}
      </div>
    </div>
  );
}
