"""Autopilot + YouTube end-to-end test against a fake Google/YouTube server.

Usage: python tests/autopilot_test.py <video-file> <ffprobe> <engine command...>
The engine runs with CLIPSWORLD_DATA from the environment (reuse a data dir that already has a speech model).
Flow: connect YouTube (OAuth + PKCE) → add a video link → Autopilot analyses + produces clips → review →
approve → scheduled uploads (resumable, with a simulated server error) → checks what YouTube received.
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fake_youtube  # noqa: E402

VIDEO, FFPROBE, ENGINE = Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3:]
results = []


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def check(name, fn):
    t = time.time()
    try:
        fn()
        results.append((name, True))
        print(f"PASS  {name} ({time.time() - t:.1f}s)", flush=True)
    except Exception as e:  # noqa: BLE001
        results.append((name, False))
        print(f"FAIL  {name}: {e}", flush=True)


# fake Google + a file server for the "video link"
yt_port, file_port, eng_port = free_port(), free_port(), free_port()
yt = ThreadingHTTPServer(("127.0.0.1", yt_port), fake_youtube.H)
threading.Thread(target=yt.serve_forever, daemon=True).start()
fs = ThreadingHTTPServer(("127.0.0.1", file_port), partial(SimpleHTTPRequestHandler, directory=str(VIDEO.parent)))
fs.RequestHandlerClass.log_message = lambda *a: None
threading.Thread(target=fs.serve_forever, daemon=True).start()
YT = f"http://127.0.0.1:{yt_port}"
HF = os.environ.get("AP_TEST_HF") == "1"  # also install the HyperFrames pack and require motion-graphics renders
env = dict(os.environ, CLIPSWORLD_YT_AUTH=YT + "/auth", CLIPSWORLD_YT_TOKEN=YT + "/token", CLIPSWORLD_YT_API=YT,
           CLIPSWORLD_YT_CHUNK=str(256 * 1024))
if HF:
    env["CLIPSWORLD_HF_TEST_DESIGN"] = str(Path(__file__).parent / "hf_test_design.json")
eng = subprocess.Popen([*ENGINE, "--port", str(eng_port)], env=env)
B = f"http://127.0.0.1:{eng_port}"


def call(method, path, body=None, ok=(200,), base=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request((base or B) + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            code, text = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        code, text = e.code, e.read().decode()
    if code not in ok:
        raise AssertionError(f"{method} {path} -> {code}: {text[:300]}")
    try:
        return json.loads(text)
    except ValueError:
        return text


def probe(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                        "-of", "json", path], capture_output=True, text=True)
    return json.loads(r.stdout)


def drive(until, limit=1500, label=""):
    """Press "Run now" until a condition holds (the background loop is off in tests)."""
    t = time.time()
    last = ""
    while time.time() - t < limit:
        st = call("GET", "/autopilot")
        if until(st):
            return st
        if not st["worker"]["busy"]:
            call("POST", "/autopilot/run")
        msg = f"{st['worker']['kind']} {round(st['worker']['progress'] * 100)}% {st['worker']['stage']}"
        if msg != last:
            print("   ", label, msg, st["counts"], flush=True)
            last = msg
        time.sleep(2)
    raise AssertionError(f"timed out waiting for {label}: {json.dumps(call('GET', '/autopilot'))[:800]}")


try:
    for _ in range(90):
        try:
            if call("GET", "/health")["ok"]:
                break
        except Exception:  # noqa: BLE001
            time.sleep(1)
    print("engine up", call("GET", "/health")["version"])
    S = {}

    def t_settings():
        s = call("PUT", "/settings", {"ap_enabled": False, "ap_per_day": 2, "ap_times": ["09:00", "18:30", "bad"],
                                      "ap_buffer_days": 1, "ap_clips_per_video": 2, "ap_approval": True})
        assert s["ap_per_day"] == 2 and s["ap_times"][1] == "18:30", s
        st = call("GET", "/autopilot")
        assert st["slots"] == ["09:00", "18:30"], st["slots"]
        assert len(st["next_slots"]) == 5 and st["next_slots"] == sorted(st["next_slots"])
    check("autopilot settings + slots", t_settings)

    def t_hf_pack():
        call("PUT", "/settings", {"ap_engine": "hyperframes" if HF else "clipsworld"})
        if not HF:
            return
        call("POST", "/downloads/hyperframes/start")
        t = time.time()
        last = ""
        while time.time() - t < 900:
            d = next(x for x in call("GET", "/downloads") if x["key"] == "hyperframes")
            msg = f"{d['state']} {round(d['progress'] * 100)}% {d['stage']}"
            if msg != last:
                print("   ", msg, flush=True)
                last = msg
            if d["state"] == "done":
                return
            if d["state"] == "error":
                raise AssertionError(d["error"])
            time.sleep(3)
        raise AssertionError("pack install timed out")
    check("motion graphics pack installs" if HF else "editor: fast", t_hf_pack)

    def t_connect():
        assert call("GET", "/youtube/status")["connected"] is False
        call("POST", "/youtube/connect", ok=(400,))  # no client yet
        call("PUT", "/youtube/client", {"client_id": "", "client_secret": ""}, ok=(400,))
        call("PUT", "/youtube/client", {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": "GOCSPX-x"})
        url = call("POST", "/youtube/connect")["url"]
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        assert q["code_challenge_method"] == "S256" and q["access_type"] == "offline"
        assert q["redirect_uri"] == f"{B}/youtube/callback", q["redirect_uri"]
        assert "youtube.upload" in q["scope"]
        bad = call("GET", f"/youtube/callback?code=wrong&state={q['state']}")
        assert "close this tab" in bad and "✕" in bad
        bad2 = call("GET", "/youtube/callback?code=good-code&state=forged")
        assert "expired" in bad2
        good = call("GET", f"/youtube/callback?code=good-code&state={q['state']}")
        assert "Connected to Carry Clips" in good, re.sub(r"<[^>]+>", " ", good)[-300:]
        st = call("GET", "/youtube/status")
        assert st["connected"] and st["channel"]["title"] == "Carry Clips", st
        assert "GOCSPX" not in json.dumps(st)
    check("YouTube sign-in (PKCE, state check, channel)", t_connect)

    def t_sources():
        url = f"http://127.0.0.1:{file_port}/{urllib.parse.quote(VIDEO.name)}"
        r = call("POST", "/autopilot/sources", {"urls": [url, url, "not a link"]})
        assert r["added"] == 1, r
        assert call("POST", "/autopilot/sources", {"urls": url})["added"] == 0
        st = drive(lambda s: s["sources"][0]["status"] not in ("queued", "analysing"), label="analyse")
        src = st["sources"][0]
        assert src["status"] in ("ready", "empty"), src
        S["pid"] = src["project_id"]
        if src["status"] == "empty":  # no speech in the CI video: add clips by hand like a user would
            call("POST", f"/projects/{S['pid']}/clips", {"start": 1, "end": 8})
            call("POST", f"/projects/{S['pid']}/clips", {"start": 9, "end": 16})
    check("video link → analysed by Autopilot", t_sources)

    def t_produce():
        st = drive(lambda s: s["counts"].get("review", 0) >= 2, label="produce")
        items = [i for i in st["items"] if i["status"] == "review"]
        for it in items:
            assert Path(it["video_path"]).exists(), it
            pr = probe(it["video_path"])
            v = [x for x in pr["streams"] if x["codec_type"] == "video"][0]
            assert (v["width"], v["height"]) == (1080, 1920), v
            assert any(x["codec_type"] == "audio" for x in pr["streams"]), "no audio"
            assert it["engine"] in ("hyperframes", "clipsworld") and it["title"], it
            if HF:
                assert it["engine"] == "hyperframes", f"HyperFrames fell back: {it.get('engine_note')}"
        assert items[0]["style"] != items[1]["style"], "caption styles should rotate"
        assert call("GET", "/autopilot")["counts"].get("review") == 2  # buffer = 2/day x 1 day: stops making more
        S["items"] = [i["id"] for i in items]
        print("    engines:", [i["engine"] for i in items], "notes:", [i.get("engine_note") for i in items])
    check("Autopilot makes clips into Review (and stops at the buffer)", t_produce)

    def t_review():
        a, b = S["items"]
        call("PUT", f"/autopilot/items/{a}", {"title": "Bhai ye kya hua 😂", "tags": "funny, minecraft #gaming"})
        call("POST", "/autopilot/items/nope/approve", ok=(404,))
        it = call("POST", f"/autopilot/items/{a}/approve", {})
        assert it["title"] == "Bhai ye kya hua 😂" and it["tags"] == ["funny", "minecraft", "#gaming"], it
        assert it["publish_at"] and re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:00Z$", it["publish_at"])
        call("POST", f"/autopilot/items/{a}/approve", ok=(409,))
        it2 = call("POST", f"/autopilot/items/{b}/approve")
        assert it2["publish_at"] > it["publish_at"], (it["publish_at"], it2["publish_at"])
        for x in (it, it2):
            local = datetime.strptime(x["publish_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone()
            assert local.strftime("%H:%M") in ("09:00", "18:30"), local
            assert local > datetime.now().astimezone()
        S["slots"] = {a: it["publish_at"], b: it2["publish_at"]}
    check("review: edit + approve → next free time slots", t_review)

    def t_upload():
        st = drive(lambda s: all(i["status"] in ("scheduled", "failed") for i in s["items"] if i["id"] in S["items"]),
                   label="upload", limit=300)
        vids = call("GET", "/_videos", base=YT)["videos"]
        for iid in S["items"]:
            it = next(i for i in st["items"] if i["id"] == iid)
            assert it["status"] == "scheduled" and it["video_id"] in vids, it
            v = vids[it["video_id"]]
            assert v["status"]["publishAt"] == S["slots"][iid] and v["status"]["privacyStatus"] == "private", v
            assert v["bytes"] == Path(it["video_path"]).stat().st_size
            assert "#shorts" in v["snippet"]["title"].lower()
            assert v["snippet"]["defaultAudioLanguage"] == "hi"
        assert any(v["snippet"]["title"].startswith("Bhai ye kya hua") for v in vids.values())
        assert call("POST", f"/autopilot/items/{S['items'][0]}/reject", ok=(409,))
    check("scheduled uploads reach YouTube (resumable, survives a 503)", t_upload)

    def t_refill_and_cleanup():
        st = call("GET", "/autopilot")
        assert any("Uploaded" in x["msg"] for x in st["log"])
        call("POST", "/youtube/disconnect")
        assert call("GET", "/youtube/status")["connected"] is False
        assert call("GET", "/youtube/status")["has_client"] is True
    check("log + disconnect", t_refill_and_cleanup)
finally:
    eng.terminate()
    try:
        eng.wait(10)
    except Exception:  # noqa: BLE001
        eng.kill()

bad = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} autopilot checks passed")
sys.exit(1 if bad else 0)
