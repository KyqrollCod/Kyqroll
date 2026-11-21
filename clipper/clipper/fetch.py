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


def _safe(name):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", str(name or "")).strip("_")[:40]


def video_folder(work_root, key, info=None):
    """One folder per video, named for people: <配信日>_<配信者>_<id> (e.g. 20261120_ろあろああ_tw_2934905292).
    An existing folder for the same id is reused, whatever its prefix."""
    if os.path.isdir(work_root):
        for n in sorted(os.listdir(work_root)):
            if (n == key or n.endswith("_" + key)) and os.path.isdir(os.path.join(work_root, n)):
                return os.path.join(work_root, n)
    info = info or {}
    parts = [info.get("upload_date"), _safe(info.get("uploader") or info.get("channel")), key]
    return os.path.join(work_root, "_".join(p for p in parts if p))


def probe(url, cookies_from_browser=None):
    import yt_dlp
    opts = {"quiet": True, "skip_download": True, "noplaylist": True}
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def fetch(url, work_root=None, cookies_from_browser=None, max_height=1080, on_progress=None, head=None):
    import yt_dlp  # imported here so render-only use needs no yt-dlp
    from .common import default_work_root

    work_root = work_root or default_work_root()
    key = video_key(url)
    head = head or probe(url, cookies_from_browser)
    wd = video_folder(work_root, key, head)
    os.makedirs(wd, exist_ok=True)

    def hook(d):
        if on_progress and d.get("status") == "downloading":
            tot = d.get("total_bytes") or d.get("total_bytes_estimate")
            if tot:
                on_progress(min(0.99, d.get("downloaded_bytes", 0) / tot))
    opts = {
        "progress_hooks": [hook],
        "outtmpl": os.path.join(wd, "source.%(ext)s"),
        "format": f"bv*[height<={max_height}]+ba/b[height<={max_height}]/bv*+ba/b",
        "merge_output_format": "mp4",
        "writesubtitles": True,
        "subtitleslangs": ["live_chat"],
        "writeinfojson": True,
        "noplaylist": True,
        "concurrent_fragment_downloads": 8,
        "retries": 10,
        "quiet": True,
        "noprogress": True,
    }
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    meta = {k: info.get(k) for k in ("id", "title", "channel", "uploader", "duration", "upload_date",
                                     "webpage_url", "extractor_key", "fps", "width", "height")}
    meta["chapters"] = [{"start": c.get("start_time"), "end": c.get("end_time"), "title": c.get("title")}
                        for c in info.get("chapters") or []]   # Twitch: the game per section
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
