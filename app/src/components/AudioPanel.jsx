import React, { useEffect, useRef, useState } from "react";
import { Camera, CameraOff, Circle, FolderOpen, Mic, Square, Trash2, Headphones } from "lucide-react";
import { api, desktop, url } from "../api.js";
import { useToast } from "../App.jsx";

function Toggle({ on, onChange, label }) {
  return (
    <label className="toggle" onClick={() => onChange(!on)}>
      <span className={"sw" + (on ? " on" : "")}><span /></span>
      {label}
    </label>
  );
}

function pickMime(video) {
  const opts = video
    ? ["video/webm;codecs=vp8,opus", "video/webm;codecs=vp9,opus", "video/webm"]
    : ["audio/webm;codecs=opus", "audio/webm"];
  return opts.find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || "";
}

export default function AudioPanel({ project, clip, patch, replaceClip, videoRef, time }) {
  const toast = useToast();
  const aud = clip.audio || {};
  const bub = aud.bubble || {};
  const [cam, setCam] = useState(true);
  const [state, setState] = useState("idle"); // idle, countdown, recording, saving
  const [count, setCount] = useState(0);
  const liveRef = useRef(null);
  const recRef = useRef(null);
  const streamRef = useRef(null);
  const chunks = useRef([]);

  const stopStream = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  };
  useEffect(() => () => { try { recRef.current?.stop(); } catch (_) {} stopStream(); }, []);
  useEffect(() => {
    const el = liveRef.current;
    if (el && streamRef.current && el.srcObject !== streamRef.current) {
      el.srcObject = streamRef.current;
      el.play().catch(() => {});
    }
  }, [state]);

  // stop automatically at the end of the clip
  useEffect(() => {
    if (state === "recording" && time >= clip.end - 0.05) stop();
  }, [time, state]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
        video: cam ? { width: { ideal: 720 }, height: { ideal: 720 }, facingMode: "user" } : false,
      });
      streamRef.current = stream;
      const v = videoRef.current;
      if (v) { v.pause(); v.currentTime = clip.start; }
      setState("countdown");
      for (let i = 3; i > 0; i--) { setCount(i); await new Promise((r) => setTimeout(r, 800)); }
      const mime = pickMime(cam);
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime, videoBitsPerSecond: 2_500_000 } : undefined);
      chunks.current = [];
      rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      rec.onstop = upload;
      recRef.current = rec;
      rec.start(250);
      if (v) { v.currentTime = clip.start; v.play().catch(() => {}); }
      setState("recording");
    } catch (e) {
      stopStream();
      setState("idle");
      toast(e.name === "NotAllowedError" ? "Allow camera/microphone access to record." : `Can't start recording: ${e.message}`, "error");
    }
  };

  const stop = () => {
    const v = videoRef.current;
    if (v) v.pause();
    try { recRef.current?.state !== "inactive" && recRef.current.stop(); } catch (_) {}
  };

  async function upload() {
    setState("saving");
    stopStream();
    try {
      const blob = new Blob(chunks.current, { type: cam ? "video/webm" : "audio/webm" });
      const c = await api.uploadVoiceover(project.id, clip.id, blob, "webm", cam);
      replaceClip(c);
      toast(cam ? "Reaction saved — it shows as a bubble in your clip" : "Voiceover saved", "ok");
    } catch (e) { toast(e.message, "error"); }
    finally { setState("idle"); }
  }

  const importFile = async () => {
    if (!desktop) return;
    const p = await desktop.pickVideo();
    if (!p) return;
    try { replaceClip(await api.importVoiceover(project.id, clip.id, p)); toast("Voiceover added", "ok"); }
    catch (e) { toast(e.message, "error"); }
  };

  const remove = async () => {
    if (!confirm("Delete this recording?")) return;
    replaceClip(await api.deleteVoiceover(project.id, clip.id));
  };

  const busy = state !== "idle";

  return (
    <>
      <div className="rec-card">
        <div className="rec-head">
          <Mic size={18} />
          <div>
            <h4>Your reaction / voiceover</h4>
            <p className="muted tiny">The best way to make clips <b>yours</b> for YouTube monetization.</p>
          </div>
        </div>
        <div className={"rec-live" + (busy && cam ? " on" : "")}>
          {busy && cam ? <video ref={liveRef} muted playsInline /> : (
            aud.vo_file ? (
              aud.vo_has_video
                ? <video src={url.file(aud.vo_file)} controls playsInline />
                : <audio src={url.file(aud.vo_file)} controls />
            ) : <div className="rec-ph">{cam ? <Camera size={30} /> : <Mic size={30} />}<span>Nothing recorded yet</span></div>
          )}
          {state === "countdown" && <div className="rec-count">{count}</div>}
          {state === "recording" && <div className="rec-dot"><Circle size={10} fill="currentColor" /> REC</div>}
        </div>
        {!busy && (
          <div className="row gap wrap">
            <button className={"btn sm " + (cam ? "" : "ghost")} onClick={() => setCam((c) => !c)}>
              {cam ? <Camera size={14} /> : <CameraOff size={14} />} Camera {cam ? "on" : "off"}
            </button>
            <button className="btn primary sm" onClick={start}><Circle size={13} fill="currentColor" /> {aud.vo_file ? "Record again" : "Record"}</button>
            {desktop && <button className="btn ghost sm" onClick={importFile}><FolderOpen size={14} /> Import file</button>}
            {aud.vo_file && <button className="icon-btn" title="Delete recording" onClick={remove}><Trash2 size={15} /></button>}
          </div>
        )}
        {state === "recording" && <button className="btn sm full" onClick={stop}><Square size={13} fill="currentColor" /> Stop</button>}
        {state === "saving" && <p className="hint">Saving…</p>}
        <p className="hint"><Headphones size={12} /> Use headphones so the clip's sound doesn't get into your mic. Recording follows the clip and stops at its end.</p>
      </div>

      <div className="field">
        <label>Clip sound <span className="muted">{Math.round((aud.orig_volume ?? 1) * 100)}%</span></label>
        <input type="range" min="0" max="1.5" step="0.05" value={aud.orig_volume ?? 1} onChange={(e) => patch({ audio: { orig_volume: Number(e.target.value) } }, true)} />
      </div>
      {aud.vo_file && (
        <>
          <div className="field">
            <label>Your voice <span className="muted">{Math.round((aud.vo_volume ?? 1) * 100)}%</span></label>
            <input type="range" min="0" max="2" step="0.05" value={aud.vo_volume ?? 1} onChange={(e) => patch({ audio: { vo_volume: Number(e.target.value) } }, true)} />
          </div>
          <div className="field row">
            <Toggle on={aud.duck !== false} onChange={(v) => patch({ audio: { duck: v } })} label="Lower clip sound while I talk" />
          </div>
          {aud.vo_has_video && (
            <>
              <div className="field row">
                <Toggle on={bub.show !== false} onChange={(v) => patch({ audio: { bubble: { show: v } } })} label="Show my camera as a bubble" />
              </div>
              <div className="field">
                <label>Bubble position</label>
                <select value={bub.pos || "top-right"} onChange={(e) => patch({ audio: { bubble: { pos: e.target.value } } })}>
                  <option value="top-right">Top right</option><option value="top-left">Top left</option>
                  <option value="middle-right">Middle right</option><option value="middle-left">Middle left</option>
                  <option value="bottom-right">Bottom right</option><option value="bottom-left">Bottom left</option>
                </select>
              </div>
              <div className="field">
                <label>Bubble size <span className="muted">{Math.round((bub.size ?? 0.34) * 100)}%</span></label>
                <input type="range" min="0.18" max="0.55" step="0.01" value={bub.size ?? 0.34} onChange={(e) => patch({ audio: { bubble: { size: Number(e.target.value) } } }, true)} />
              </div>
            </>
          )}
        </>
      )}
    </>
  );
}
