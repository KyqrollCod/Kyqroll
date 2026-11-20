"""Automated quality gate for a rendered clip, plus a contact sheet for visual review."""
import os
import re

from .common import media_info, need, run


def _parse_intervals(err, kind):
    out = []
    if kind == "black":
        for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)", err):
            out.append((float(m.group(1)), float(m.group(3))))
    elif kind == "silence":
        for m in re.finditer(r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)", err):
            out.append((float(m.group(1)) - float(m.group(2)), float(m.group(2))))
    elif kind == "freeze":
        starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", err)]
        durs = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", err)]
        out = list(zip(starts, durs))
    return out


def _ts(x):
    h, m, s = x.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _norm(t):
    return re.sub(r"[\s、。！？!?…「」『』・,.~〜ー]", "", t)


def asr_sync(path, ass_path, model="medium"):
    """Re-transcribe the finished video and check every subtitle against what is actually heard.

    Returns (score, bad): score is the share of subtitles whose characters are mostly heard
    inside their own window (±0.4 s)."""
    import subprocess
    import difflib
    import numpy as np
    from faster_whisper import WhisperModel
    p = subprocess.run([need("ffmpeg"), "-loglevel", "error", "-i", path, "-ac", "1", "-ar", "16000",
                        "-f", "f32le", "-"], stdout=subprocess.PIPE, check=True)
    audio = np.frombuffer(p.stdout, dtype=np.float32)
    try:
        import ctranslate2
        dev = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    except Exception:
        dev = "cpu"
    m = WhisperModel(model, device=dev, compute_type="float16" if dev == "cuda" else "int8")
    segs, _ = m.transcribe(audio, language="ja", word_timestamps=True, vad_filter=True,
                           condition_on_previous_text=False)
    words = [w for s in segs for w in (s.words or [])]
    events = []
    for line in open(ass_path, encoding="utf-8-sig"):
        if line.startswith("Dialogue: 2,") and ",SubInner," in line:
            f = line.split(",")
            body = re.sub(r"\{[^}]*\}", "", line.rstrip("\n").split(",", 9)[9]).replace("\\N", "")
            events.append((_ts(f[1]), _ts(f[2]), body.strip()))
    ok, bad = 0, []
    for a, b, text in events:
        heard = "".join(w.word for w in words if a - 0.4 <= (w.start + w.end) / 2 <= b + 0.4)
        t, h = _norm(text), _norm(heard)
        if not t:
            continue
        sm = difflib.SequenceMatcher(None, t, h)
        cover = sum(x.size for x in sm.get_matching_blocks()) / len(t)
        if cover >= 0.6:
            ok += 1
        else:
            bad.append({"at": round(a, 2), "sub": text, "heard": heard, "cover": round(cover, 2)})
    return (ok / len(events) if events else 1.0), bad


def check(path, fmt, st, ass_path=None, sheet_path=None, asr_model=None):
    q, cfg = st["qc"], st[fmt]
    info = media_info(path)
    res = {"file": path, "format": fmt, "checks": [], "pass": True}

    def add(name, ok, detail, hard=True):
        res["checks"].append({"name": name, "ok": bool(ok), "detail": detail, "hard": hard})
        if hard and not ok:
            res["pass"] = False

    W, H = cfg["size"]
    add("resolution", (info["width"], info["height"]) == (W, H), f"{info['width']}x{info['height']}（期待 {W}x{H}）")
    add("codec", info["vcodec"] == "h264" and info["acodec"] == "aac", f"{info['vcodec']}/{info['acodec']}")
    add("fps", info["fps"] >= 29.0, f"{info['fps']:.2f}fps")
    d = info["duration"]
    if fmt == "short":
        add("duration", cfg["min_sec"] <= d <= cfg["max_sec"], f"{d:.1f}秒（{cfg['min_sec']}〜{cfg['max_sec']}）")
    else:
        add("duration", d >= cfg["min_sec"], f"{d:.1f}秒（{cfg['min_sec']}秒以上）")

    err = run([need("ffmpeg"), "-hide_banner", "-nostats", "-i", path,
               "-filter_complex", "[0:a]ebur128=peak=true[a];[0:v]blackdetect=d=0.2:pix_th=0.06,"
               "freezedetect=n=0.003:d=1.0[v]", "-map", "[a]", "-map", "[v]", "-f", "null", "-"])
    lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    peak = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", err)
    li = float(lufs[-1]) if lufs else -99
    tp = float(peak[-1]) if peak else 0
    target = st["audio"]["lufs"]
    add("loudness", abs(li - target) <= q["lufs_tolerance"], f"{li:.1f} LUFS（目標 {target}±{q['lufs_tolerance']}）")
    add("true_peak", tp <= -0.9, f"{tp:.1f} dBTP（-1.0以下）")
    black = [b for b in _parse_intervals(err, "black") if b[1] > q["max_black_sec"]]
    add("black_frames", not black, f"{len(black)}箇所 {black[:3]}")
    freeze = [f for f in _parse_intervals(err, "freeze") if f[1] > q["max_freeze_sec"]]
    add("frozen_video", not freeze, f"{len(freeze)}箇所 {freeze[:3]}", hard=False)

    err2 = run([need("ffmpeg"), "-hide_banner", "-nostats", "-i", path, "-af",
                "silencedetect=n=-45dB:d=0.5", "-vn", "-f", "null", "-"])
    sil = [s for s in _parse_intervals(err2, "silence") if s[1] > q["max_silence_sec"]]
    add("dead_air", not sil, f"{len(sil)}箇所 {[(round(a, 1), round(b, 1)) for a, b in sil[:3]]}")

    if ass_path and os.path.exists(ass_path):
        txt = open(ass_path, encoding="utf-8-sig").read()
        limit = q["max_line_chars_short"] if fmt == "short" else q["max_line_chars_long"]
        long_rows = []
        for m in re.finditer(r"^Dialogue: 2,[^,]*,[^,]*,SubInner,[^,]*,\d+,\d+,\d+,,(.*)$", txt, re.M):
            body = re.sub(r"\{[^}]*\}", "", m.group(1))
            long_rows += [r for r in body.split("\\N") if len(r) > limit]
        add("subtitle_line_length", not long_rows, f"{len(long_rows)}行が{limit}字超 {long_rows[:3]}")
        if fmt == "short":
            sf = cfg["safe"]
            limit_y = H - sf["bottom_px"]
            hk = cfg["hook"]
            hook_m = re.search(r"Hook,[^\n]*\\pos\(\d+,(\d+)\)\}(.*)", txt)
            if hook_m:
                rows = hook_m.group(2).count("\\N") + 1
                bottom = int(hook_m.group(1)) + rows * hk["font_size"] * 1.15
                add("safe_area_hook", bottom <= limit_y, f"オチ文の下端 {bottom:.0f}px（{limit_y}px以内）")
            add("safe_area_subs", cfg["subs"]["bottom_y"] <= limit_y, f"字幕の下端 {cfg['subs']['bottom_y']}px")

    if asr_model and ass_path and os.path.exists(ass_path):
        score, bad = asr_sync(path, ass_path, asr_model)
        add("subtitle_sync", score >= 0.9, f"{score:.0%} の字幕が音声と一致 {bad[:3]}")

    if sheet_path:
        every = q["contact_sheet_every_sec"]
        n = max(1, int(d / every))
        cols = 6 if fmt == "short" else 4
        rows = -(-n // cols)
        scale = "scale=216:-1" if fmt == "short" else "scale=480:-1"
        run([need("ffmpeg"), "-y", "-hide_banner", "-i", path, "-vf",
             f"fps=1/{every},{scale},tile={cols}x{rows}:padding=4:color=white", "-frames:v", "1", sheet_path])
        res["contact_sheet"] = sheet_path
    return res
