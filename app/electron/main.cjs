// Clipsworld desktop shell: starts the local AI/video engine and opens the UI window.
const { app, BrowserWindow, dialog, ipcMain, net: enet, session, shell } = require("electron");
const { spawn, execFile } = require("child_process");
const net = require("net");
const path = require("path");
const fs = require("fs");
const http = require("http");

let win = null;
let backend = null;
let backendPort = 0;
let backendLog = [];

if (!app.requestSingleInstanceLock()) {
  app.quit();
}

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

function logLine(s) {
  backendLog.push(s);
  if (backendLog.length > 200) backendLog.shift();
}

async function startBackend() {
  backendPort = await freePort();
  let cmd, args, cwd;
  const env = { ...process.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" };
  if (app.isPackaged) {
    const dir = path.join(process.resourcesPath, "backend");
    cmd = path.join(dir, process.platform === "win32" ? "clipsworld-backend.exe" : "clipsworld-backend");
    args = ["--port", String(backendPort)];
    cwd = dir;
    env.CLIPSWORLD_RESOURCES = process.resourcesPath;
  } else {
    const root = path.resolve(__dirname, "..", "..");
    cmd = process.platform === "win32" ? "python" : "python3";
    args = [path.join(root, "backend", "server.py"), "--port", String(backendPort)];
    cwd = path.join(root, "backend");
    env.CLIPSWORLD_RESOURCES = path.join(root, "resources");
  }
  logLine(`[starting engine] ${cmd}\n`);
  if (!fs.existsSync(cmd) && app.isPackaged) logLine(`[error] engine file is missing: ${cmd}\n`);
  backend = spawn(cmd, args, { cwd, env, windowsHide: true });
  backend.on("error", (e) => logLine(`[error] could not start engine: ${e.message}\n`));
  backend.stdout.on("data", (d) => logLine(d.toString()));
  backend.stderr.on("data", (d) => logLine(d.toString()));
  backend.on("exit", (code) => {
    logLine(`[engine exited with code ${code}]`);
    backend = null;
    if (win && !win.isDestroyed()) win.webContents.send("backend-exit", code);
  });
}

function stopBackend() {
  if (!backend) return;
  const pid = backend.pid;
  if (process.platform === "win32") {
    execFile("taskkill", ["/pid", String(pid), "/T", "/F"], () => {});
  } else {
    try { backend.kill("SIGTERM"); } catch (_) { /* already gone */ }
  }
  backend = null;
}

function createWindow() {
  win = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1120,
    minHeight: 720,
    backgroundColor: "#07070d",
    title: "Clipsworld",
    titleBarStyle: "hidden",
    titleBarOverlay: { color: "#07070d", symbolColor: "#c9c4ff", height: 38 },
    icon: path.join(__dirname, "..", "build", "icon.png"),
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      additionalArguments: [`--cw-port=${backendPort}`],
    },
  });
  win.once("ready-to-show", () => win.show());
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  if (app.isPackaged) {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"), { query: { port: String(backendPort) } });
  } else {
    win.loadURL(`http://localhost:5173/?port=${backendPort}`);
  }
}

ipcMain.handle("pick-video", async () => {
  const r = await dialog.showOpenDialog(win, {
    title: "Choose a video or stream recording",
    properties: ["openFile"],
    filters: [
      { name: "Videos", extensions: ["mp4", "mkv", "mov", "webm", "avi", "flv", "ts", "m4v", "wmv"] },
      { name: "All files", extensions: ["*"] },
    ],
  });
  return r.canceled ? null : r.filePaths[0];
});

ipcMain.handle("pick-folder", async () => {
  const r = await dialog.showOpenDialog(win, { title: "Choose export folder", properties: ["openDirectory", "createDirectory"] });
  return r.canceled ? null : r.filePaths[0];
});

ipcMain.handle("open-path", (_e, p) => shell.openPath(p));
ipcMain.handle("show-item", (_e, p) => { shell.showItemInFolder(p); return true; });
ipcMain.handle("open-external", (_e, url) => { if (/^https?:\/\//.test(url)) shell.openExternal(url); return true; });
ipcMain.handle("backend-log", () => backendLog.join(""));

function buildInfo() {
  try { return JSON.parse(fs.readFileSync(path.join(__dirname, "..", "build-info.json"), "utf8")); } catch (_) { return { build: 0 }; }
}
ipcMain.handle("app-info", () => ({ version: app.getVersion(), build: buildInfo().build || 0 }));
ipcMain.handle("check-update", async () => {
  try {
    const r = await enet.fetch("https://api.github.com/repos/Tanishk6/clipsworld/releases/latest",
      { headers: { "User-Agent": "Clipsworld", Accept: "application/vnd.github+json" } });
    if (!r.ok) return null;
    const j = await r.json();
    const m = /build-(\d+)/.exec(j.tag_name || "");
    const latest = m ? Number(m[1]) : 0;
    const mine = buildInfo().build || 0;
    if (!latest || !mine || latest <= mine) return null;
    const exe = (j.assets || []).find((a) => /\.exe$/i.test(a.name));
    return { latest, mine, url: exe ? exe.browser_download_url : j.html_url, page: j.html_url, name: j.name };
  } catch (_) { return null; }
});
ipcMain.handle("restart-backend", async () => {
  stopBackend();
  await startBackend();
  return backendPort;
});

app.on("second-instance", () => {
  if (win) {
    if (win.isMinimized()) win.restore();
    win.focus();
  }
});

app.whenReady().then(async () => {
  // camera + microphone for reaction recording, clipboard for copy buttons
  const allowed = new Set(["media", "clipboard-sanitized-write", "clipboard-read", "fullscreen"]);
  session.defaultSession.setPermissionRequestHandler((_wc, perm, cb) => cb(allowed.has(perm)));
  session.defaultSession.setPermissionCheckHandler((_wc, perm) => allowed.has(perm));
  await startBackend();
  createWindow();
});

app.on("window-all-closed", () => {
  stopBackend();
  app.quit();
});
app.on("before-quit", stopBackend);
