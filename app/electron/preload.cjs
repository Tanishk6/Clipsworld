const { contextBridge, ipcRenderer, webUtils } = require("electron");

const portArg = process.argv.find((a) => a.startsWith("--cw-port="));

contextBridge.exposeInMainWorld("clipsworld", {
  port: portArg ? Number(portArg.split("=")[1]) : 0,
  isDesktop: true,
  pickVideo: () => ipcRenderer.invoke("pick-video"),
  pickFolder: () => ipcRenderer.invoke("pick-folder"),
  openPath: (p) => ipcRenderer.invoke("open-path", p),
  showItem: (p) => ipcRenderer.invoke("show-item", p),
  openExternal: (u) => ipcRenderer.invoke("open-external", u),
  backendLog: () => ipcRenderer.invoke("backend-log"),
  appInfo: () => ipcRenderer.invoke("app-info"),
  checkUpdate: () => ipcRenderer.invoke("check-update"),
  restartBackend: () => ipcRenderer.invoke("restart-backend"),
  pathForFile: (file) => {
    try { return webUtils.getPathForFile(file); } catch (_) { return file && file.path; }
  },
  onBackendExit: (cb) => ipcRenderer.on("backend-exit", (_e, code) => cb(code)),
});
