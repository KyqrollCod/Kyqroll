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


FFMPEG_MAX_GB = float(os.environ.get("CLIPPER_FFMPEG_MAX_GB", "12"))


def _memory_cap(pid, gb):
    """Windows: put the process in a job object with a per-process memory limit, so a runaway
    filter graph fails on its own instead of paging the whole PC to a halt (owner, 2026-11-22)."""
    if os.name != "nt" or gb <= 0:
        return
    import ctypes
    from ctypes import wintypes

    class _IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class _BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class _EXT(ctypes.Structure):
        _fields_ = [("Basic", _BASIC), ("Io", _IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = k32.CreateJobObjectW(None, None)
    info = _EXT()
    info.Basic.LimitFlags = 0x100   # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.ProcessMemoryLimit = int(gb * 1024 ** 3)
    k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
    h = k32.OpenProcess(0x0100 | 0x0001, False, pid)   # SET_QUOTA | TERMINATE
    if h:
        k32.AssignProcessToJobObject(job, h)
        k32.CloseHandle(h)
    return job   # keep the handle alive while the process runs


def run(cmd, cwd=None, capture=False):
    """Run a command, raising with its stderr tail on failure. ffmpeg runs at below-normal priority
    with a memory cap (FFMPEG_MAX_GB) so encoding never starves the rest of the PC."""
    is_ff = os.path.basename(str(cmd[0])).lower().startswith("ffmpeg")
    flags = 0x00004000 if (os.name == "nt" and is_ff) else 0   # BELOW_NORMAL_PRIORITY_CLASS
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=flags)
    job = _memory_cap(p.pid, FFMPEG_MAX_GB) if is_ff else None
    out, err = p.communicate()
    del job
    # ffmpeg treats an allocation failure in a demuxer as end of input and still exits 0, which
    # would leave a silently truncated video: count it as a failure.
    oom = is_ff and "Cannot allocate memory" in (err or "")
    if p.returncode != 0 or oom:
        tail = "\n".join(err.strip().splitlines()[-25:])
        hint = (f"\n（ffmpeg のメモリ上限 {FFMPEG_MAX_GB:g}GB に達した可能性があります）"
                if is_ff and ("Cannot allocate memory" in err or "out of memory" in err.lower()) else "")
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(map(str, cmd[:6]))} ...\n{tail}{hint}")
    return out if capture else err


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
