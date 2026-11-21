"""Download a VOD and its chat replay into a work folder (run on the user's own PC).

YouTube refuses datacenter IPs, so this runs where the user's browser lives. With
`--cookies-from-browser chrome` yt-dlp uses the user's own signed-in session, the same
way tokodake's desktop import app does.
"""
import os
import re
import shutil
import subprocess

from .common import save_json
from .chat import normalize_chat


def video_key(url):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|live/)([\w-]{11})", url)
    if m:
        return "yt_" + m.group(1)
    m = re.search(r"twitch\.tv/videos/(\d+)", url)
    if m:
        return "tw_" + m.group(1)
    return "vod_" + re.sub(r"\W+", "_", url)[-24:]


def twitch_chat_gql(video_id, duration, step=600):
    """Twitch chat replay without TwitchDownloaderCLI, via the public web GQL endpoint
    (the same client id yt-dlp uses). Without a browser integrity token Twitch may return only a
    sample of the comments, so treat the result as a weak signal. Observed 2026-11: each query
    returned comments from across the whole VOD regardless of the offset, so querying every
    `step` seconds and de-duplicating by id does not bunch them at offsets. Returns [{t, text}]."""
    import json
    import urllib.request
    q = ("query($id: ID!, $off: Int) { video(id: $id) { comments(contentOffsetSeconds: $off) { "
         "edges { node { id contentOffsetSeconds message { fragments { text } } } } } } }")
    seen, msgs = set(), []
    for off in range(0, int(duration) + step, step):
        body = json.dumps({"query": q, "variables": {"id": video_id, "off": off}}).encode()
        req = urllib.request.Request("https://gql.twitch.tv/gql", data=body, headers={
            "Client-ID": "kimne78kx3ncx6brgo4mv6wki5h1ko", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            video = json.loads(r.read())["data"]["video"] or {}
        for e in ((video.get("comments") or {}).get("edges") or []):
            n = e["node"]
            if n["id"] not in seen:
                seen.add(n["id"])
                msgs.append({"t": float(n["contentOffsetSeconds"]),
                             "text": "".join(f.get("text") or "" for f in (n.get("message") or {}).get("fragments") or [])})
    return sorted(msgs, key=lambda m: m["t"])


def fetch(url, work_root, cookies_from_browser=None, max_height=1080):
    import yt_dlp  # imported here so render-only use needs no yt-dlp

    key = video_key(url)
    wd = os.path.join(work_root, key)
    os.makedirs(wd, exist_ok=True)
    opts = {
        "outtmpl": os.path.join(wd, "source.%(ext)s"),
        "format": f"bv*[height<={max_height}]+ba/b[height<={max_height}]/bv*+ba/b",
        "merge_output_format": "mp4",
        "writesubtitles": True,
        "subtitleslangs": ["live_chat"],
        "writeinfojson": True,
        "noplaylist": True,
        "concurrent_fragment_downloads": 8,
        "retries": 10,
        "quiet": False,
    }
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    meta = {k: info.get(k) for k in ("id", "title", "channel", "uploader", "duration", "upload_date",
                                     "webpage_url", "extractor_key", "fps", "width", "height")}
    save_json(os.path.join(wd, "meta.json"), meta)

    raw = next((os.path.join(wd, n) for n in os.listdir(wd) if n.endswith(".live_chat.json")), None)
    if not raw and key.startswith("tw_") and shutil.which("TwitchDownloaderCLI"):
        raw = os.path.join(wd, "twitch_chat.json")
        subprocess.run(["TwitchDownloaderCLI", "chatdownload", "--id", key[3:], "-o", raw], check=True)
    if not raw and key.startswith("tw_"):
        try:
            msgs = twitch_chat_gql(key[3:], meta.get("duration") or 0)
            raw = os.path.join(wd, "twitch_chat.json")
            save_json(raw, msgs)
            print(f"chat: {len(msgs)} messages (Twitch GQL)")
        except Exception as e:  # chat is optional; analysis still runs on audio and transcript
            print(f"chat: skipped ({e})")
    if raw:
        save_json(os.path.join(wd, "chat.json"), normalize_chat(raw))
    return wd
