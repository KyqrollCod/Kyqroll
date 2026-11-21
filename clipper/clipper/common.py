"""Shared helpers: config loading, paths, ffmpeg/ffprobe calls."""
import json
import os
import re
import shutil
import subprocess
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def save_yaml(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False, width=120)


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def style(path=None):
    return load_yaml(path or os.path.join(ROOT, "config", "style.yaml"))


class gpu_lock:
    """Cross-process lock around GPU-heavy stages (transcribe, voice stems + alignment, qc ASR).
    Two clipper processes on one 12 GB GPU (prepare + an editing build) crashed the process
    outright (exit 9) twice; taking turns costs minutes, a crash costs the whole queue."""

    def __init__(self, what=""):
        import tempfile
        self.path = os.path.join(tempfile.gettempdir(), "clipper_gpu.lock")
        self.what = what
        self.fh = None

    def __enter__(self):
        import time
        self.fh = open(self.path, "a+")
        waited = False
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if not waited:
                    print(f"  GPU の順番待ち（{self.what}）…", flush=True)
                    waited = True
                time.sleep(3)

    def __exit__(self, *exc):
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()
        return False


def default_work_root():
    """Where fetch creates one folder per video. Machine-local, so it lives outside git:
    env CLIPPER_WORK_ROOT, else config/local.yaml `work_root`, else clipper/work."""
    if os.environ.get("CLIPPER_WORK_ROOT"):
        return os.environ["CLIPPER_WORK_ROOT"]
    local = os.path.join(ROOT, "config", "local.yaml")
    if os.path.exists(local):
        root = (load_yaml(local) or {}).get("work_root")
        if root:
            return root
    return os.path.join(ROOT, "work")


def glossary(path=None):
    g = load_yaml(path or os.path.join(ROOT, "config", "glossary.yaml"))
    g.setdefault("terms", [])
    g.setdefault("replace", {})
    g.setdefault("hype_words", [])
    return g


def apply_glossary(text, gl):
    for pat, rep in (gl.get("replace") or {}).items():
        text = re.sub(pat, rep, text)
    return text


def fonts_dir(st):
    d = st.get("fonts_dir", "assets/fonts")
    return d if os.path.isabs(d) else os.path.join(ROOT, d)


def need(binary):
    path = shutil.which(binary)
    if not path:
        sys.exit(f"{binary} が見つかりません。README の セットアップ を参照してください。")
    return path


def run(cmd, cwd=None, capture=False):
    """Run a command, raising with its stderr tail on failure."""
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                       stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-25:])
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(map(str, cmd[:6]))} ...\n{tail}")
    return p.stdout if capture else p.stderr


_FF_MAJOR = None


def filter_script_args(path):
    """ffmpeg >= 7 reads option values from files with '-/opt'; older uses -filter_complex_script."""
    global _FF_MAJOR
    if _FF_MAJOR is None:
        out = run([need("ffmpeg"), "-hide_banner", "-version"], capture=True)
        m = re.search(r"version\s+n?(\d+)\.", out, re.I)
        # Git builds (BtbN "N-118xxx-g...") are always current.
        _FF_MAJOR = int(m.group(1)) if m else (99 if re.search(r"version\s+N-", out) else 6)
    return ["-/filter_complex", path] if _FF_MAJOR >= 7 else ["-filter_complex_script", path]


def ffprobe(path):
    out = run([need("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
              capture=True)
    return json.loads(out)


def media_info(path):
    info = ffprobe(path)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    fps = 30.0
    if v and v.get("avg_frame_rate", "0/0") != "0/0":
        n, d = v["avg_frame_rate"].split("/")
        fps = float(n) / float(d) if float(d) else 30.0
    return {
        "duration": float(info["format"].get("duration", 0)),
        "width": int(v["width"]) if v else 0,
        "height": int(v["height"]) if v else 0,
        "fps": fps,
        "vcodec": v.get("codec_name") if v else None,
        "acodec": a.get("codec_name") if a else None,
        "has_audio": a is not None,
    }


def ff_escape(path):
    """Escape a path as an UNQUOTED filter option value inside a filtergraph (Windows-safe).

    Two levels: first the option value (\\ ' :), then the filtergraph (\\ ' [ ] , ;).
    Quoting is avoided because inside '...' ffmpeg cannot express an apostrophe (O'Brien)."""
    p = os.path.abspath(path).replace("\\", "/")
    lvl1 = "".join("\\" + c if c in "\\':" else c for c in p)
    return "".join("\\" + c if c in "\\'[],;" else c for c in lvl1)


def ass_color(hex_rgb, alpha=0):
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def work_dir(arg):
    d = os.path.abspath(arg)
    if not os.path.isdir(d):
        sys.exit(f"作業フォルダがありません: {d}")
    return d


def source_path(wd):
    for name in sorted(os.listdir(wd)):
        if name.startswith("source.") and name.rsplit(".", 1)[-1] in ("mp4", "mkv", "webm", "mov"):
            return os.path.join(wd, name)
    sys.exit(f"source.* が {wd} にありません（fetch を先に実行）")
