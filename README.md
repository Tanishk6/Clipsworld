# Clipsworld

AI clipping studio for Windows. Drop in a long video or stream and Clipsworld:

- **Listens** to it with Whisper (runs free on your PC; Hindi + English mixed mode)
- **Finds** the funniest / most hype moments (Claude AI, or a free offline finder)
- **Captions** them word-by-word in 12 trending styles (Hormozi, Beast, Bebas, Comic, Pixel Gamer…)
- **Translates** captions to Hindi, Hinglish or English (Claude)
- **Edits** like a Shorts editor: zoom punch-ins, camera shake, freeze frames with text, slow-mo replays,
  meme text pops and 16 built-in sound effects — or one-click **Auto edit**
- **Your reaction**: record a voiceover or facecam bubble right in the app (auto-ducks the clip audio)
- **Facecam layout** for stream clips (streamer's webcam on top, gameplay below)
- **Originality check** based on YouTube's reused/inauthentic content rules, with tips
- **Upload details**: title, description (with credit) and hashtags saved as a .txt next to each video
- **Exports** ready-to-upload 9:16 Shorts, 1:1 or 16:9 videos

## Install

1. Open the **Releases** page on GitHub and download `Clipsworld-Setup-x.y.z.exe`.
2. Run it. Windows SmartScreen may warn because the app isn't code-signed: click **More info → Run anyway**.
3. First launch: go to **Settings**
   - Paste your **Claude API key** (Claude Console). Max/Ultra plans include monthly API credits.
   - If you have an NVIDIA GPU, click **Download GPU pack** for much faster transcription.

The first video downloads the Whisper speech model once (~1.6 GB for the best quality).

## How it's built

| Part | Tech |
|---|---|
| Desktop app + UI | Electron + React (Vite) |
| Engine | Python (FastAPI) packaged with PyInstaller |
| Speech to text | faster-whisper (CPU or NVIDIA CUDA) |
| AI clip picking + translation | Claude API (Haiku 5.5 by default) |
| Video | FFmpeg + libass captions, x264 / NVENC |
| Video links | yt-dlp (use only for your own videos or with permission) |

## Develop

```bash
# engine
cd backend && pip install -r requirements.txt && python server.py --port 8765
# UI (browser preview)
cd app && npm install && npm run dev   # open http://localhost:5173/?port=8765
# desktop shell
cd app && npm start
```

Every push to `main` builds the Windows installer in GitHub Actions and publishes it on the
**Releases** page.

Fonts in `resources/fonts` are free (SIL OFL / Apache 2.0); see `FONT-LICENSES.txt`.
Sound effects in `resources/sfx` are original, synthesized by `tools/make_sfx.py` (free to use).
