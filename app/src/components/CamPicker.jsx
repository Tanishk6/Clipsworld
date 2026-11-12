import React, { useRef, useState } from "react";
import { url } from "../api.js";

// Drag a box over the stream's webcam area. Values are 0..1 of the source frame.
export default function CamPicker({ projectId, t, cam, onChange }) {
  const ref = useRef(null);
  const [drag, setDrag] = useState(null);
  const [box, setBox] = useState(cam);
  const b = drag ? box : cam;

  const begin = (mode) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    const r = ref.current.getBoundingClientRect();
    const start = { x: e.clientX, y: e.clientY, cam: { ...cam } };
    setBox(cam);
    setDrag(mode);
    const move = (ev) => {
      const dx = (ev.clientX - start.x) / r.width;
      const dy = (ev.clientY - start.y) / r.height;
      const c = { ...start.cam };
      if (mode === "move") {
        c.x = Math.min(1 - c.w, Math.max(0, c.x + dx));
        c.y = Math.min(1 - c.h, Math.max(0, c.y + dy));
      } else {
        c.w = Math.min(1 - c.x, Math.max(0.06, c.w + dx));
        c.h = Math.min(1 - c.y, Math.max(0.06, c.h + dy));
      }
      setBox(c);
      start.last = c;
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      setDrag(null);
      if (start.last) onChange(Object.fromEntries(Object.entries(start.last).map(([k, v]) => [k, Math.round(v * 1000) / 1000])));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
  };

  return (
    <div className="campick" ref={ref}>
      <img src={url.frame(projectId, t)} alt="" draggable={false} />
      <div className="cp-shade" style={{ clipPath: `polygon(0 0,100% 0,100% 100%,0 100%,0 ${b.y * 100}%,${b.x * 100}% ${b.y * 100}%,${b.x * 100}% ${(b.y + b.h) * 100}%,${(b.x + b.w) * 100}% ${(b.y + b.h) * 100}%,${(b.x + b.w) * 100}% ${b.y * 100}%,0 ${b.y * 100}%)` }} />
      <div className="cp-box" onPointerDown={begin("move")}
        style={{ left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%` }}>
        <span className="cp-label">Facecam</span>
        <div className="cp-handle" onPointerDown={begin("size")} />
      </div>
    </div>
  );
}
