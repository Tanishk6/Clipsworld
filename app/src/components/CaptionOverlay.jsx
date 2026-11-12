import React from "react";

// Live HTML version of the ASS caption styles, so the preview matches the export.
export default function CaptionOverlay({ clip, styleDef, time, frameH }) {
  const cap = clip.captions || {};
  const k = frameH / 1920;
  const nodes = [];

  const rel = time - clip.start;
  if (cap.show_hook && clip.hook && rel >= 0 && rel < 3) {
    nodes.push(
      <div key="hook" className="cap-hook" style={{ fontSize: 64 * k, top: 250 * k, padding: `${10 * k}px ${22 * k}px` }}>
        {clip.hook}
      </div>
    );
  }
  if (cap.enabled === false || !styleDef) return <div className="cap-layer">{nodes}</div>;

  const cues = cap.cues || [];
  const idx = cues.findIndex((c) => time >= c.start && time < c.end);
  if (idx >= 0) {
    const cue = cues[idx];
    const st = styleDef;
    const upper = cap.uppercase == null ? st.upper : cap.uppercase;
    const words = cue.words && cue.words.length ? cue.words : cue.text.split(" ").map((w) => ({ word: w, start: cue.start, end: cue.end }));
    let active = 0;
    words.forEach((w, i) => { if (time >= w.start) active = i; });
    const hasDeva = /[ऀ-ॿ]/.test(cue.text);
    const font = !st.deva && hasDeva ? "Mukta ExtraBold" : st.font;
    const size = (!st.deva && hasDeva ? 88 : st.size) * k;
    const pos = cap.position || "bottom";
    const posStyle = pos === "bottom" ? { bottom: 420 * k } : pos === "top" ? { top: 330 * k } : { top: "50%", transform: "translateY(-50%)" };
    const stroke = st.box ? 0 : Math.max(1, st.bord * k * 2);
    const base = {
      fontFamily: `"${font}", "Nirmala UI", "Segoe UI", sans-serif`,
      fontSize: size,
      color: st.color,
      WebkitTextStroke: stroke ? `${stroke}px ${st.outline}` : undefined,
      paintOrder: "stroke fill",
      textShadow: st.blur ? `0 0 ${8 * k}px ${st.color}, 0 0 ${22 * k}px ${st.color}` : st.shadow ? `0 ${3 * k}px ${4 * k}px rgba(0,0,0,.6)` : undefined,
      lineHeight: 1.05,
      letterSpacing: 1,
    };
    nodes.push(
      <div key={"cue" + idx} className={"cap-line" + (st.pop ? " pop" : "")} style={{ ...posStyle, left: 70 * k, right: 70 * k }}>
        <span className={st.box ? "cap-box" : ""} style={{ ...base, padding: st.box ? `${6 * k}px ${16 * k}px` : 0 }}>
          {words.map((w, i) => {
            let text = upper ? w.word.toUpperCase() : w.word;
            let s = {};
            if (st.karaoke) {
              const p = time >= w.end ? 1 : time <= w.start ? 0 : (time - w.start) / Math.max(0.01, w.end - w.start);
              s = {
                backgroundImage: `linear-gradient(90deg, ${st.color} ${p * 100}%, ${st.karaoke} ${p * 100}%)`,
                WebkitBackgroundClip: "text",
                backgroundClip: "text",
                color: "transparent",
              };
            } else if (st.active && i === active) {
              s = { color: st.active, display: "inline-block", margin: "0 0.08em", transform: `scale(${st.active_scale / 100})`, textShadow: st.blur ? `0 0 ${10 * k}px ${st.active}, 0 0 ${26 * k}px ${st.active}` : base.textShadow };
            }
            return (
              <React.Fragment key={i}>
                <span className="cap-word" style={s}>{text}</span>
                {i < words.length - 1 ? " " : ""}
              </React.Fragment>
            );
          })}
        </span>
      </div>
    );
  }
  return <div className="cap-layer">{nodes}</div>;
}
