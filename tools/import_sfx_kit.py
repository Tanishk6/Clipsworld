"""Import the SFX Kit (https://github.com/wyzowl/sfx-kit, CC0 1.0) into resources/sfx.

Run: python tools/import_sfx_kit.py <path-to-cloned-sfx-kit>
Converts the categories useful for Shorts to Ogg Vorbis and writes resources/sfx/catalog.json with each
sound's description, uses and sync point (the instant in the file that should land on the action).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

KEEP = ["booms-and-bass", "cinematic-hits", "impacts", "whooshes", "swishes-and-zips", "reverse-whooshes",
        "risers-and-fallers", "pops", "appear-and-vanish", "bounce-spin-zoom", "shape-changes", "shimmers",
        "celebration", "notifications", "tones", "time", "money", "digital"]
OUT = Path(__file__).resolve().parents[1] / "resources" / "sfx"


def main(kit: Path):
    data = json.loads((kit / "sounds.json").read_text(encoding="utf-8"))["sounds"]
    for old in OUT.glob("*.wav"):  # the old synthesized sounds
        old.unlink()
    cat = {}
    for s in data:
        if s["category"] not in KEEP:
            continue
        dst = OUT / f"{s['id']}.ogg"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(kit / s["file"]),
                        "-c:a", "libvorbis", "-q:a", "5", "-ar", "48000", str(dst)], check=True)
        sync = s.get("sync") or {}
        cat[s["id"]] = {"name": s["name"], "category": s["category"], "description": s.get("description", ""),
                        "use_for": s.get("use_for", [])[:4], "duration": round(float(s.get("duration", 0)), 3),
                        "sync": round(float(sync.get("at", 0) or 0), 3)}
    (OUT / "catalog.json").write_text(json.dumps(cat, ensure_ascii=False, indent=0), encoding="utf-8")
    shutil.copy(kit / "LICENSE", OUT / "LICENSE-sfx-kit-CC0.txt")
    print(f"{len(cat)} sounds → {OUT}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
