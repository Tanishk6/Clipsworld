"""A tiny stand-in for Google's OAuth + YouTube Data API, for offline tests.

Run: python fake_youtube.py PORT   (set FAKE_YT_LOCKED=1 to act like an unaudited project)
Behaviour: resumable uploads with 308 resume, one simulated 503 per upload, scheduled publishAt.
"""
import json
import os
import sys
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VIDEOS = {}
THUMBS = {}
SESSIONS = {}
CODES = {"good-code"}
LOG = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj, headers=None):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _authed(self):
        if self.headers.get("Authorization", "").startswith("Bearer at-"):
            return True
        self._json(401, {"error": {"code": 401, "message": "Invalid Credentials"}})
        return False

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.path == "/_videos":
            return self._json(200, {"videos": VIDEOS, "log": LOG, "thumbs": THUMBS})
        if not self._authed():
            return
        if u.path == "/youtube/v3/channels":
            return self._json(200, {"items": [{"id": "UC_fake", "snippet": {"title": "Carry Clips",
                                                "thumbnails": {"default": {"url": "http://x/t.jpg"}}}}]})
        if u.path == "/youtube/v3/videos":
            v = VIDEOS.get(q.get("id"))
            return self._json(200, {"items": [{"id": q.get("id"), "status": v["status"]}] if v else []})
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        body = self._body()
        if u.path == "/token":
            f = dict(urllib.parse.parse_qsl(body.decode()))
            LOG.append(("token", f.get("grant_type")))
            if f.get("grant_type") == "authorization_code":
                if f.get("code") not in CODES or not f.get("code_verifier"):
                    return self._json(400, {"error": "invalid_grant", "error_description": "Bad code"})
                return self._json(200, {"access_token": "at-" + uuid.uuid4().hex[:6], "refresh_token": "rt-1",
                                        "expires_in": 3600})
            if f.get("grant_type") == "refresh_token" and f.get("refresh_token") == "rt-1":
                return self._json(200, {"access_token": "at-" + uuid.uuid4().hex[:6], "expires_in": 3600})
            return self._json(400, {"error": "invalid_grant"})
        if u.path == "/upload/youtube/v3/thumbnails/set":
            if not self._authed():
                return
            q = dict(urllib.parse.parse_qsl(u.query))
            vid = q.get("videoId")
            if vid not in VIDEOS:
                return self._json(404, {"error": {"code": 404, "errors": [{"reason": "videoNotFound"}]}})
            if not VIDEOS[vid].get("thumb_tried"):  # first try: still processing
                VIDEOS[vid]["thumb_tried"] = True
                return self._json(404, {"error": {"code": 404, "errors": [{"reason": "videoNotFound"}]}})
            if len(body) > 2 * 1024 * 1024 or self.headers.get("Content-Type") not in ("image/jpeg", "image/png"):
                return self._json(400, {"error": {"code": 400, "errors": [{"reason": "invalidImage"}]}})
            THUMBS[vid] = {"bytes": len(body), "jpeg": body[:3] == b"\xff\xd8\xff"}
            return self._json(200, {"kind": "youtube#thumbnailSetResponse", "items": [{"default": {"url": "x"}}]})
        if u.path == "/upload/youtube/v3/videos":
            if not self._authed():
                return
            meta = json.loads(body)
            if os.environ.get("FAKE_YT_QUOTA") == "1":
                return self._json(403, {"error": {"code": 403, "message": "quota",
                                                  "errors": [{"reason": "quotaExceeded"}]}})
            sid = uuid.uuid4().hex[:8]
            SESSIONS[sid] = {"meta": meta, "size": int(self.headers["X-Upload-Content-Length"]), "got": 0, "failed": False}
            port = self.server.server_address[1]
            self.send_response(200)
            self.send_header("Location", f"http://127.0.0.1:{port}/upload/session/{sid}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._json(404, {"error": {"message": "not found"}})

    def do_PUT(self):
        u = urllib.parse.urlparse(self.path)
        body = self._body()
        if not u.path.startswith("/upload/session/") or not self._authed():
            return
        s = SESSIONS[u.path.rsplit("/", 1)[1]]
        rng = self.headers.get("Content-Range", "")
        if body:
            start = int(rng.split(" ")[1].split("-")[0])
            if start != s["got"]:
                return self._json(400, {"error": {"message": f"bad offset {start} != {s['got']}"}})
            if s["got"] > 0 and not s["failed"]:  # one simulated server hiccup per upload
                s["failed"] = True
                return self._json(503, {"error": {"message": "backend error"}})
            s["got"] += len(body)
        if s["got"] < s["size"]:
            self.send_response(308)
            if s["got"]:
                self.send_header("Range", f"bytes=0-{s['got'] - 1}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        vid = "vid" + uuid.uuid4().hex[:8]
        st = dict(s["meta"]["status"])
        if os.environ.get("FAKE_YT_LOCKED") == "1":
            st = {"privacyStatus": "private", "uploadStatus": "uploaded"}
        VIDEOS[vid] = {"snippet": s["meta"]["snippet"], "status": st, "bytes": s["got"]}
        self._json(200, {"id": vid, "status": st})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
