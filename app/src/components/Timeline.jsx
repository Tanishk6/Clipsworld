import React, { useEffect, useRef, useState } from "react";
import { ZoomIn, ZoomOut, Crosshair } from "lucide-react";
import { fmtTime } from "../api.js";

// Waveform timeline around the selected clip, with draggable start/end handles.
export default function Timeline({ wave, duration, clip, clips, time, onSeek, onTrim }) {
  const ref = useRef(null);
  const canvasRef = useRef(null);
  const [drag, setDrag] = useState(null); // {which, start, end}
  const [width, setWidth] = useState(800);

  const s0 = drag ? drag.start : clip.start;
  const e0 = drag ? drag.end : clip.end;
  const len = Math.max(1, clip.end - clip.start);
  const pad = Math.max(8, len * 0.6);
  // view window: follows the clip until you scroll / drag / zoom it yourself
  const [view, setView] = useState(null); // {start, span}
  useEffect(() => setView(null), [clip.id]);
  const autoStart = Math.max(0, clip.start - pad);
  const autoSpan = Math.max(1, Math.min(duration, clip.end + pad) - autoStart);
  const span = Math.min(duration, Math.max(3, view ? view.span : autoSpan));
  const vs = Math.min(Math.max(0, duration - span), Math.max(0, view ? view.start : autoStart));
  const ve = vs + span;
  const setViewSafe = (start, sp) => {
    const nsp = Math.min(duration, Math.max(3, sp));
    setView({ start: Math.min(Math.max(0, duration - nsp), Math.max(0, start)), span: nsp });
  };
  const x = (t) => ((t - vs) / span) * width;
  const tAt = (px) => vs + (px / width) * span;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const c = canvasRef.current;
    if (!c || !wave) return;
    const dpr = window.devicePixelRatio || 1;
    const H = 78;
    c.width = width * dpr;
    c.height = H * dpr;
    const ctx = c.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, H);
    const vals = wave.values || [];
    const hop = wave.hop || 0.25;
    const bars = Math.floor(width / 3);
    for (let i = 0; i < bars; i++) {
      const t = vs + (i / bars) * span;
      const j = Math.floor(t / hop);
      const v = vals[Math.min(vals.length - 1, Math.max(0, j))] || 0;
      const h = Math.max(2, Math.pow(v, 1.6) * (H - 8));
      const inClip = t >= s0 && t <= e0;
      ctx.fillStyle = inClip ? "rgba(178,150,255,0.95)" : "rgba(140,140,170,0.35)";
      ctx.fillRect(i * 3, (H - h) / 2, 2, h);
    }
  }, [wave, width, vs, span, s0, e0]);

  useEffect(() => {
    if (!drag) return;
    const move = (ev) => {
      const r = ref.current.getBoundingClientRect();
      const t = Math.min(duration, Math.max(0, tAt(ev.clientX - r.left)));
      setDrag((d) => {
        if (!d) return d;
        if (d.which === "start") return { ...d, start: Math.min(t, d.end - 1) };
        if (d.which === "end") return { ...d, end: Math.max(t, d.start + 1) };
        const shift = t - d.grab;
        const L = d.oe - d.os;
        const ns = Math.min(duration - L, Math.max(0, d.os + shift));
        return { ...d, start: ns, end: ns + L };
      });
    };
    const up = () => {
      setDrag((d) => {
        if (d) onTrim(Math.round(d.start * 100) / 100, Math.round(d.end * 100) / 100);
        return null;
      });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
    return () => window.removeEventListener("pointermove", move);
  }, [drag ? drag.which : null]); // eslint-disable-line react-hooks/exhaustive-deps

  const begin = (which) => (ev) => {
    ev.stopPropagation();
    const r = ref.current.getBoundingClientRect();
    setDrag({ which, start: clip.start, end: clip.end, os: clip.start, oe: clip.end, grab: tAt(ev.clientX - r.left) });
  };

  // drag the empty timeline to move it left/right; a short click seeks
  const click = (ev) => {
    const r = ref.current.getBoundingClientRect();
    const startX = ev.clientX;
    const v0 = vs;
    let moved = false;
    const move = (e) => {
      const dx = e.clientX - startX;
      if (!moved && Math.abs(dx) < 4) return;
      moved = true;
      setViewSafe(v0 - (dx / width) * span, span);
    };
    const up = (e) => {
      window.removeEventListener("pointermove", move);
      if (!moved) onSeek(tAt(e.clientX - r.left));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
  };

  const wheel = (ev) => {
    const r = ref.current.getBoundingClientRect();
    if (ev.shiftKey || Math.abs(ev.deltaX) > Math.abs(ev.deltaY)) {
      const d = (ev.deltaX || ev.deltaY) / width * span;
      setViewSafe(vs + d, span);
      return;
    }
    const at = tAt(ev.clientX - r.left);
    const f = ev.deltaY > 0 ? 1.2 : 1 / 1.2;
    const nsp = Math.min(duration, Math.max(3, span * f));
    setViewSafe(at - ((at - vs) / span) * nsp, nsp);
  };

  const overviewNav = (ev) => {
    const el = ev.currentTarget;
    const go = (e) => {
      const r = el.getBoundingClientRect();
      const t = Math.min(duration, Math.max(0, ((e.clientX - r.left) / r.width) * duration));
      setViewSafe(t - span / 2, span);
      return t;
    };
    const t = go(ev);
    onSeek(t);
    const move = (e) => go(e);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", () => window.removeEventListener("pointermove", move), { once: true });
  };

  const ticks = [];
  const step = span > 240 ? 60 : span > 90 ? 15 : span > 40 ? 5 : 2;
  for (let t = Math.ceil(vs / step) * step; t <= ve; t += step) ticks.push(t);

  return (
    <div className="timeline">
      <div className="tl-tools">
        <span className="muted tiny">Drag the timeline to move it · scroll to zoom · drag the purple box to move the clip</span>
        <div className="row gap">
          <button className="icon-btn" title="Zoom out" onClick={() => setViewSafe(vs - span * 0.25, span * 1.5)}><ZoomOut size={15} /></button>
          <button className="icon-btn" title="Zoom in" onClick={() => setViewSafe(vs + span * 0.17, span / 1.5)}><ZoomIn size={15} /></button>
          <button className="icon-btn" title="Back to this clip" onClick={() => setView(null)}><Crosshair size={15} /></button>
        </div>
      </div>
      <div className="overview" title="Whole video — click or drag to move around" onPointerDown={overviewNav}>
        <span className="ov-view" style={{ left: `${(vs / duration) * 100}%`, width: `${(span / duration) * 100}%` }} />
        {clips.map((c) => (
          <span key={c.id} className={"ov-clip" + (c.id === clip.id ? " on" : "")}
            style={{ left: `${(c.start / duration) * 100}%`, width: `${Math.max(0.4, ((c.end - c.start) / duration) * 100)}%` }} />
        ))}
        <span className="ov-head" style={{ left: `${(time / duration) * 100}%` }} />
      </div>
      <div className="tl-main" ref={ref} onPointerDown={click} onWheel={wheel}>
        <canvas ref={canvasRef} style={{ width: "100%", height: 78 }} />
        <div className="tl-region" style={{ left: x(s0), width: Math.max(2, x(e0) - x(s0)) }} onPointerDown={begin("move")}>
          <div className="tl-handle l" onPointerDown={begin("start")}><span /></div>
          <div className="tl-handle r" onPointerDown={begin("end")}><span /></div>
          <div className="tl-len mono">{(e0 - s0).toFixed(1)}s</div>
        </div>
        {(clip.captions?.cues || []).map((q, i) => (
          <span key={i} className="tl-cue" style={{ left: x(q.start), width: Math.max(1, x(q.end) - x(q.start)) }} />
        ))}
        {(clip.effects || []).map((e) => (
          <span key={e.id} className={"tl-fx " + e.type} title={e.type} style={{ left: x(clip.start + e.t) }} />
        ))}
        <div className="tl-head" style={{ left: x(time) }} />
        <div className="tl-ticks">
          {ticks.map((t) => <span key={t} style={{ left: x(t) }}>{fmtTime(t)}</span>)}
        </div>
      </div>
    </div>
  );
}
