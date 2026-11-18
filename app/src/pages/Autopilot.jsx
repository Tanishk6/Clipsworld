import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle, Bot, CalendarClock, Check, CheckCircle2, Clock, ExternalLink, Film, Link2, Loader2, Play, Plus,
  MonitorPlay as Youtube, RotateCcw, Settings2, ShieldCheck, Sparkles, Trash2, Upload, Wand2, X,
} from "lucide-react";
import { api, desktop, url } from "../api.js";
import { useApp, useToast } from "../App.jsx";
import { DownloadRow } from "../components/Downloads.jsx";

const open = (u) => (desktop ? desktop.openExternal(u) : window.open(u, "_blank"));

function when(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const today = new Date();
  const tmr = new Date(); tmr.setDate(today.getDate() + 1);
  const day = d.toDateString() === today.toDateString() ? "Today" : d.toDateString() === tmr.toDateString() ? "Tomorrow"
    : d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  return `${day} ${d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
}

const STATUS = {
  producing: ["Making…", ""], review: ["Needs review", "warn"], approved: ["Waiting to upload", ""],
  uploading: ["Uploading…", ""], scheduled: ["Scheduled on YouTube", "ok"], uploaded: ["Posted", "ok"],
  failed: ["Failed", "bad"], rejected: ["Rejected", ""], render_failed: ["Couldn't make", "bad"], queued_again: ["Remaking…", ""],
};
const SRC = { queued: "Waiting", analysing: "Analysing…", ready: "Clips found", empty: "No clips found", error: "Error" };

export default function Autopilot() {
  const { settings, refreshSettings, go } = useApp();
  const toast = useToast();
  const [st, setSt] = useState(null);
  const [tab, setTab] = useState("review");

  const load = useCallback(async () => {
    try { setSt(await api.autopilot()); } catch (_) { /* engine busy */ }
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, [load]);

  const saveS = async (patch) => {
    try { await api.saveSettings(patch); await refreshSettings(); await load(); } catch (e) { toast(e.message, "error"); }
  };
  const act = async (fn, okMsg) => {
    try { await fn(); okMsg && toast(okMsg); await load(); } catch (e) { toast(e.message, "error"); }
  };

  if (!st) return <div className="page"><Loader2 className="spin" /></div>;
  const c = st.counts || {};
  const review = st.items.filter((i) => ["review", "producing", "queued_again"].includes(i.status));
  const sched = st.items.filter((i) => ["approved", "uploading", "scheduled", "uploaded", "failed", "render_failed"].includes(i.status));
  const nextPost = st.items.filter((i) => i.status === "scheduled" && new Date(i.publish_at) > new Date())
    .map((i) => i.publish_at).sort()[0];
  const steps = [
    { ok: settings.has_api_key, label: "Claude API key", fix: () => go("settings") },
    { ok: st.youtube.connected, label: "YouTube connected", fix: () => setTab("setup") },
    { ok: st.sources.length > 0, label: "Video links added", fix: () => setTab("videos") },
  ];
  const allReady = steps.every((s) => s.ok);
  const w = st.worker;

  return (
    <div className="page ap">
      <div className="ap-head">
        <h1 className="page-title"><Bot size={28} /> Autopilot</h1>
        <div className="ap-power">
          <div className="ap-power-txt">
            <b>{st.enabled ? "Autopilot is ON" : "Autopilot is OFF"}</b>
            <span className="muted tiny">{st.enabled ? `Posting ${st.slots.length} Shorts a day at ${st.slots.join(", ")}` : "Turn it on to start making clips"}</span>
          </div>
          <button className={"ap-switch" + (st.enabled ? " on" : "")} disabled={!allReady && !st.enabled}
            title={!allReady ? "Finish the setup steps first" : ""}
            onClick={() => saveS({ ap_enabled: !st.enabled }).then(() => toast(st.enabled ? "Autopilot paused" : "Autopilot started — clips will appear in Review"))}>
            <span />
          </button>
        </div>
      </div>

      {!allReady && (
        <div className="ap-steps">
          {steps.map((s, i) => (
            <button key={i} className={"ap-step" + (s.ok ? " ok" : "")} onClick={s.fix}>
              {s.ok ? <CheckCircle2 size={16} /> : <span className="ap-num">{i + 1}</span>} {s.label}
            </button>
          ))}
        </div>
      )}

      <div className="ap-stats">
        <Stat icon={Sparkles} n={c.review || 0} label="to review" hot={c.review > 0} onClick={() => setTab("review")} />
        <Stat icon={CalendarClock} n={(c.scheduled || 0) + (c.approved || 0)} label="scheduled" onClick={() => setTab("schedule")} />
        <Stat icon={Youtube} n={st.items.filter((i) => i.video_id && (i.status === "uploaded" || (i.status === "scheduled" && new Date(i.publish_at) <= new Date()))).length} label="posted" onClick={() => setTab("schedule")} />
        <Stat icon={Clock} n={nextPost ? when(nextPost) : "—"} label="next post" small />
        <div className="ap-worker">
          {w.busy ? (
            <>
              <div className="row gap"><Loader2 size={15} className="spin" /><span className="ap-wstage">{w.stage || "Working…"}</span></div>
              <div className="pbar"><span style={{ width: `${Math.round(w.progress * 100)}%` }} /></div>
            </>
          ) : (
            <div className="row gap" style={{ justifyContent: "space-between" }}>
              <span className="muted tiny">{st.enabled ? "Idle — checks every 20 s" : "Paused"}</span>
              <button className="btn sm" disabled={!st.sources.length && !c.approved} onClick={() => act(api.autopilotRun)}><Play size={13} /> Run now</button>
            </div>
          )}
        </div>
      </div>

      <div className="seg-tabs ap-tabs">
        {[["review", `Review${c.review ? ` (${c.review})` : ""}`, Sparkles], ["schedule", "Schedule", CalendarClock],
          ["videos", `Video links (${st.sources.length})`, Link2], ["setup", "Setup", Settings2]].map(([id, label, Icon]) => (
          <button key={id} className={"seg" + (tab === id ? " on" : "")} onClick={() => setTab(id)}><Icon size={15} /> {label}</button>
        ))}
      </div>

      {tab === "review" && <ReviewTab items={review} st={st} act={act} />}
      {tab === "schedule" && <ScheduleTab items={sched} act={act} />}
      {tab === "videos" && <VideosTab st={st} act={act} />}
      {tab === "setup" && <SetupTab st={st} settings={settings} saveS={saveS} load={load} />}
    </div>
  );
}

function Stat({ icon: Icon, n, label, hot, small, onClick }) {
  return (
    <button className={"ap-stat" + (hot ? " hot" : "")} onClick={onClick} disabled={!onClick}>
      <Icon size={18} />
      <b className={small ? "small" : ""}>{n}</b>
      <span>{label}</span>
    </button>
  );
}

// ------------------------------------------------------------------ Review
function ReviewTab({ items, st, act }) {
  if (!items.length) {
    return (
      <div className="empty">
        Nothing to review yet. {st.enabled ? "Autopilot is making clips — they'll show up here." : "Add video links and turn Autopilot on."}
      </div>
    );
  }
  let slotI = 0;
  return (
    <div className="ap-review">
      {items.map((it) => it.status === "review"
        ? <ReviewCard key={it.id} it={it} slot={st.next_slots[slotI++]} act={act} />
        : <MakingCard key={it.id} it={it} st={st} />)}
    </div>
  );
}

function MakingCard({ it, st }) {
  const mine = st.worker.item === it.id;
  return (
    <div className="ap-card making">
      <div className="ap-video ph"><Wand2 size={30} className={mine ? "pulse" : ""} /></div>
      <div className="ap-fields">
        <div className="ap-title-ro">{it.title || "New clip"}</div>
        <div className="muted tiny">{mine ? st.worker.stage : "Waiting for its turn…"}</div>
        {mine && <div className="pbar"><span style={{ width: `${Math.round(st.worker.progress * 100)}%` }} /></div>}
      </div>
    </div>
  );
}

function ReviewCard({ it, slot, act }) {
  const [title, setTitle] = useState(it.title);
  const [desc, setDesc] = useState(it.description);
  const [tags, setTags] = useState((it.tags || []).join(", "));
  const dirty = title !== it.title || desc !== it.description || tags !== (it.tags || []).join(", ");
  const patch = { title, description: desc, tags };
  return (
    <div className="ap-card">
      <div className="ap-video">
        <video src={url.file(it.video_path)} controls playsInline preload="metadata" />
      </div>
      <div className="ap-fields">
        <div className="row gap wrap">
          <span className={"chip " + (it.engine === "hyperframes" ? "violet" : "")} title={it.engine_note || ""}>
            {it.engine === "hyperframes" ? <><Sparkles size={11} /> Motion graphics</> : <><Film size={11} /> Fast editor</>}
          </span>
          {it.duration && <span className="chip">{it.duration}s</span>}
          <span className="chip">Captions: {it.style}</span>
          {it.engine_note && <span className="chip warn" title={it.engine_note}><AlertTriangle size={11} /> Motion graphics skipped</span>}
        </div>
        <label>Title <span className="muted">{title.length}/100</span></label>
        <input className="input" value={title} maxLength={100} onChange={(e) => setTitle(e.target.value)} />
        <label>Description</label>
        <textarea className="input" rows={4} value={desc} onChange={(e) => setDesc(e.target.value)} />
        <label>Tags <span className="muted">comma separated</span></label>
        <input className="input" value={tags} onChange={(e) => setTags(e.target.value)} />
        <div className="ap-actions">
          <span className="muted tiny"><CalendarClock size={13} /> Posts {when(slot)}</span>
          <div className="row gap">
            {dirty && <button className="btn sm" onClick={() => act(() => api.apEdit(it.id, patch), "Saved")}>Save</button>}
            <button className="btn ghost sm" onClick={() => act(() => api.apReject(it.id), "Rejected")}><X size={14} /> Reject</button>
            <button className="btn primary sm" onClick={() => act(() => api.apApprove(it.id, patch), "Approved — it will be uploaded and scheduled")}>
              <Check size={14} /> Approve
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Schedule
function ScheduleTab({ items, act }) {
  if (!items.length) return <div className="empty">No clips scheduled yet. Approve clips in Review.</div>;
  return (
    <div className="ap-list">
      {items.map((it) => {
        const [label, kind] = STATUS[it.status] || [it.status, ""];
        const live = it.status === "scheduled" && new Date(it.publish_at) <= new Date();
        return (
          <div key={it.id} className="ap-row">
            <div className="ap-row-thumb">{it.thumb && <img src={url.file(it.thumb)} alt="" onError={(e) => { e.currentTarget.style.display = "none"; }} />}</div>
            <div className="ap-row-main">
              <div className="ap-row-title">{it.title}</div>
              <div className="muted tiny">
                <CalendarClock size={12} /> {when(it.publish_at)}
                {it.error && <span className="bad"> · {it.error}</span>}
                {it.note && <span className="warnc"> · {it.note}</span>}
              </div>
            </div>
            <span className={"chip " + (live ? "ok" : kind)}>{live ? "Live on YouTube" : label}</span>
            {it.video_id && <button className="btn ghost sm" onClick={() => open(`https://youtu.be/${it.video_id}`)}><ExternalLink size={13} /> Open</button>}
            {["failed", "render_failed"].includes(it.status) && <button className="btn sm" onClick={() => act(() => api.apRetry(it.id), "Trying again")}><RotateCcw size={13} /> Retry</button>}
            {!["uploading", "producing"].includes(it.status) && (
              <button className="icon-btn" title="Remove from the list" onClick={() => act(() => api.apDelete(it.id))}><Trash2 size={15} /></button>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ Videos
function VideosTab({ st, act }) {
  const [text, setText] = useState("");
  const links = useMemo(() => text.split(/\s+/).filter((x) => /^https?:\/\//i.test(x)), [text]);
  return (
    <div className="ap-videos">
      <div className="set-card">
        <div className="set-head"><Link2 size={18} /><div><h3>Add video links</h3>
          <p className="muted tiny">Paste one or many links (YouTube, etc.). Autopilot clips them in order. Only use videos you own or have permission to clip.</p></div></div>
        <textarea className="input" rows={4} placeholder={"https://www.youtube.com/watch?v=…\nhttps://youtu.be/…"} value={text} onChange={(e) => setText(e.target.value)} />
        <div className="row gap" style={{ marginTop: 10, justifyContent: "space-between" }}>
          <span className="muted tiny">{links.length} link{links.length === 1 ? "" : "s"}</span>
          <button className="btn primary" disabled={!links.length}
            onClick={() => act(async () => { const r = await api.apAddSources(links); setText(""); if (!r.added) throw new Error("Those links are already in the list."); }, "Added")}>
            <Plus size={15} /> Add to queue
          </button>
        </div>
      </div>
      <div className="ap-list">
        {st.sources.map((s) => (
          <div key={s.id} className="ap-row">
            <div className="ap-row-main">
              <div className="ap-row-title">{s.title || s.url}</div>
              <div className="muted tiny">{s.url}{s.error && <span className="bad"> · {s.error}</span>}</div>
            </div>
            <span className={"chip " + (s.status === "ready" ? "ok" : s.status === "error" ? "bad" : "")}>
              {s.status === "analysing" && <Loader2 size={11} className="spin" />} {SRC[s.status] || s.status}
              {s.clips ? ` · ${s.used.length}/${s.clips} used` : ""}
            </span>
            {s.status === "error" && <button className="btn sm" onClick={() => act(() => api.apRetrySource(s.id))}><RotateCcw size={13} /> Retry</button>}
            {s.status !== "analysing" && <button className="icon-btn" onClick={() => act(() => api.apRemoveSource(s.id))}><Trash2 size={15} /></button>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Setup
function SetupTab({ st, settings, saveS, load }) {
  const toast = useToast();
  const yt = st.youtube;
  const [cid, setCid] = useState("");
  const [secret, setSecret] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [editClient, setEditClient] = useState(false);
  const [auto, setAuto] = useState(false);
  const [times, setTimes] = useState(settings.ap_times || []);
  useEffect(() => { desktop && desktop.getAutoStart && desktop.getAutoStart().then(setAuto).catch(() => {}); }, []);
  useEffect(() => { if (waiting && yt.connected) { setWaiting(false); toast(`Connected to ${yt.channel?.title || "YouTube"} ✓`); } }, [waiting, yt.connected, yt.channel, toast]);

  const saveClient = async () => {
    try { await api.ytClient(cid, secret); setCid(""); setSecret(""); setEditClient(false); await load(); toast("Saved. Now press Connect YouTube."); } catch (e) { toast(e.message, "error"); }
  };
  const connect = async () => {
    try { const r = await api.ytConnect(); setWaiting(true); open(r.url); } catch (e) { toast(e.message, "error"); }
  };
  const perDay = settings.ap_per_day || 5;
  const setPerDay = (n) => {
    const base = ["10:00", "13:00", "16:00", "19:00", "21:30", "08:00", "11:30", "14:30", "17:30", "20:00", "22:30", "23:30"];
    const next = [...times];
    for (const t of base) if (next.length < n && !next.includes(t)) next.push(t);
    const sorted = next.slice(0, Math.max(n, 1)).sort();
    setTimes(sorted);
    saveS({ ap_per_day: n, ap_times: sorted });
  };

  return (
    <div className="set-grid">
      <div className="set-card">
        <div className="set-head"><Youtube size={18} /><div><h3>YouTube channel</h3><p className="muted tiny">Clipsworld uploads with your own Google project (free). One-time setup, ~10 minutes.</p></div></div>
        {yt.connected ? (
          <div className="key-on">
            <div className="key-pill">{yt.channel?.thumb && <img src={yt.channel.thumb} alt="" className="yt-av" />}<Check size={15} /> {yt.channel?.title || "Connected"}</div>
            <button className="btn ghost sm" onClick={async () => { await api.ytDisconnect(); load(); }}>Disconnect</button>
          </div>
        ) : yt.has_client ? (
          <div className="col gap">
            <p className="muted tiny">Client ID {yt.client_id_hint} saved.</p>
            <div className="row gap">
              <button className="btn primary" onClick={connect}>{waiting ? <Loader2 size={15} className="spin" /> : <Youtube size={15} />} Connect YouTube</button>
              <button className="btn ghost sm" onClick={() => setEditClient(!editClient)}>Change client</button>
            </div>
            {waiting && <p className="hint">Sign in in your browser and allow access. Google may say the app isn't verified: click <b>Advanced → Go to Clipsworld</b> (it's your own project).</p>}
          </div>
        ) : null}
        {!yt.connected && (!yt.has_client || editClient) && (
          <>
            <ol className="rules ap-guide">
              <li>Open <a onClick={() => open("https://console.cloud.google.com/projectcreate")}>Google Cloud → New project</a>, name it “Clipsworld”.</li>
              <li>Enable <a onClick={() => open("https://console.cloud.google.com/apis/library/youtube.googleapis.com")}>YouTube Data API v3</a>.</li>
              <li>Open <a onClick={() => open("https://console.cloud.google.com/auth/branding")}>Google Auth Platform</a> → Get started: app name Clipsworld, audience <b>External</b>, your email.</li>
              <li>Audience → <b>Test users</b> → add the Google account that owns your channel.</li>
              <li><a onClick={() => open("https://console.cloud.google.com/auth/clients/create")}>Clients → Create client</a> → type <b>Desktop app</b> → copy the Client ID and secret (or download the JSON).</li>
            </ol>
            <div className="field"><label>Client ID (or paste the whole JSON file)</label>
              <input className="input mono" value={cid} placeholder="1234-abc.apps.googleusercontent.com" onChange={(e) => setCid(e.target.value)} /></div>
            <div className="field"><label>Client secret</label>
              <input className="input mono" type="password" value={secret} placeholder="GOCSPX-…" onChange={(e) => setSecret(e.target.value)} /></div>
            <button className="btn primary" disabled={!cid.trim()} onClick={saveClient}><Check size={15} /> Save</button>
            <p className="hint">Saved only on this PC.</p>
          </>
        )}
      </div>

      <div className="set-card">
        <div className="set-head"><ShieldCheck size={18} /><div><h3>Make uploads public (YouTube audit)</h3><p className="muted tiny">Required once for new Google projects.</p></div></div>
        <p className="big muted" style={{ fontSize: 13 }}>
          YouTube keeps videos uploaded by a brand-new, unaudited Google project <b>private</b>. Clipsworld still uploads and schedules them,
          but to post publicly you need to pass YouTube's free API compliance audit (usually a few days to a few weeks).
        </p>
        <ol className="rules">
          <li>Fill the <a onClick={() => open("https://support.google.com/youtube/contact/yt_api_form")}>YouTube API Services audit form</a>.</li>
          <li>Describe it as: “Personal desktop app that uploads Shorts I edit to my own channel. Only my account uses it.”</li>
          <li>Give your channel link and the Google project number; mention the uploads use the <span className="mono">youtube.upload</span> scope only.</li>
          <li>Until it's approved, use privacy “Private” and publish from YouTube Studio, or keep Autopilot making clips for later.</li>
        </ol>
        <div className="field" style={{ marginTop: 12 }}>
          <label>Upload privacy</label>
          <div className="segmented">
            {[["public", "Public"], ["unlisted", "Unlisted"], ["private", "Private"]].map(([v, l]) => (
              <button key={v} className={"seg" + ((settings.ap_privacy || "public") === v ? " on" : "")} onClick={() => saveS({ ap_privacy: v })}>{l}</button>
            ))}
          </div>
          <p className="hint">Public: each clip is uploaded early and YouTube makes it public at its time slot. Unlisted/Private upload at the slot time without scheduling.</p>
        </div>
      </div>

      <div className="set-card">
        <div className="set-head"><CalendarClock size={18} /><div><h3>Posting schedule</h3><p className="muted tiny">Times are in this PC's time zone.</p></div></div>
        <div className="field">
          <label>Shorts per day <span className="muted">{perDay}</span></label>
          <input type="range" min="1" max="12" value={perDay} onChange={(e) => setPerDay(Number(e.target.value))} />
        </div>
        <div className="field">
          <label>Posting times</label>
          <div className="ap-times">
            {times.slice(0, perDay).map((t, i) => (
              <input key={i} type="time" className="input" value={t}
                onChange={(e) => { const n = [...times]; n[i] = e.target.value; setTimes(n); }}
                onBlur={() => saveS({ ap_times: [...times].sort() })} />
            ))}
          </div>
        </div>
        <div className="field two">
          <div><label>Keep ready (days)</label><input className="input" type="number" min="1" max="7" value={settings.ap_buffer_days || 2} onChange={(e) => saveS({ ap_buffer_days: Number(e.target.value) })} /></div>
          <div><label>Max clips per video</label><input className="input" type="number" min="1" max="30" value={settings.ap_clips_per_video || 6} onChange={(e) => saveS({ ap_clips_per_video: Number(e.target.value) })} /></div>
        </div>
        <label className="toggle" onClick={() => saveS({ ap_approval: !settings.ap_approval })}>
          <span className={"sw" + (settings.ap_approval ? " on" : "")}><span /></span> I approve every clip before it's uploaded
        </label>
      </div>

      <div className="set-card">
        <div className="set-head"><Wand2 size={18} /><div><h3>Editing</h3><p className="muted tiny">How Autopilot edits each clip.</p></div></div>
        <div className="field">
          <div className="segmented">
            <button className={"seg" + (settings.ap_engine !== "clipsworld" ? " on" : "")} onClick={() => saveS({ ap_engine: "hyperframes" })}><Sparkles size={13} /> Motion graphics</button>
            <button className={"seg" + (settings.ap_engine === "clipsworld" ? " on" : "")} onClick={() => saveS({ ap_engine: "clipsworld" })}><Film size={13} /> Fast editor</button>
          </div>
          <p className="hint">Motion graphics: Claude designs animated hook titles, meme pops, punch-in zooms and SFX for every clip, rendered with HyperFrames. If it ever fails, the fast editor takes over automatically.</p>
        </div>
        {settings.ap_engine !== "clipsworld" && (
          <>
            <DownloadRow dkey="hyperframes" title="Motion graphics pack (~250 MB)" hint="Node.js + HyperFrames + Chrome renderer" startLabel="Install" />
            <div className="field" style={{ marginTop: 12 }}>
              <label>Designer model</label>
              <div className="segmented">
                {[["claude-sonnet-5-5", "Sonnet 5.5 (best)"], ["claude-haiku-5-5", "Haiku 5.5 (cheaper)"]].map(([v, l]) => (
                  <button key={v} className={"seg" + ((settings.ap_hf_model || "claude-sonnet-5-5") === v ? " on" : "")} onClick={() => saveS({ ap_hf_model: v })}>{l}</button>
                ))}
              </div>
              <p className="hint">Sonnet costs roughly $0.05–0.10 per clip from your API credit.</p>
            </div>
          </>
        )}
      </div>

      <div className="set-card">
        <div className="set-head"><Upload size={18} /><div><h3>Run in the background</h3><p className="muted tiny">Autopilot works while Clipsworld is open.</p></div></div>
        <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
          With Autopilot on, closing the window keeps Clipsworld in the tray. Uploaded clips are scheduled on YouTube, so they go live on time even if your PC is off.
        </p>
        {desktop && desktop.setAutoStart && (
          <label className="toggle" onClick={async () => setAuto(await desktop.setAutoStart(!auto))}>
            <span className={"sw" + (auto ? " on" : "")}><span /></span> Start Clipsworld with Windows (in the tray)
          </label>
        )}
      </div>
    </div>
  );
}
