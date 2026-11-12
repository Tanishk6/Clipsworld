import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Clapperboard, FolderOpen, Home as HomeIcon, Settings as SettingsIcon, Sparkles } from "lucide-react";
import { api, desktop, url } from "./api.js";
import Home from "./pages/Home.jsx";
import Project from "./pages/Project.jsx";
import Exports from "./pages/Exports.jsx";
import Settings from "./pages/Settings.jsx";

const ToastCtx = createContext(() => {});
export const useToast = () => useContext(ToastCtx);
const AppCtx = createContext({});
export const useApp = () => useContext(AppCtx);

function injectFonts(fonts) {
  if (document.getElementById("cw-fonts")) return;
  const st = document.createElement("style");
  st.id = "cw-fonts";
  st.textContent = Object.entries(fonts || {})
    .map(([family, file]) => `@font-face { font-family: "${family}"; src: url("${url.font(file)}"); font-display: swap; }`)
    .join("\n");
  document.head.appendChild(st);
}

function Splash({ error }) {
  return (
    <div className="splash">
      <div className="splash-logo"><Logo size={64} /></div>
      <h1 className="brand-title">Clipsworld</h1>
      {!error ? (
        <>
          <p className="muted">Starting the AI engine…</p>
          <div className="splash-bar"><span /></div>
        </>
      ) : (
        <div className="splash-error">
          <p>The engine didn't start.</p>
          <pre>{error}</pre>
          {desktop && <button className="btn primary" onClick={() => desktop.restartBackend().then(() => location.reload())}>Try again</button>}
        </div>
      )}
    </div>
  );
}

export function Logo({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <defs>
        <linearGradient id="cwg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#7c5cff" />
          <stop offset="0.55" stopColor="#ff4fd8" />
          <stop offset="1" stopColor="#2de2ff" />
        </linearGradient>
      </defs>
      <rect x="4" y="4" width="56" height="56" rx="16" fill="url(#cwg)" />
      <circle cx="32" cy="32" r="15" fill="none" stroke="#0b0b14" strokeWidth="4.5" />
      <path d="M17 32h30M32 17c-6 6-6 24 0 30M32 17c6 6 6 24 0 30" stroke="#0b0b14" strokeWidth="3" fill="none" strokeLinecap="round" />
      <path d="M44 40l9 5-9 5z" fill="#0b0b14" />
    </svg>
  );
}

const NAV = [
  { id: "home", label: "Studio", icon: HomeIcon },
  { id: "exports", label: "My Clips", icon: Clapperboard },
  { id: "settings", label: "Settings", icon: SettingsIcon },
];

export default function App() {
  const [ready, setReady] = useState(false);
  const [bootError, setBootError] = useState(null);
  const [route, setRoute] = useState({ page: "home" });
  const [toasts, setToasts] = useState([]);
  const [settings, setSettings] = useState(null);
  const [styles, setStyles] = useState(null);

  const toast = useCallback((msg, kind = "info") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, msg, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 8000 : 4000);
  }, []);

  useEffect(() => {
    let tries = 0;
    let stop = false;
    const ping = async () => {
      try {
        await api.health();
        const [s, st] = await Promise.all([api.settings(), api.styles()]);
        injectFonts(st.fonts);
        setSettings(s);
        setStyles(st);
        setReady(true);
      } catch (e) {
        tries += 1;
        if (tries > 120) {
          const log = desktop ? await desktop.backendLog() : String(e);
          setBootError(log.slice(-1500) || String(e));
          return;
        }
        if (!stop) setTimeout(ping, 500);
      }
    };
    ping();
    desktop && desktop.onBackendExit && desktop.onBackendExit(() => toast("The engine stopped. Restart Clipsworld.", "error"));
    return () => { stop = true; };
  }, [toast]);

  const refreshSettings = useCallback(async () => setSettings(await api.settings()), []);

  if (!ready) return <Splash error={bootError} />;

  const go = (page, extra = {}) => setRoute({ page, ...extra });

  return (
    <AppCtx.Provider value={{ settings, styles, refreshSettings, go }}>
      <ToastCtx.Provider value={toast}>
        <div className="shell">
          <div className="titlebar">
            <div className="tb-brand"><Logo size={18} /><span>Clipsworld</span></div>
          </div>
          <aside className="sidebar">
            <div className="side-logo" onClick={() => go("home")}><Logo size={34} /></div>
            {NAV.map((n) => {
              const Icon = n.icon;
              const active = route.page === n.id || (n.id === "home" && route.page === "project");
              return (
                <button key={n.id} className={"nav-btn" + (active ? " active" : "")} onClick={() => go(n.id)} title={n.label}>
                  <Icon size={21} />
                  <span>{n.label}</span>
                </button>
              );
            })}
            <div className="side-spacer" />
            <div className={"ai-pill " + (settings.has_api_key ? "on" : "off")} title={settings.has_api_key ? "Claude AI connected" : "Add Claude API key in Settings"} onClick={() => go("settings")}>
              <Sparkles size={15} />
              <span>{settings.has_api_key ? "AI on" : "AI off"}</span>
            </div>
          </aside>
          <main className="main">
            {route.page === "home" && <Home onOpen={(id) => go("project", { id })} />}
            {route.page === "project" && <Project id={route.id} onBack={() => go("home")} />}
            {route.page === "exports" && <Exports />}
            {route.page === "settings" && <Settings />}
          </main>
        </div>
        <div className="toasts">
          {toasts.map((t) => (
            <div key={t.id} className={"toast " + t.kind}>{t.msg}</div>
          ))}
        </div>
      </ToastCtx.Provider>
    </AppCtx.Provider>
  );
}

export function openFolderButton(path) {
  return desktop ? (
    <button className="btn ghost sm" onClick={() => desktop.showItem(path)}><FolderOpen size={15} /> Show in folder</button>
  ) : null;
}
