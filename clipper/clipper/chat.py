"""Normalize chat replays to [{t, text}] (seconds from VOD start)."""
import json


def _yt_text(renderer):
    runs = (renderer.get("message") or {}).get("runs") or []
    out = []
    for r in runs:
        if "text" in r:
            out.append(r["text"])
        elif "emoji" in r:
            sc = (r["emoji"].get("shortcuts") or [""])[0]
            out.append(sc or r["emoji"].get("emojiId", ""))
    return "".join(out)


def _from_youtube(lines):
    msgs = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        rep = d.get("replayChatItemAction") or {}
        t = int(rep.get("videoOffsetTimeMsec", d.get("videoOffsetTimeMsec", -1))) / 1000
        if t < 0:
            continue
        for act in rep.get("actions") or []:
            item = (act.get("addChatItemAction") or {}).get("item") or {}
            for kind in ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer"):
                if kind in item:
                    msgs.append({"t": round(t, 2), "text": _yt_text(item[kind]),
                                 "paid": kind == "liveChatPaidMessageRenderer"})
    return msgs


def _from_twitch(d):
    return [{"t": round(float(c["content_offset_seconds"]), 2), "text": (c.get("message") or {}).get("body", "")}
            for c in d.get("comments", [])]


def normalize_chat(path):
    """Accepts yt-dlp live_chat.json (JSON lines), TwitchDownloader JSON, or [{t, text}]."""
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        d = None
    if isinstance(d, dict) and "comments" in d:
        return sorted(_from_twitch(d), key=lambda m: m["t"])
    if isinstance(d, list):
        return sorted(({"t": float(m["t"]), "text": m.get("text", "")} for m in d), key=lambda m: m["t"])
    return sorted(_from_youtube(raw.splitlines()), key=lambda m: m["t"])
