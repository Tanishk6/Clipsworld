import React, { useEffect, useState } from "react";
import { Check, Cpu, ExternalLink, FolderOpen, KeyRound, Loader2, Save, Sparkles, Zap, Mic, Scissors, Settings as Cog } from "lucide-react";
import { api, desktop, waitForJob } from "../api.js";
import { useApp, useToast } from "../App.jsx";

const WHISPER = [
  { id: "large-v3-turbo", label: "Best — large-v3-turbo (1.6 GB, recommended with GPU)" },
  { id: "medium", label: "Great — medium (1.5 GB)" },
  { id: "small", label: "Good — small (480 MB, fast on CPU)" },
  { id: "base", label: "Basic — base (145 MB)" },
  { id: "tiny", label: "Fastest — tiny (75 MB, low accuracy)" },
];
const MODELS = [
  { id: "claude-haiku-5-5", label: "Claude Haiku 5.5 — fast & cheapest (recommended)" },
  { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5 — smarter picks, costs more" },
];

function Card({ icon: Icon, title, children, sub }) {
  return (
    <div className="set-card">
      <div className="set-head"><Icon size={18} /><div><h3>{title}</h3>{sub && <p className="muted tiny">{sub}</p>}</div></div>
      {children}
    </div>
  );
}

export default function Settings() {
  const toast = useToast();
  const { settings, refreshSettings } = useApp();
  const [s, setS] = useState(settings);
  const [key, setKey] = useState("");
  const [testing, setTesting] = useState(false);
  const [gpu, setGpu] = useState(null);
  const [gpuJob, setGpuJob] = useState(null);

  useEffect(() => { setS(settings); }, [settings]);
  useEffect(() => { api.gpu().then(setGpu).catch(() => {}); }, []);

  const set = (k, v) => setS((x) => ({ ...x, [k]: v }));

  const save = async (extra = {}) => {
    try {
      const body = { ...s, ...extra };
      delete body.has_api_key; delete body.api_key_hint;
      await api.saveSettings(body);
      await refreshSettings();
      toast("Settings saved", "ok");
    } catch (e) { toast(e.message, "error"); }
  };

  const saveKey = async () => {
    if (!key.trim()) return;
    setTesting(true);
    try {
      const r = await api.testKey({ claude_api_key: key.trim(), claude_model: s.claude_model });
      if (!r.ok) throw new Error(r.error);
      await api.saveSettings({ claude_api_key: key.trim() });
      await refreshSettings();
      setKey("");
      toast("Claude connected! AI features are on ✨", "ok");
    } catch (e) {
      toast(e.message, "error");
    } finally { setTesting(false); }
  };

  const removeKey = async () => {
    await api.saveSettings({ claude_api_key: "" });
    await refreshSettings();
    toast("API key removed");
  };

  const testSaved = async () => {
    setTesting(true);
    try {
      const r = await api.testKey({ claude_model: s.claude_model });
      r.ok ? toast(`Working ✓ (${r.model})`, "ok") : toast(r.error, "error");
    } finally { setTesting(false); }
  };

  const installGpu = async () => {
    setGpuJob({ progress: 0, stage: "Starting download…" });
    try {
      const j = await api.installGpu();
      await waitForJob(j.id, (x) => setGpuJob({ progress: x.progress, stage: x.stage }), 1000);
      toast("GPU pack installed. Transcription will use your NVIDIA GPU.", "ok");
      setGpu(await api.gpu());
    } catch (e) { toast(e.message, "error"); }
    finally { setGpuJob(null); }
  };

  const pickFolder = async () => {
    if (!desktop) return;
    const f = await desktop.pickFolder();
    if (f) set("output_dir", f);
  };

  if (!s) return null;

  return (
    <div className="page settings">
      <h1 className="page-title"><Cog size={26} /> Settings</h1>
      <div className="set-grid">
        <Card icon={Sparkles} title="Claude AI" sub="Picks the best clips, translates captions. Uses your API key from the Claude Console — Ultra and Max plans include monthly API credits.">
          {settings.has_api_key ? (
            <div className="key-on">
              <div className="key-pill"><Check size={15} /> Connected <span className="mono muted">{settings.api_key_hint}</span></div>
              <div className="row gap">
                <button className="btn sm" onClick={testSaved} disabled={testing}>{testing ? <Loader2 size={14} className="spin" /> : <Zap size={14} />} Test</button>
                <button className="btn ghost sm" onClick={removeKey}>Remove</button>
              </div>
            </div>
          ) : (
            <div className="key-row">
              <KeyRound size={16} />
              <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder="sk-ant-…" />
              <button className="btn primary" onClick={saveKey} disabled={testing || !key.trim()}>{testing ? <Loader2 size={15} className="spin" /> : <Check size={15} />} Connect</button>
            </div>
          )}
          <div className="field">
            <label>Model</label>
            <select value={s.claude_model} onChange={(e) => set("claude_model", e.target.value)}>
              {MODELS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
              {!MODELS.find((m) => m.id === s.claude_model) && <option value={s.claude_model}>{s.claude_model}</option>}
            </select>
          </div>
          {desktop && (
            <button className="link-btn" onClick={() => desktop.openExternal("https://platform.claude.com/")}>
              Open Claude Console to create a key <ExternalLink size={13} />
            </button>
          )}
          <p className="hint">Your key is saved only on this PC.</p>
        </Card>

        <Card icon={Mic} title="Speech to text" sub="Runs on your PC for free with Whisper.">
          <div className="field">
            <label>Language in your videos</label>
            <select value={s.language} onChange={(e) => set("language", e.target.value)}>
              <option value="mixed">Hindi + English mixed (recommended)</option>
              <option value="hi">Hindi / Hinglish only</option>
              <option value="en">English only</option>
              <option value="auto">Auto detect (one language)</option>
            </select>
          </div>
          <div className="field">
            <label>Accuracy</label>
            <select value={s.whisper_model} onChange={(e) => set("whisper_model", e.target.value)}>
              {WHISPER.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Run on</label>
            <select value={s.device} onChange={(e) => set("device", e.target.value)}>
              <option value="auto">Auto (GPU if ready, else CPU)</option>
              <option value="cuda">NVIDIA GPU</option>
              <option value="cpu">CPU only</option>
            </select>
          </div>
        </Card>

        <Card icon={Cpu} title="NVIDIA GPU boost" sub="Makes transcription 5–10× faster on cards like the GTX 1650.">
          {gpu ? (
            <>
              <div className="gpu-stats">
                <div><span className="muted tiny">NVIDIA GPUs found</span><b>{gpu.nvidia_gpus}</b></div>
                <div><span className="muted tiny">GPU pack</span><b>{gpu.pack_installed ? "Installed ✓" : "Not installed"}</b></div>
              </div>
              {gpu.platform_supported && gpu.nvidia_gpus > 0 && !gpu.pack_installed && (
                gpuJob ? (
                  <>
                    <div className="pbar"><span style={{ width: `${gpuJob.progress * 100}%` }} /></div>
                    <p className="hint">{gpuJob.stage}</p>
                  </>
                ) : (
                  <button className="btn primary" onClick={installGpu}><Zap size={15} /> Download GPU pack (~1 GB, one time)</button>
                )
              )}
              {gpu.nvidia_gpus === 0 && <p className="hint">No NVIDIA GPU detected — Clipsworld will use the CPU. Update your NVIDIA driver if you have one.</p>}
            </>
          ) : <Loader2 size={18} className="spin" />}
        </Card>

        <Card icon={Scissors} title="Clip finder" sub="How the AI cuts your videos.">
          <div className="field two">
            <div><label>Shortest clip (sec)</label><input className="input" type="number" min="5" max="170" value={s.min_clip_sec} onChange={(e) => set("min_clip_sec", Number(e.target.value))} /></div>
            <div><label>Longest clip (sec)</label><input className="input" type="number" min="10" max="180" value={s.max_clip_sec} onChange={(e) => set("max_clip_sec", Number(e.target.value))} /></div>
          </div>
          <div className="field">
            <label>Clips per video <span className="muted">{s.max_clips}</span></label>
            <input type="range" min="3" max="40" value={s.max_clips} onChange={(e) => set("max_clips", Number(e.target.value))} />
          </div>
        </Card>

        <Card icon={FolderOpen} title="Export" sub="Where finished clips are saved.">
          <div className="field">
            <label>Export folder</label>
            <div className="key-row">
              <input value={s.output_dir} onChange={(e) => set("output_dir", e.target.value)} />
              {desktop && <button className="btn" onClick={pickFolder}><FolderOpen size={15} /> Browse</button>}
            </div>
          </div>
          <div className="field">
            <label>Video encoder</label>
            <select value={s.encoder} onChange={(e) => set("encoder", e.target.value)}>
              <option value="auto">Auto (NVIDIA NVENC if available)</option>
              <option value="nvenc">NVIDIA NVENC (fast)</option>
              <option value="x264">CPU x264 (best compatibility)</option>
            </select>
          </div>
        </Card>
      </div>
      <div className="save-bar">
        <button className="btn primary lg" onClick={() => save()}><Save size={17} /> Save settings</button>
      </div>
    </div>
  );
}
