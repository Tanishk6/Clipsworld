import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Eye, Loader2, Pause, Play, RotateCcw, Volume2, VolumeX, Radio, Film } from "lucide-react";
import { fmtTime, url } from "../api.js";
import CaptionOverlay from "./CaptionOverlay.jsx";

const RATIO = { short: 9 / 16, landscape: 16 / 9, square: 1 };

export default function Preview({ projectId, clip, styleDef, videoRef, time, setTime, rendered, previewBusy, onMakePreview, onToggleRendered }) {
  const showRendered = !!(rendered && rendered.show && rendered.url);
  const wrapRef = useRef(null);
  const canvasRef = useRef(null);
  const camRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [box, setBox] = useState({ w: 300, h: 533 });
  const layout = clip.layout || {};
  const ratio = RATIO[layout.format] || RATIO.short;

  // Fit the phone/landscape frame into the available space
  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const fit = () => {
      const W = el.clientWidth - 16;
      const H = el.clientHeight - 16;
      let h = H;
      let w = h * ratio;
      if (w > W) { w = W; h = w / ratio; }
      setBox({ w: Math.floor(w), h: Math.floor(h) });
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ratio]);

  // Jump to clip start when the clip changes
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const go = () => { v.currentTime = clip.start; setTime(clip.start); };
    if (v.readyState >= 1) go();
    else v.addEventListener("loadedmetadata", go, { once: true });
  }, [clip.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Smooth time updates + loop inside the clip + blurred background canvas
  useEffect(() => {
    let raf;
    const loop = () => {
      const v = videoRef.current;
      if (v) {
        if (!v.paused) {
          if (v.currentTime >= clip.end || v.currentTime < clip.start - 0.5) v.currentTime = clip.start;
          setTime(v.currentTime);
        }
        const cc = camRef.current;
        if (cc && layout.mode === "split" && v.readyState >= 2) {
          const cam = layout.cam || { x: 0.7, y: 0, w: 0.3, h: 0.3 };
          const sw = v.videoWidth * cam.w, sh = v.videoHeight * cam.h;
          const ctx = cc.getContext("2d");
          const r = Math.max(cc.width / sw, cc.height / sh);
          const dw = sw * r, dh = sh * r;
          ctx.drawImage(v, v.videoWidth * cam.x, v.videoHeight * cam.y, sw, sh, (cc.width - dw) / 2, (cc.height - dh) / 2, dw, dh);
        }
        const c = canvasRef.current;
        if (c && layout.mode === "blur" && v.readyState >= 2) {
          const ctx = c.getContext("2d");
          const cw = c.width, ch = c.height;
          const vr = v.videoWidth / v.videoHeight || 16 / 9;
          let dw = cw, dh = cw / vr;
          if (dh < ch) { dh = ch; dw = ch * vr; }
          ctx.filter = "blur(18px) brightness(0.85) saturate(1.15)";
          ctx.drawImage(v, (cw - dw) / 2, (ch - dh) / 2, dw, dh);
        }
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [clip.start, clip.end, layout.mode, layout.cam, videoRef, setTime]);

  const toggle = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      if (v.currentTime < clip.start || v.currentTime >= clip.end) v.currentTime = clip.start;
      v.play();
    } else v.pause();
  };

  const zoom = layout.zoom || 1;
  let vStyle;
  const splitTop = layout.split ?? 0.42;
  if (layout.mode === "split") {
    vStyle = { position: "absolute", left: 0, bottom: 0, width: "100%", height: `${(1 - splitTop) * 100}%`, objectFit: "cover",
      objectPosition: `${(layout.crop_x ?? 0.5) * 100}% 50%` };
  } else if (layout.mode === "crop") {
    vStyle = { width: "100%", height: "100%", objectFit: "cover", objectPosition: `${(layout.crop_x ?? 0.5) * 100}% 50%`, transform: `scale(${zoom})`, transformOrigin: `${(layout.crop_x ?? 0.5) * 100}% 50%` };
  } else if (layout.mode === "fit") {
    vStyle = { width: "100%", height: "100%", objectFit: "contain", background: "#000" };
  } else {
    vStyle = { width: `${100 * zoom}%`, maxHeight: "100%", objectFit: "contain", position: "relative", zIndex: 1 };
  }

  // live approximation of zoom / shake effects
  const rel = time - clip.start;
  let fz = 1, sx = 0, sy = 0;
  for (const e of clip.effects || []) {
    if (e.type === "zoom" && rel >= e.t && rel <= e.t + (e.dur || 0.9)) fz = Math.max(fz, e.scale || 1.3);
    if (e.type === "shake" && rel >= e.t && rel <= e.t + (e.dur || 0.6)) {
      const k = (1 - (rel - e.t) / (e.dur || 0.6)) * (e.strength || 1);
      fz = Math.max(fz, 1.08); sx = Math.sin(rel * 71) * 6 * k; sy = Math.sin(rel * 53 + 1.3) * 5 * k;
    }
  }
  const progress = Math.min(1, Math.max(0, (time - clip.start) / Math.max(0.1, clip.end - clip.start)));

  return (
    <div className="preview">
      <div className="preview-stage" ref={wrapRef}>
        {showRendered && (
          <div className={"frame " + (layout.format || "short")} style={{ width: box.w, height: box.h }}>
            <video key={rendered.url} src={rendered.url} controls autoPlay playsInline style={{ width: "100%", height: "100%", objectFit: "contain" }} />
            {rendered.stale && <div className="stale-tag">Changed since this preview — render again</div>}
          </div>
        )}
        <div className={"frame " + (layout.format || "short")} style={{ width: box.w, height: box.h, display: showRendered ? "none" : undefined }} onClick={toggle}>
          <div className="fx-wrap" style={{ transform: `translate(${sx}px, ${sy}px) scale(${fz})`, transition: fz === 1 ? "transform .12s" : "transform .05s" }}>
          {layout.mode === "blur" && <canvas ref={canvasRef} className="bg-canvas" width={180} height={320} />}
          {layout.mode === "split" && <canvas ref={camRef} className="cam-canvas" width={540} height={Math.round(960 * splitTop)} style={{ height: `${splitTop * 100}%` }} />}
          <video
            ref={videoRef}
            src={url.media(projectId)}
            style={vStyle}
            muted={muted}
            playsInline
            preload="auto"
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
          />
          </div>
          <CaptionOverlay clip={clip} styleDef={styleDef} time={time} frameH={box.h} />
          {(clip.effects || []).filter((e) => Math.abs(time - clip.start - e.t) < 0.6 && e.type !== "sfx").slice(0, 1).map((e) => (
            <div key={e.id} className="fx-flash">{e.type === "text" || e.type === "freeze" ? e.text : e.type.toUpperCase()}</div>
          ))}
          {!playing && <div className="play-hint"><Play size={36} fill="currentColor" /></div>}
        </div>
      </div>
      <div className="mode-row">
        <div className="segmented sm">
          <button className={!showRendered ? "on" : ""} onClick={() => onToggleRendered(false)}><Radio size={13} /> Live edit</button>
          <button className={showRendered ? "on" : ""} disabled={!rendered?.url} onClick={() => onToggleRendered(true)}><Film size={13} /> Final preview</button>
        </div>
        <button className="btn sm" onClick={onMakePreview} disabled={!!previewBusy}>
          {previewBusy ? <><Loader2 size={13} className="spin" /> {Math.round((previewBusy.progress || 0) * 100)}%</> : <><Eye size={13} /> Render preview</>}
        </button>
      </div>
      <div className="transport" style={{ display: showRendered ? "none" : undefined }}>
        <button className="icon-btn lg" onClick={toggle}>{playing ? <Pause size={20} /> : <Play size={20} />}</button>
        <button className="icon-btn" onClick={() => { const v = videoRef.current; if (v) { v.currentTime = clip.start; setTime(clip.start); } }} title="Back to start"><RotateCcw size={17} /></button>
        <div className="t-bar"><span style={{ width: `${progress * 100}%` }} /></div>
        <span className="t-time mono">{fmtTime(Math.max(0, time - clip.start), true)} / {fmtTime(clip.end - clip.start, true)}</span>
        <button className="icon-btn" onClick={() => setMuted((m) => !m)}>{muted ? <VolumeX size={17} /> : <Volume2 size={17} />}</button>
      </div>
    </div>
  );
}
