"""YouTube connection: Google sign-in (desktop OAuth with PKCE) and resumable, scheduled uploads.

The user creates their own Google Cloud "Desktop app" OAuth client (free) and pastes its ID and
secret into Clipsworld. Tokens are stored only on this PC.
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .paths import data_dir

AUTH_URL = os.environ.get("CLIPSWORLD_YT_AUTH", "https://accounts.google.com/o/oauth2/v2/auth")
TOKEN_URL = os.environ.get("CLIPSWORLD_YT_TOKEN", "https://oauth2.googleapis.com/token")
API = os.environ.get("CLIPSWORLD_YT_API", "https://www.googleapis.com")
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
CHUNK = int(os.environ.get("CLIPSWORLD_YT_CHUNK") or 8 * 1024 * 1024)  # multiple of 256 KB

_lock = threading.Lock()


class YTError(RuntimeError):
    pass


def _file() -> Path:
    return data_dir() / "youtube.json"


def _load() -> dict:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d: dict):
    with _lock:
        _file().write_text(json.dumps(d, indent=2), encoding="utf-8")


def status() -> dict:
    d = _load()
    return {"has_client": bool(d.get("client_id") and d.get("client_secret")),
            "client_id_hint": (d.get("client_id", "")[:12] + "…") if d.get("client_id") else "",
            "connected": bool(d.get("refresh_token")), "channel": d.get("channel")}


def set_client(client_id: str, client_secret: str):
    d = _load()
    client_id, client_secret = client_id.strip(), client_secret.strip()
    if client_id.startswith("{"):  # the whole client_secret_*.json file was pasted
        try:
            j = json.loads(client_id)
            j = j.get("installed") or j.get("web") or j
            client_id, client_secret = j["client_id"], j["client_secret"]
        except (ValueError, KeyError, TypeError):
            raise YTError("That JSON isn't a Google OAuth client file.")
    if not client_secret:
        raise YTError("Paste the Client secret too.")
    if not client_id.endswith(".apps.googleusercontent.com") and "localhost" not in API:
        raise YTError("That doesn't look like a Google OAuth Client ID (it ends with .apps.googleusercontent.com).")
    if d.get("client_id") != client_id:
        d.pop("refresh_token", None)
        d.pop("channel", None)
    d["client_id"], d["client_secret"] = client_id, client_secret
    _save(d)
    return status()


def disconnect():
    d = _load()
    for k in ("refresh_token", "access_token", "expires_at", "channel", "pending"):
        d.pop(k, None)
    _save(d)
    return status()


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode())
        except Exception:
            err = {}
        msg = err.get("error_description") or err.get("error") or f"HTTP {e.code}"
        raise YTError(f"Google sign-in failed: {msg}")


def auth_url(redirect_uri: str) -> str:
    d = _load()
    if not d.get("client_id"):
        raise YTError("Add your Google OAuth Client ID and Secret first.")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    d["pending"] = {"state": state, "verifier": verifier, "redirect": redirect_uri, "at": int(time.time())}
    _save(d)
    q = {"client_id": d["client_id"], "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPES,
         "access_type": "offline", "prompt": "consent", "state": state,
         "code_challenge": challenge, "code_challenge_method": "S256", "include_granted_scopes": "true"}
    return AUTH_URL + "?" + urllib.parse.urlencode(q)


def handle_callback(code: str, state: str) -> dict:
    d = _load()
    p = d.get("pending") or {}
    if not code or state != p.get("state"):
        raise YTError("Sign-in link expired. Press Connect YouTube again.")
    tok = _post_form(TOKEN_URL, {"code": code, "client_id": d["client_id"], "client_secret": d["client_secret"],
                                 "redirect_uri": p["redirect"], "grant_type": "authorization_code",
                                 "code_verifier": p["verifier"]})
    if not tok.get("refresh_token"):
        raise YTError("Google didn't give offline access. Remove Clipsworld from your Google account's "
                      "third-party access and connect again.")
    d["refresh_token"] = tok["refresh_token"]
    d["access_token"] = tok["access_token"]
    d["expires_at"] = int(time.time()) + int(tok.get("expires_in", 3600)) - 60
    d.pop("pending", None)
    _save(d)
    try:
        d["channel"] = channel_info()
        _save(d)
    except Exception:  # noqa: BLE001
        pass
    return status()


def access_token() -> str:
    d = _load()
    if not d.get("refresh_token"):
        raise YTError("YouTube is not connected.")
    if d.get("access_token") and d.get("expires_at", 0) > time.time():
        return d["access_token"]
    tok = _post_form(TOKEN_URL, {"client_id": d["client_id"], "client_secret": d["client_secret"],
                                 "refresh_token": d["refresh_token"], "grant_type": "refresh_token"})
    d["access_token"] = tok["access_token"]
    d["expires_at"] = int(time.time()) + int(tok.get("expires_in", 3600)) - 60
    _save(d)
    return d["access_token"]


def _api(method: str, path: str, body=None, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {access_token()}", "Content-Type": "application/json; charset=UTF-8"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise YTError(_explain(e.code, e.read().decode(errors="replace")))


def _explain(code: int, text: str) -> str:
    try:
        err = json.loads(text).get("error", {})
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        msg = err.get("message", "")
    except Exception:
        reason, msg = "", text[:200]
    if reason in ("quotaExceeded", "uploadLimitExceeded", "rateLimitExceeded"):
        return "YouTube upload limit reached for today. Clipsworld will try again later."
    if code == 401:
        return "YouTube sign-in expired. Connect YouTube again in Autopilot → Setup."
    if code == 403:
        return f"YouTube refused the upload ({reason or msg}). Check the channel and the Google Cloud project."
    return f"YouTube error {code}: {msg or reason}"


def channel_info() -> dict:
    r = _api("GET", "/youtube/v3/channels", params={"part": "snippet", "mine": "true"})
    items = r.get("items") or []
    if not items:
        raise YTError("This Google account has no YouTube channel.")
    sn = items[0]["snippet"]
    return {"id": items[0]["id"], "title": sn.get("title"),
            "thumb": ((sn.get("thumbnails") or {}).get("default") or {}).get("url")}


def upload(path: str, title: str, description: str, tags: list, category_id: str = "24",
           privacy: str = "public", publish_at: str | None = None, made_for_kids: bool = False,
           progress=None) -> str:
    """Upload a video (resumable). With publish_at (RFC 3339 UTC), YouTube publishes it at that time."""
    size = os.path.getsize(path)
    status_part = {"selfDeclaredMadeForKids": bool(made_for_kids), "embeddable": True}
    if publish_at:
        status_part.update({"privacyStatus": "private", "publishAt": publish_at})
    else:
        status_part["privacyStatus"] = privacy
    meta = {"snippet": {"title": title[:100], "description": description[:4900],
                        "tags": [t.lstrip("#")[:30] for t in tags][:15], "categoryId": str(category_id),
                        "defaultLanguage": "hi", "defaultAudioLanguage": "hi"},
            "status": status_part}
    req = urllib.request.Request(
        API + "/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        data=json.dumps(meta).encode(), method="POST",
        headers={"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            session = r.headers.get("Location")
    except urllib.error.HTTPError as e:
        raise YTError(_explain(e.code, e.read().decode(errors="replace")))
    if not session:
        raise YTError("YouTube didn't start the upload. Try again.")
    sent = 0
    failures = 0
    with open(path, "rb") as f:
        while True:
            f.seek(sent)
            chunk = f.read(CHUNK)
            end = sent + len(chunk) - 1
            put = urllib.request.Request(session, data=chunk, method="PUT", headers={
                "Authorization": f"Bearer {access_token()}", "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {sent}-{end}/{size}" if chunk else f"bytes */{size}"})
            try:
                with urllib.request.urlopen(put, timeout=300) as r:
                    data = json.load(r)
                    if progress:
                        progress(1.0)
                    return data["id"]
            except urllib.error.HTTPError as e:
                if e.code == 308:  # resume incomplete: server tells how much it has
                    rng = e.headers.get("Range")
                    sent = int(rng.split("-")[1]) + 1 if rng else 0
                    failures = 0
                    if progress:
                        progress(sent / size)
                    continue
                if e.code in (500, 502, 503, 504) and failures < 6:
                    failures += 1
                    time.sleep(2 ** failures)
                    sent = _resume_point(session, size)
                    continue
                raise YTError(_explain(e.code, e.read().decode(errors="replace")))
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                failures += 1
                if failures > 6:
                    raise YTError(f"Upload kept failing ({e}). Check your internet.")
                time.sleep(2 ** failures)
                sent = _resume_point(session, size)


def _resume_point(session: str, size: int) -> int:
    put = urllib.request.Request(session, data=b"", method="PUT", headers={
        "Authorization": f"Bearer {access_token()}", "Content-Length": "0", "Content-Range": f"bytes */{size}"})
    try:
        with urllib.request.urlopen(put, timeout=60):
            return size
    except urllib.error.HTTPError as e:
        if e.code == 308:
            rng = e.headers.get("Range")
            return int(rng.split("-")[1]) + 1 if rng else 0
        return 0
    except Exception:
        return 0


def video_status(video_id: str) -> dict:
    r = _api("GET", "/youtube/v3/videos", params={"part": "status", "id": video_id})
    items = r.get("items") or []
    return items[0].get("status", {}) if items else {}


class ThumbRetry(YTError):
    """The video isn't ready for a thumbnail yet (still processing) or the rate limit hit: try later."""


def set_thumbnail(video_id: str, path: str) -> dict:
    """Upload a custom thumbnail (JPG/PNG, max 2 MB). Needs a phone-verified channel."""
    data = Path(path).read_bytes()
    if len(data) > 2 * 1024 * 1024:
        raise YTError("The thumbnail is bigger than 2 MB.")
    ctype = "image/png" if str(path).lower().endswith(".png") else "image/jpeg"
    req = urllib.request.Request(
        f"{API}/upload/youtube/v3/thumbnails/set?" + urllib.parse.urlencode({"videoId": video_id, "uploadType": "media"}),
        data=data, method="POST",
        headers={"Authorization": f"Bearer {access_token()}", "Content-Type": ctype, "Content-Length": str(len(data))})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")
        try:
            reason = (json.loads(text).get("error", {}).get("errors") or [{}])[0].get("reason", "")
        except Exception:  # noqa: BLE001
            reason = ""
        if e.code == 403 and reason in ("forbidden", ""):
            raise YTError("YouTube didn't allow a custom thumbnail. Verify your channel with your phone at "
                          "youtube.com/verify, then press Retry thumbnail.")
        if e.code in (404, 409, 429, 500, 502, 503) or reason in ("videoNotFound", "uploadRateLimitExceeded"):
            raise ThumbRetry(f"YouTube isn't ready for the thumbnail yet ({reason or e.code}).")
        raise YTError(_explain(e.code, text))
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise ThumbRetry(f"Network problem ({e}).")
