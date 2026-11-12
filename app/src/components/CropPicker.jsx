import React, { useRef, useState } from "react";
import { url } from "../api.js";

// Pick the exact part of the video to show. The box keeps the output shape (9:16, 1:1 or 16:9).
// box = {x, y, w} as parts of the source frame; height follows from the shape.
export function boxHeight(w, srcW, srcH, targetRatio) {
  return (w * (srcW / srcH)) / targetRatio;
}

export function fitBox(box, srcW, srcH, targetRatio) {
  let w = Math.min(1, Math.max(0.05, box.w));
  let h = boxHeight(w, srcW, srcH, targetRatio);
  if (h > 1) { w = w / h; h = 1; }
  const x = Math.min(1 - w, Math.max(0, box.x));
  const y = Math.min(1 - h, Math.max(0, box.y));
  return { x, y, w, h };
}

export function defaultBox(srcW, srcH, targetRatio) {
  // biggest box of the right shape, centered
  const hFull = boxHeight(1, srcW, srcH, targetRatio);
  const w = hFull > 1 ? 1 / hFull : 1;
  const b = fitBox({ x: 0, y: 0, w }, srcW, srcH, targetRatio);
  return { x: (1 - b.w) / 2, y: (1 - b.h) / 2, w: b.w };
}

export default function CropPicker({ projectId, t, info, targetRatio, box, onChange }) {
  const ref = useRef(null);
  const [live, setLive] = useState(null);
  const srcW = info.width || 1920;
  const srcH = info.height || 1080;
  const b = fitBox(live || box || defaultBox(srcW, srcH, targetRatio), srcW, srcH, targetRatio);

  const begin = (mode) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    const r = ref.current.getBoundingClientRect();
    const start = { x: e.clientX, y: e.clientY, b: { ...b } };
    let last = null;
    const move = (ev) => {
      const dx = (ev.clientX - start.x) / r.width;
      const dy = (ev.clientY - start.y) / r.height;
      let nb;
      if (mode === "move") nb = { x: start.b.x + dx, y: start.b.y + dy, w: start.b.w };
      else nb = { x: start.b.x, y: start.b.y, w: Math.max(0.05, start.b.w + dx) };
      last = fitBox(nb, srcW, srcH, targetRatio);
      setLive(last);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      setLive(null);
      if (last) onChange({ x: +last.x.toFixed(4), y: +last.y.toFixed(4), w: +last.w.toFixed(4) });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
  };

  return (
    <div className="campick" ref={ref}>
      <img src={url.frame(projectId, t)} alt="" draggable={false} />
      <div className="cp-shade" style={{ clipPath: `polygon(0 0,100% 0,100% 100%,0 100%,0 ${b.y * 100}%,${b.x * 100}% ${b.y * 100}%,${b.x * 100}% ${(b.y + b.h) * 100}%,${(b.x + b.w) * 100}% ${(b.y + b.h) * 100}%,${(b.x + b.w) * 100}% ${b.y * 100}%,0 ${b.y * 100}%)` }} />
      <div className="cp-box crop" onPointerDown={begin("move")}
        style={{ left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%` }}>
        <span className="cp-label">In your Short</span>
        <div className="cp-handle" onPointerDown={begin("size")} title="Drag to make bigger / smaller" />
      </div>
    </div>
  );
}
