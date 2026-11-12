"""Originality checker: how much of *you* is in a clip, based on YouTube's reused / inauthentic
content rules for the Partner Program. It gives a score and plain-language tips.

This is guidance, not a guarantee: YouTube reviewers make the final decision.
"""
RULES = [
    "Reused content: clips from other creators need real added value — your commentary, reaction, "
    "story, ranking or meaningful editing. Captions alone are usually not enough.",
    "Inauthentic content: avoid many near-identical videos made from one template with no real variation.",
    "Permission is separate from monetization: getting permission avoids copyright strikes, but YouTube "
    "still checks that you added something of your own.",
    "Your whole channel is reviewed. Remove plain re-uploads before applying for monetization.",
]


def check(project: dict, clip: dict, recent_styles: list | None = None) -> dict:
    checks = []
    score = 0
    aud = clip.get("audio") or {}
    effs = clip.get("effects") or []
    cap = clip.get("captions") or {}
    L = max(1.0, clip["end"] - clip["start"])

    def add(ok, pts, label, tip):
        nonlocal score
        if ok:
            score += pts
        checks.append({"ok": bool(ok), "points": pts, "label": label, "tip": None if ok else tip})

    has_vo = bool(aud.get("vo_file"))
    add(has_vo, 35, "Your voice / reaction is in the clip",
        "Record a voiceover or facecam reaction (Audio tab). This is the strongest way to make a clip yours.")
    kinds = {e["type"] for e in effs}
    edit_pts = min(20, 5 * len(kinds & {"zoom", "shake", "freeze", "replay", "text"}))
    add(edit_pts >= 10, 20, f"Real editing ({len(effs)} effects)",
        "Add zooms, a freeze frame with text, a replay or text pops (Effects tab), or press Auto edit.")
    if 0 < edit_pts < 10:
        score += edit_pts
    add(cap.get("enabled", True) and bool(cap.get("cues")), 10, "Captions on",
        "Turn captions on: most Shorts are watched without sound.")
    add(bool(clip.get("hook")) and cap.get("show_hook"), 5, "Hook text in the first seconds",
        "Add a hook line so viewers know why to keep watching.")
    add(bool(project.get("credit")), 10, "Original creator is credited",
        "Add the original creator's name in the Export tab so the description credits them.")
    add(L <= 60, 5, "Short and focused (60 sec or less)",
        "Shorter clips that get to the point usually perform better and look less like a re-upload.")
    varied = True
    if recent_styles:
        same = sum(1 for s in recent_styles if s == (cap.get("style"), tuple(sorted(kinds))))
        varied = same < 4
    add(varied, 5, "Varied style across your uploads",
        "Your last uploads all look the same. Change the caption style or effects to avoid looking mass-produced.")
    add(cap.get("language", "original") != "original" or has_vo or len(effs) >= 3, 10, "Transformed for a new audience",
        "Translate the captions (e.g. Hindi → Hinglish/English) or add more of your own editing.")
    score = min(100, score)
    level = "great" if score >= 70 else "ok" if score >= 45 else "risky"
    summary = {
        "great": "Looks original. Clips like this have the best chance with YouTube's reused-content review.",
        "ok": "Some of you is in this clip, but adding your voice or more editing would make it safer.",
        "risky": "This mostly looks like someone else's video. It may fail YouTube's reused-content review.",
    }[level]
    return {"score": score, "level": level, "summary": summary, "checks": checks, "rules": RULES}
