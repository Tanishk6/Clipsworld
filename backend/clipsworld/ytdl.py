"""Download a video from a link (YouTube etc.) with yt-dlp.

Only use this for your own videos or videos you have permission to clip.
"""
from pathlib import Path

from .paths import IS_WIN, resources_dir, tool


def download(job, url: str, dest_dir: Path) -> dict:
    import yt_dlp

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes", 0)
            if total:
                speed = d.get("speed") or 0
                job.update(progress=0.9 * got / total,
                           stage=f"Downloading video… {got / total * 100:.0f}%"
                                 + (f" ({speed / 1e6:.1f} MB/s)" if speed else ""))
        elif d.get("status") == "finished":
            job.update(stage="Merging video and audio…")

    opts = {
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "ffmpeg_location": str(Path(tool("ffmpeg")).parent),
        "progress_hooks": [hook],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "retries": 10,
        "fragment_retries": 10,
        "continuedl": True,
    }
    deno = resources_dir() / "deno" / ("deno.exe" if IS_WIN else "deno")
    if deno.exists():  # YouTube needs a JavaScript runtime for its player code
        opts["js_runtimes"] = {"deno": {"path": str(deno)}}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
        if not path.exists():
            found = sorted(dest_dir.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
            if not found:
                raise RuntimeError("Download finished but the video file was not found.")
            path = found[0]
    return {"path": str(path), "title": info.get("title") or "Downloaded video",
            "uploader": info.get("uploader") or info.get("channel") or "",
            "webpage_url": info.get("webpage_url") or url}
