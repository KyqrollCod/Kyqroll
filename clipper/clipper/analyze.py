"""Find highlight candidates from chat, reactions, loudness, keywords and on-screen events.

Each signal becomes a per-second series, robust-z-scored, smoothed, weighted and summed.
Peaks are picked with a minimum spacing, then each window is snapped to sentence
boundaries so a clip starts on a complete thought and ends on a line.
"""
import glob
import os
import re
import subprocess

import numpy as np

from .common import load_json, need, save_json


def _robust_z(x):
    med = np.median(x)
    mad = np.median(np.abs(x - med)) * 1.4826 + 1e-6
    return np.clip((x - med) / mad, -3, 8)


def _smooth(x, n):
    if n <= 1:
        return x
    k = np.ones(n) / n
    return np.convolve(x, k, mode="same")


def loudness_series(src, duration, bin_sec):
    """RMS dBFS per bin, read as 8 kHz mono PCM straight from ffmpeg."""
    sr = 8000
    n_bins = int(duration / bin_sec) + 1
    out = np.full(n_bins, -90.0)
    proc = subprocess.Popen([need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", src, "-vn",
                             "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"], stdout=subprocess.PIPE)
    per = int(sr * bin_sec)
    i, buf = 0, b""
    while True:
        chunk = proc.stdout.read(per * 2 * 64)
        if not chunk:
            break
        buf += chunk
        while len(buf) >= per * 2 and i < n_bins:
            a = np.frombuffer(buf[:per * 2], dtype=np.int16).astype(np.float32) / 32768
            buf = buf[per * 2:]
            out[i] = 20 * np.log10(np.sqrt(np.mean(a * a)) + 1e-9)
            i += 1
    proc.wait()
    return out


def chat_series(chat, n_bins, bin_sec, lag, patterns, hype):
    rate = np.zeros(n_bins)
    react = np.zeros(n_bins)
    kw = np.zeros(n_bins)
    rx = re.compile("|".join(patterns)) if patterns else None
    hx = re.compile("|".join(map(re.escape, hype))) if hype else None
    for m in chat:
        i = int((m["t"] - lag) / bin_sec)
        if 0 <= i < n_bins:
            rate[i] += 1 + (2 if m.get("paid") else 0)
            if rx and rx.search(m["text"]):
                react[i] += 1
            if hx and hx.search(m["text"]):
                kw[i] += 0.5
    return rate, react, kw


def speech_keyword_series(words, n_bins, bin_sec, hype):
    kw = np.zeros(n_bins)
    if not hype:
        return kw
    text_by_bin = {}
    for w in words:
        i = int(w["start"] / bin_sec)
        if 0 <= i < n_bins:
            text_by_bin[i] = text_by_bin.get(i, "") + w["word"]
    hx = re.compile("|".join(map(re.escape, hype)))
    for i, t in text_by_bin.items():
        kw[i] += len(hx.findall(t))
    return kw


def event_series(src, duration, n_bins, bin_sec, template_dir):
    """Optional: match on-screen templates (e.g. a game's ロン/ツモ banner) at 2 fps."""
    files = sorted(glob.glob(os.path.join(template_dir, "*.png")))
    ev = np.zeros(n_bins)
    if not files:
        return ev, []
    try:
        import cv2
    except ImportError:
        return ev, ["opencv が無いため画面イベント検出を省略（pip install opencv-python-headless）"]
    W, H = 640, 360
    temps = []
    for f in files:
        t = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
        if t is not None:
            temps.append((os.path.basename(f), t))
    proc = subprocess.Popen([need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", src,
                             "-vf", f"fps=2,scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
                            stdout=subprocess.PIPE)
    frame, k = W * H, 0
    hits = []
    while True:
        raw = proc.stdout.read(frame)
        if len(raw) < frame:
            break
        img = np.frombuffer(raw, dtype=np.uint8).reshape(H, W)
        t = k / 2
        for name, tp in temps:
            if tp.shape[0] > H or tp.shape[1] > W:
                continue
            score = cv2.matchTemplate(img, tp, cv2.TM_CCOEFF_NORMED).max()
            if score > 0.72:
                i = int(t / bin_sec)
                if i < n_bins:
                    ev[i] = max(ev[i], 4.0)
                hits.append({"t": t, "template": name, "score": round(float(score), 3)})
        k += 1
    proc.wait()
    return ev, hits


def sentence_bounds(words, gap):
    """Times where a new sentence starts (after a pause or sentence-final punctuation)."""
    starts, ends = [], []
    for i, w in enumerate(words):
        prev = words[i - 1] if i else None
        if prev is None or w["start"] - prev["end"] >= gap or re.search(r"[。！？!?]$", prev["word"].strip()):
            starts.append(w["start"])
            if prev is not None:
                ends.append(prev["end"])
    if words:
        ends.append(words[-1]["end"])
    return np.array(starts), np.array(ends)


def snap(t, arr, lo, hi):
    c = arr[(arr >= lo) & (arr <= hi)]
    if not len(c):
        return t
    return float(c[np.argmin(np.abs(c - t))])


def excerpt(words, a, b, limit=400):
    s = "".join(w["word"] for w in words if a <= w["start"] < b)
    return s[:limit] + ("…" if len(s) > limit else "")


def analyze(wd, src, duration, st, gl):
    an = st["analysis"]
    bs = an["bin_sec"]
    n = int(duration / bs) + 1
    words = load_json(os.path.join(wd, "transcript.json"))["words"] if os.path.exists(os.path.join(wd, "transcript.json")) else []
    chat = load_json(os.path.join(wd, "chat.json")) if os.path.exists(os.path.join(wd, "chat.json")) else []
    notes = []
    if not chat:
        notes.append("チャットなし: 声と発言だけで判定")
    if not words:
        notes.append("文字起こしなし: transcribe を先に実行すると精度が上がる")

    loud = loudness_series(src, duration, bs)
    rate, react, ckw = chat_series(chat, n, bs, an["chat_lag_sec"], an["react_patterns"], gl["hype_words"])
    skw = speech_keyword_series(words, n, bs, gl["hype_words"])
    from .common import ROOT
    ev, hits = event_series(src, duration, n, bs, os.path.join(ROOT, "config", "templates"))
    notes += [h for h in hits if isinstance(h, str)]
    hits = [h for h in hits if isinstance(h, dict)]

    sm = max(1, int(an["smooth_sec"] / bs))
    w = an["weights"]
    loud_rel = loud - _smooth(loud, max(3, int(60 / bs)))  # loud relative to the last minute
    parts = {
        "chat": _smooth(_robust_z(rate), sm) if chat else np.zeros(n),
        "react": _smooth(_robust_z(react), sm) if chat else np.zeros(n),
        "audio": _smooth(_robust_z(loud_rel), sm),
        "keyword": _smooth(ckw + skw, sm),
        "event": _smooth(ev, 3),
    }
    score = sum(w[k] * parts[k] for k in parts)

    starts, ends = sentence_bounds(words, an["sentence_gap"]) if words else (np.array([]), np.array([]))
    order = np.argsort(-score)
    gap = an["min_gap_sec"] / bs
    picked = []
    for i in order:
        if len(picked) >= an["candidates"]:
            break
        if score[i] <= 0:
            break
        if all(abs(i - j) >= gap for j in picked):
            picked.append(int(i))

    cands = []
    for rank, i in enumerate(picked, 1):
        peak = i * bs
        a0, b0 = peak + an["short_window"][0], peak + an["short_window"][1]
        a = snap(a0, starts, a0 - 10, peak - 5) if len(starts) else a0
        b = snap(b0, ends, peak + 3, b0 + 10) if len(ends) else b0
        a, b = max(0.0, a), min(duration, b)
        la, lb = max(0.0, peak + an["long_window"][0]), min(duration, peak + an["long_window"][1])
        drivers = sorted(((k, float(w[k] * parts[k][i])) for k in parts), key=lambda x: -x[1])
        top_chat = [m["text"] for m in chat if peak - 3 <= m["t"] - an["chat_lag_sec"] <= peak + 8][:12]
        cands.append({
            "rank": rank, "peak": round(peak, 1), "score": round(float(score[i]), 2),
            "short": {"start": round(a, 2), "end": round(b, 2)},
            "long": {"start": round(la, 1), "end": round(lb, 1)},
            "drivers": {k: round(v, 2) for k, v in drivers if abs(v) > 0.05},
            "events": [h for h in hits if abs(h["t"] - peak) < 20][:3],
            "chat_sample": top_chat,
            "transcript": excerpt(words, a, b),
        })
    out = {"duration": duration, "notes": notes, "candidates": cands,
           "signal_bins": {"bin_sec": bs, "score": [round(float(x), 2) for x in score]}}
    save_json(os.path.join(wd, "candidates.json"), out)
    with open(os.path.join(wd, "candidates.md"), "w", encoding="utf-8") as fh:
        fh.write(f"# 見どころ候補（{len(cands)}件）\n\n")
        for nt in notes:
            fh.write(f"- 注: {nt}\n")
        for c in cands:
            mm = lambda t: f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}"
            fh.write(f"\n## {c['rank']}. {mm(c['peak'])}  score {c['score']}\n")
            fh.write(f"- ショート案: {mm(c['short']['start'])}–{mm(c['short']['end'])}"
                     f"（{c['short']['end'] - c['short']['start']:.0f}秒）\n")
            fh.write(f"- 根拠: {', '.join(f'{k} {v}' for k, v in c['drivers'].items())}\n")
            if c["events"]:
                fh.write(f"- 画面イベント: {', '.join(e['template'] for e in c['events'])}\n")
            if c["chat_sample"]:
                fh.write(f"- チャット: {' / '.join(c['chat_sample'][:8])}\n")
            fh.write(f"- 発言: {c['transcript']}\n")
    return out
