"""Automated quality gate for a rendered clip, plus a contact sheet for visual review."""
import os
import re

from .common import media_info, need, run
from .subs import dw, is_note


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


_KAKASI = None


_REPEAT = re.compile(r"(.{2,6}?)\1+")


def _norm(t, read=True):
    """Compare by sound, not spelling: punctuation dropped, kanji read as hiragana (read=True)
    and katakana folded to hiragana (ASR writes 「お前」「ヤバイ」 for the telop's 「おまえ」「やばい」).
    Immediate repeats collapse to one (「やばい」×4 vs ×3 heard is not a timing error)."""
    global _KAKASI
    if read:
        try:   # read kanji BEFORE dropping punctuation: 「お前、食べる」 joined becomes おぜんしょく…
            if _KAKASI is None:
                import pykakasi
                _KAKASI = pykakasi.kakasi()
            t = "".join(x["hira"] for x in _KAKASI.convert(t))
        except ImportError:
            pass
    t = re.sub(r"[\s、。！？!?…「」『』（）()・,.~〜ー]", "", t)
    t = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in t)
    return _REPEAT.sub(r"\1", t)


def _cover(text, heard):
    """Share of the telop's sounds found in what was heard; the reading converter can misread
    run-together ASR text, so the better of 'read' and 'as written' counts."""
    import difflib
    best = 0.0
    for read in (True, False):
        t, h = _norm(text, read), _norm(heard, read)
        if t:
            sm = difflib.SequenceMatcher(None, t, h)
            best = max(best, sum(x.size for x in sm.get_matching_blocks()) / len(t))
    return best


def asr_sync(path, ass_path, model="medium"):
    """Re-transcribe the finished video and check every subtitle against what is actually heard.

    Returns (score, bad): score is the share of subtitles whose characters are mostly heard
    inside their own window (±0.4 s)."""
    import subprocess
    import difflib
    import numpy as np
    from .transcribe import _cuda_dll_paths
    _cuda_dll_paths()  # Windows: pip's cuBLAS/cuDNN DLLs are not on the loader path otherwise
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
    ok, bad, checked = 0, [], 0
    for a, b, text in events:
        heard = "".join(w.word for w in words if a - 0.6 <= (w.start + w.end) / 2 <= b + 0.6)
        if not _norm(text) or is_note(text):
            continue  # （…） is a translation of game/English audio, not a transcript of speech
        checked += 1
        cover = _cover(text, heard)
        if cover >= 0.6:
            ok += 1
        else:
            bad.append({"at": round(a, 2), "sub": text, "heard": heard, "cover": round(cover, 2)})
    return (ok / checked if checked else 1.0), bad


def check(path, fmt, st, ass_path=None, sheet_path=None, asr_model=None, opening=0.0):
    """opening: seconds of channel intro/teaser at the start (its designed fades are not defects)."""
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
    add("fps", info["fps"] >= 23.9, f"{info['fps']:.2f}fps")
    d = info["duration"]
    if fmt == "short":
        add("duration", cfg["min_sec"] <= d <= cfg["max_sec"], f"{d:.1f}秒（{cfg['min_sec']}〜{cfg['max_sec']}）")
    else:
        add("duration", d >= cfg["min_sec"], f"{d:.1f}秒（{cfg['min_sec']}秒以上）")
        # Owner 2026-11-22: about 10 minutes is the floor to aim for (a guide, so a warning only).
        tgt = cfg.get("target_min_sec", 600)
        add("duration_target", d >= tgt, f"{d / 60:.1f}分（目安 {tgt // 60}分以上）", hard=False)

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
    black = [b for b in _parse_intervals(err, "black") if b[1] > q["max_black_sec"] and b[0] > opening + 0.3]
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
            long_rows += [r for r in body.split("\\N") if dw(r) > limit]
        add("subtitle_line_length", not long_rows, f"{len(long_rows)}行が{limit}字超 {long_rows[:3]}")
        if fmt == "short":
            # Every text element's real box (from the ASS events) must stay clear of the
            # YouTube Shorts UI: the bottom strip (title, buttons) and the right column.
            sf = cfg["safe"]
            limit_y, limit_x = H - sf["bottom_px"], W - sf["right_px"]
            sizes = {"Hook": cfg["hook"]["font_size"], "Band": cfg["band"]["font_size"], "Label": 46,
                     "SubInner": cfg["subs"]["font_size"]}
            off, right = [], []
            for m in re.finditer(r"^Dialogue: \d+,[^,]*,[^,]*,(Hook|Band|Label|SubInner),[^\n]*?"
                                 r"\\pos\((\d+),(\d+)\)([^\n]*?)\}([^\n]*)$", txt, re.M):
                style_, x, y, tags, body = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4), m.group(5)
                body = re.sub(r"\{[^}]*\}", "", body)
                rows = body.split("\\N")
                scales = [int(v) for v in re.findall(r"\\fscx(\d+)", tags)]
                fs = sizes[style_] * (max(scales) / 100 if scales else 1.0)
                hgt = len(rows) * fs * 1.15
                bottom = y if style_ == "SubInner" else (y + hgt if style_ == "Hook" else y + hgt / 2)
                half_w = max(dw(r) for r in rows) * fs / 2
                if bottom > limit_y:
                    off.append(f"{style_}『{body[:10]}』下端{bottom:.0f}px")
                if bottom > H * 0.55 and x + half_w > limit_x:
                    right.append(f"{style_}『{body[:10]}』右端{x + half_w:.0f}px")
            add("safe_area_bottom", not off, f"{len(off)}件 {off[:3]}（下端{limit_y}px以内）")
            # The like/comment column only covers the lower right; reference channels run big
            # captions under it, so this is a warning, not a failure.
            add("safe_area_right", not right, f"{len(right)}件 {right[:3]}（右端{limit_x}px以内）", hard=False)

    if asr_model and ass_path and os.path.exists(ass_path):
        score, bad = asr_sync(path, ass_path, asr_model)
        add("subtitle_sync", score >= 0.9, f"{score:.0%} の字幕が音声と一致 {bad[:3]}")
        res["sync_bad"] = bad   # every mismatch, for review

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
