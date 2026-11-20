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
    if raw:
        save_json(os.path.join(wd, "chat.json"), normalize_chat(raw))
    return wd
