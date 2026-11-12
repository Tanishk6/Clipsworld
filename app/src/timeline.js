// Mirror of the engine's output timeline (freeze frames and replays add time).
export function buildTimeline(L, effects = []) {
  const inserts = [];
  for (const e of effects) {
    if (e.type === "freeze") {
      const t = Math.min(Math.max(0.05, e.t), L - 0.05);
      inserts.push([t, 0, { kind: "freeze", a: t, b: t, speed: 1, dur: Math.max(0.3, e.dur || 1.2) }]);
    } else if (e.type === "replay") {
      const end = Math.min(Math.max(0.3, e.t), L);
      const start = Math.max(0, end - Math.max(0.5, e.dur || 2.5));
      const speed = Math.min(1, Math.max(0.5, e.speed || 0.6));
      inserts.push([end, 1, { kind: "replay", a: start, b: end, speed, dur: (end - start) / speed }]);
    }
  }
  inserts.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
  const segs = [];
  let cur = 0;
  for (const [pos, , seg] of inserts) {
    if (pos > cur + 0.01) { segs.push({ kind: "normal", a: cur, b: pos, speed: 1, dur: pos - cur }); cur = pos; }
    segs.push(seg);
  }
  if (L > cur + 0.01) segs.push({ kind: "normal", a: cur, b: L, speed: 1, dur: L - cur });
  let o = 0;
  for (const s of segs) { s.out_a = o; s.out_b = o + s.dur; o += s.dur; }
  return segs;
}

export function outToSrc(segs, t) {
  for (const s of segs) {
    if (t >= s.out_a && t <= s.out_b) {
      if (s.kind === "freeze") return s.a;
      if (s.kind === "replay") return s.a + (t - s.out_a) * s.speed;
      return s.a + (t - s.out_a);
    }
  }
  return segs.length ? segs[segs.length - 1].b : t;
}
