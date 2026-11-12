"""Full feature test for the Clipsworld engine (runs locally and in the Windows CI build).

Usage: python tests/full_test.py <engine-url> <video-file> <output-dir> [ffprobe]
Exercises every API feature and checks the exported files with ffprobe.
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

B, VIDEO, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
FFPROBE = sys.argv[4] if len(sys.argv) > 4 else "ffprobe"
results = []


def call(method, path, body=None, raw=None, ok=(200,)):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(B + path, data=data, method=method,
                                 headers={"Content-Type": "application/octet-stream" if raw is not None else "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            code, text = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        code, text = e.code, e.read().decode()
    if code not in ok:
        raise AssertionError(f"{method} {path} -> {code}: {text[:300]}")
    return json.loads(text) if text else None


def wait(job, limit=1800):
    t = time.time()
    while time.time() - t < limit:
        j = call("GET", f"/jobs/{job['id']}")
        if j["status"] != "running":
            if j["status"] != "done":
                raise AssertionError(f"job {j['kind']} failed: {j['error']}")
            return j
        time.sleep(1)
    raise AssertionError("job timed out")


def probe(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                        "-of", "json", path], capture_output=True, text=True)
    return json.loads(r.stdout)


def check(name, fn):
    t = time.time()
    try:
        fn()
        results.append((name, True, f"{time.time() - t:.1f}s"))
        print(f"PASS  {name} ({time.time() - t:.1f}s)", flush=True)
    except Exception as e:  # noqa: BLE001
        results.append((name, False, str(e)))
        print(f"FAIL  {name}: {e}", flush=True)


S = {}


def t_basics():
    for p in ("/health", "/settings", "/styles", "/gpu", "/downloads", "/sfx", "/projects", "/exports", "/effects/defaults"):
        call("GET", p)
    st = call("GET", "/styles")
    assert len(st["styles"]) >= 12 and st["fonts"], "styles/fonts missing"
    assert len(call("GET", "/sfx")) >= 16, "sound effects missing"


def t_settings():
    s = call("PUT", "/settings", {"whisper_model": "tiny", "language": "mixed", "output_dir": OUT,
                                   "min_clip_sec": 5, "max_clip_sec": 15, "max_clips": 3, "caption_language": "hinglish"})
    assert s["whisper_model"] == "tiny" and not s["has_api_key"]
    r = call("POST", "/settings/test-key", {"claude_api_key": "sk-bad"})
    assert r["ok"] is False


def t_project():
    r = call("POST", "/projects", {"source": VIDEO})
    S["pid"] = r["project"]["id"]
    wait(r["job"])
    p = call("GET", f"/projects/{S['pid']}")
    assert p["status"] == "ready", p.get("error")
    assert p["transcript"] is not None
    call("POST", f"/projects/{S['pid']}/analyze", {"from": "clips"})  # second one must be refused while running
    call("POST", f"/projects/{S['pid']}/analyze", {"from": "clips"}, ok=(409,))
    time.sleep(1)
    for _ in range(300):
        if not any(j["status"] == "running" and j["project_id"] == S["pid"] for j in call("GET", "/jobs")):
            break
        time.sleep(1)
    w = call("GET", f"/projects/{S['pid']}/waveform")
    assert w["values"], "no waveform"


def t_clips():
    c = call("POST", f"/projects/{S['pid']}/clips", {"start": 2, "end": 12})
    S["cid"] = c["id"]
    assert c["captions"]["language"] == "original"  # no Claude key: stays as spoken
    for style in ("hormozi", "beast", "pop", "pixel", "karaoke", "clean"):
        c = call("PUT", f"/projects/{S['pid']}/clips/{S['cid']}", {"captions": {"style": style}})
        assert c["captions"]["style"] == style
    c = call("PUT", f"/projects/{S['pid']}/clips/{S['cid']}", {"start": 1.5, "end": 11})
    assert abs(c["start"] - 1.5) < 0.01
    call("POST", f"/projects/{S['pid']}/clips/{S['cid']}/captions/rebuild")
    j = call("POST", f"/projects/{S['pid']}/clips/{S['cid']}/translate", {"target": "hinglish"})
    jj = call("GET", f"/jobs/{j['id']}")
    for _ in range(30):
        if jj["status"] != "running":
            break
        time.sleep(0.5)
        jj = call("GET", f"/jobs/{j['id']}")
    assert jj["status"] == "error" and "API key" in jj["error"], "translate without key should explain"
    call("POST", f"/projects/{S['pid']}/clips/zzzzzz/auto-edit", ok=(404,))


def t_effects():
    j = wait(call("POST", f"/projects/{S['pid']}/clips/{S['cid']}/auto-edit"))
    assert isinstance(j["result"]["clip"]["effects"], list)
    effects = [{"type": "zoom", "t": 1, "scale": 1.3, "dur": 0.8, "sfx": "whoosh", "volume": 0.5},
               {"type": "shake", "t": 2, "dur": 0.5, "sfx": "boom"},
               {"type": "freeze", "t": 3, "dur": 1, "text": "WAIT WHAT"},
               {"type": "replay", "t": 6, "dur": 2, "speed": 0.6},
               {"type": "text", "t": 7, "text": "BHAI KYA", "position": "top", "color": "#ff0000"},
               {"type": "sfx", "t": 8, "sfx": "airhorn", "volume": 1.2},
               {"type": "bogus", "t": 1}, {"type": "zoom", "t": 999}]
    c = call("PUT", f"/projects/{S['pid']}/clips/{S['cid']}", {"effects": effects, "audio": {"sfx_volume": 0.7},
                                                               "hook": "Test hook", "captions": {"show_hook": True}})
    assert len(c["effects"]) == 6, "invalid effects must be dropped"


def t_voice():
    import pathlib
    vo = pathlib.Path(OUT) / "vo_test.webm"
    if not vo.exists():
        return
    c = call("POST", f"/projects/{S['pid']}/clips/{S['cid']}/voiceover?ext=webm&video=1", raw=vo.read_bytes())
    assert c["audio"]["vo_file"] and c["audio"]["vo_has_video"]
    call("PUT", f"/projects/{S['pid']}/clips/{S['cid']}", {"audio": {"bubble": {"pos": "bottom-left", "size": 0.3}}})


def t_layouts_and_exports():
    p = call("GET", f"/projects/{S['pid']}")
    info = p["info"]
    combos = [("short", {"mode": "blur"}), ("short", {"mode": "crop", "box": {"x": 0.1, "y": 0.1, "w": 0.3}}),
              ("short", {"mode": "split", "cam": {"x": 0, "y": 0, "w": 0.3, "h": 0.3}}), ("square", {"mode": "fit"}),
              ("landscape", {"mode": "blur"})]
    want = {"short": (1080, 1920), "square": (1080, 1080), "landscape": (1920, 1080)}
    for fmt, lay in combos:
        call("PUT", f"/projects/{S['pid']}/clips/{S['cid']}", {"layout": dict(lay, format=fmt)})
        j = wait(call("POST", f"/projects/{S['pid']}/export", {"clip_ids": [S["cid"]]}))
        f = j["result"]["files"][0]
        pr = probe(f["path"])
        v = next(s for s in pr["streams"] if s["codec_type"] == "video")
        assert (v["width"], v["height"]) == want[fmt], f"{fmt}/{lay['mode']}: got {v['width']}x{v['height']}"
        assert any(s["codec_type"] == "audio" for s in pr["streams"]), "no audio"
        # 9.5s clip + 1s freeze + 2/0.6s replay
        assert abs(float(pr["format"]["duration"]) - (9.5 + 1 + 2 / 0.6)) < 0.6, f"duration {pr['format']['duration']}"
        print(f"      {fmt}/{lay['mode']}: {v['width']}x{v['height']} {float(pr['format']['duration']):.2f}s", flush=True)
    _ = info


def t_preview_meta_orig():
    j = wait(call("POST", f"/projects/{S['pid']}/clips/{S['cid']}/preview"))
    assert j["result"]["path"].endswith(".mp4")
    j = wait(call("POST", f"/projects/{S['pid']}/clips/{S['cid']}/metadata", {}))
    assert "#shorts" in j["result"]["clip"]["meta"]["hashtags"]
    o = call("GET", f"/projects/{S['pid']}/clips/{S['cid']}/originality")
    assert 0 <= o["score"] <= 100 and o["checks"]
    call("PUT", f"/projects/{S['pid']}", {"credit": "@Tester"})
    assert len(call("GET", "/exports")) >= 1


def t_cleanup():
    call("DELETE", f"/projects/{S['pid']}/clips/{S['cid']}/voiceover")
    call("DELETE", f"/projects/{S['pid']}/clips/{S['cid']}")
    call("POST", f"/projects/{S['pid']}/clips/{S['cid']}/preview", ok=(404,))


for name, fn in [("engine basics", t_basics), ("settings", t_settings), ("import + transcribe + find clips", t_project),
                 ("clip editing + captions", t_clips), ("effects + auto edit", t_effects), ("voice / facecam", t_voice),
                 ("all layouts + formats export", t_layouts_and_exports), ("preview, upload details, originality", t_preview_meta_orig),
                 ("cleanup", t_cleanup)]:
    check(name, fn)
    if name.startswith("import") and not results[-1][1]:
        break

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
