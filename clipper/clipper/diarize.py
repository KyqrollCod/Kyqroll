"""Stream-wide speaker diarization: who is talking, for every telop line.

Judging each short telop line on its own (pitch + one embedding) was not reliable enough: game
audio, screams and overlaps make single lines noisy. This does what diarization systems do:

1. Speech windows (1.2 s, hop 0.6 s inside Silero-VAD speech) across the WHOLE stream are
   embedded (wespeaker ResNet34 via sherpa-onnx). Cached in <video>/diar.npz, so it runs once.
2. The windows are clustered (spherical k-means, k=6: streamer, partner, chat TTS, plus room for
   game voices and noise).
3. Clusters are named by evidence:
     配信者   the voice of the stream's opening minutes (the streamer greets her viewers)
     読み上げ the cluster holding the lines that ARE chat messages (the TTS bot reads chat verbatim)
     相手     the largest remaining cluster that is not game audio/noise
   Unnamed clusters close to a named one are merged into it; the rest are ignored.
4. Each telop line takes the majority role of the windows inside it (weighted by overlap).
   A line that is a chat message is always 読み上げ; "@名前:" in the script always wins.
"""
import difflib
import os
import re
import subprocess

import numpy as np

from .common import need

WIN, HOP, SR = 1.2, 0.6, 16000
ROLES = ("配信者", "相手", "読み上げ")
_NORM = re.compile(r"[\s、。,.!！?？…「」『』（）()・~〜ーwｗ]")


def _norm(t):
    t = _NORM.sub("", str(t))
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in t)


def _pcm(src, start, dur):
    p = subprocess.run([need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
                        "-i", src, "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], stdout=subprocess.PIPE, check=True)
    return np.frombuffer(p.stdout, dtype=np.float32)


def _extractor():
    import sherpa_onnx
    from .speakers import MODEL
    if not os.path.exists(MODEL):
        return None
    return sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=MODEL, num_threads=4, provider="cpu"))


def _embed(ex, x):
    st = ex.create_stream()
    st.accept_waveform(SR, x)
    st.input_finished()
    v = np.asarray(ex.compute(st), dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def build_index(wd, src, duration, chunk=600.0, on_progress=None):
    """Embeddings of speech windows over the whole stream (cached)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    from .speakers import f0_median
    cache = os.path.join(wd, "diar.npz")
    if os.path.exists(cache):
        z = np.load(cache)
        return {"t": z["t"], "e": z["e"], "f0": z["f0"]}
    ex = _extractor()
    if ex is None:
        return None
    opts = VadOptions(threshold=0.5, min_speech_duration_ms=400, min_silence_duration_ms=250, speech_pad_ms=30)
    T, E, F = [], [], []
    s0 = 0.0
    while s0 < duration:
        d = min(chunk, duration - s0)
        audio = _pcm(src, s0, d)
        for seg in get_speech_timestamps(audio, opts):
            a, b = seg["start"] / SR, seg["end"] / SR
            starts = [a] if b - a < WIN else list(np.arange(a, b - WIN + 1e-6, HOP))
            for w0 in starts:
                w1 = min(b, w0 + WIN)
                x = audio[int(w0 * SR):int(w1 * SR)]
                if len(x) < 0.5 * SR:
                    continue
                T.append((s0 + w0, s0 + w1))
                E.append(_embed(ex, x))
                F.append(f0_median(x))
        s0 += chunk
        if on_progress:
            on_progress(min(1.0, s0 / duration))
    idx = {"t": np.array(T, dtype=np.float32), "e": np.stack(E), "f0": np.array(F, dtype=np.float32)}
    np.savez_compressed(cache, **idx)
    return idx


def _kmeans(X, k, iters=50, seeds=6):
    rng = np.random.default_rng(0)
    best, best_score = None, -1e18
    for _ in range(seeds):
        cent = [X[rng.integers(len(X))]]
        for _ in range(1, k):
            d = np.clip(1 - np.max(X @ np.array(cent).T, axis=1), 0, None)
            cent.append(X[rng.choice(len(X), p=d / d.sum())] if d.sum() > 0 else X[rng.integers(len(X))])
        C = np.array(cent)
        for _ in range(iters):
            lab = np.argmax(X @ C.T, axis=1)
            newC = np.array([X[lab == j].mean(0) if np.any(lab == j) else C[j] for j in range(k)])
            newC /= np.linalg.norm(newC, axis=1, keepdims=True) + 1e-9
            if np.allclose(newC, C, atol=1e-5):
                break
            C = newC
        score = float(np.sum(np.max(X @ C.T, axis=1)))
        if score > best_score:
            best, best_score = (lab, C), score
    return best


def is_chat_line(text, chat_norm):
    t = _norm(text)
    return len(t) >= 4 and any(len(t) <= len(m) * 1.25 and difflib.SequenceMatcher(None, t, m).ratio() >= 0.7
                               for m in chat_norm)


def name_clusters(idx, lab, C, chat_lines_spans, k):
    """Map cluster id -> role (or None). chat_lines_spans: [(s, e)] of lines that are chat messages."""
    t = idx["t"]
    n = np.bincount(lab, minlength=k).astype(float)
    # 配信者: the very first seconds of speech (her opening words to viewers). A wider window
    # (first 2 min) also caught the partner's replies and named the wrong voice.
    first = np.argsort(t[:, 0])[:20]
    S = int(np.bincount(lab[first], minlength=k).argmax())
    # 相手: of the sizeable clusters, the voice least like the streamer's.
    big = [j for j in range(k) if j != S and n[j] >= 0.05 * n.sum()]
    names = {S: "配信者"}
    if not big:
        return names
    P = min(big, key=lambda j: float(C[j] @ C[S]))
    names[P] = "相手"
    # Every other cluster joins the closer of the two voices, unless it is like neither
    # (game voice lines, music, noise). The chat TTS is identified by text, not by cluster:
    # its voice sat inside the streamer's clusters and naming a cluster for it misfired.
    for j in range(k):
        if j in names:
            continue
        sS, sP = float(C[j] @ C[S]), float(C[j] @ C[P])
        if max(sS, sP) >= 0.35:
            names[j] = "配信者" if sS >= sP else "相手"
    return names


def voice_refs(idx, low=(90.0, 150.0), high=(205.0, 300.0)):
    """Reference voices from the whole stream: windows with an unmistakably low pitch vs a high
    one (thousands of windows, so a few screams or game voices barely move the mean).
    Returns {"low": centroid, "high": centroid, "streamer": "low"|"high"}."""
    e, f0, t = idx["e"], idx["f0"], idx["t"]
    lo = e[(f0 > low[0]) & (f0 < low[1])]
    hi = e[(f0 > high[0]) & (f0 < high[1])]
    if len(lo) < 20 or len(hi) < 20:
        return None
    cl = lo.mean(0); cl /= np.linalg.norm(cl)
    ch = hi.mean(0); ch /= np.linalg.norm(ch)
    first = np.argsort(t[:, 0])[:20]   # her opening words to viewers
    s_low = float(np.mean(e[first] @ cl)) > float(np.mean(e[first] @ ch))
    return {"low": cl, "high": ch, "streamer": "low" if s_low else "high"}


def label_lines(wd, src, duration, clips, chat, on_progress=None, low_hz=155.0, margin=0.02):
    """Set ln['speaker'] (配信者/相手/読み上げ) on every non-note line of `clips`. Returns a report.

    Per line, in order of evidence strength:
      1. "@名前:" in the script (hand-set)                       → that speaker
      2. the line is a chat message                               → 読み上げ
      3. its own pitch is below `low_hz` (a woman's voice rarely is) → the low voice
      4. its own embedding vs the stream-wide reference voices    → the nearer one
    A high pitch alone is not trusted: a man screaming reaches 300 Hz."""
    from .subs import is_note
    from .speakers import f0_median
    idx = build_index(wd, src, duration, on_progress=on_progress)
    if idx is None or len(idx["e"]) < 50:
        return {}
    refs = voice_refs(idx)
    if refs is None:
        return {}
    role = {refs["streamer"]: "配信者", ("high" if refs["streamer"] == "low" else "low"): "相手"}
    chat_norm = [_norm(m.get("text", "")) for m in chat or [] if len(_norm(m.get("text", ""))) >= 4]
    ex = _extractor()
    report = {}
    for c in clips:
        subs = [ln for ln in c.get("subs") or [] if not is_note(ln["text"])]
        if not subs:
            continue
        a0 = float(c["start"])
        audio = _pcm(src, a0, float(c["end"]) - a0)
        for ln in subs:
            how, conf = "手動", 1.0
            if not ln.get("_forced"):
                if is_chat_line(ln["text"], chat_norm):
                    ln["speaker"], how = "読み上げ", "チャット一致"
                else:
                    s, e = float(ln["start"]), float(ln["end"])
                    if e - s < 0.6:
                        mid = (s + e) / 2
                        s, e = mid - 0.3, mid + 0.3
                    x = audio[max(0, int((s - a0) * SR)):max(0, int((e - a0) * SR))]
                    f0 = f0_median(x) if len(x) else 0.0
                    if 0 < f0 < low_hz:
                        ln["speaker"], how, conf = role["low"], "低い声", 0.9
                    elif len(x) >= 0.3 * SR:
                        v = _embed(ex, x)
                        d = float(v @ refs["low"] - v @ refs["high"])
                        conf = 0.5 + min(0.45, abs(d) * 4)
                        if abs(d) >= margin:
                            ln["speaker"], how = role["low" if d > 0 else "high"], "声の特徴"
                            if d > 0 and f0 > 230:      # a low-voice fingerprint at a high pitch (a scream?)
                                conf -= 0.15
                        else:
                            ln["speaker"], how = role["high" if f0 >= 200 else "low"], "僅差→声の高さ"
                    else:
                        ln["speaker"], how, conf = role["high"], "短すぎ", 0.4
            ln["speaker_conf"], ln["_how"] = round(conf, 2), how
        _smooth_by_turns(subs)
    for c in clips:
        for ln in c.get("subs") or []:
            if is_note(ln["text"]) or "speaker_conf" not in ln:
                continue
            how = ln.pop("_how", "")
            r = report.setdefault(ln.get("speaker", "?"), {"lines": 0, "examples": [], "how": {}})
            r["lines"] += 1
            r["how"][how] = r["how"].get(how, 0) + 1
            if len(r["examples"]) < 5:
                r["examples"].append(ln["text"].replace("\n", ""))
            if ln["speaker_conf"] < REVIEW_BELOW:
                report.setdefault("_review", []).append(
                    {"clip": c["id"], "at": ln["start"], "text": ln["text"].replace("\n", ""),
                     "speaker": ln["speaker"], "conf": ln["speaker_conf"]})
    return report


REVIEW_BELOW = 0.6   # lines under this confidence are listed for a human check


def _smooth_by_turns(subs, gap=2.5):
    """An unsure line between two sure lines of the same speaker (close in time) is that speaker:
    people rarely interject a single line inside the other's run."""
    for i, ln in enumerate(subs):
        if ln.get("_forced") or ln.get("speaker") == "読み上げ" or ln.get("speaker_conf", 1) >= 0.6:
            continue
        prev = next((p for p in reversed(subs[:i]) if p.get("speaker") != "読み上げ"), None)
        nxt = next((q for q in subs[i + 1:] if q.get("speaker") != "読み上げ"), None)
        if not prev or not nxt or prev.get("speaker_conf", 0) < 0.75 or nxt.get("speaker_conf", 0) < 0.75:
            continue
        if prev["speaker"] == nxt["speaker"] and ln["start"] - prev["end"] <= gap and nxt["start"] - ln["end"] <= gap:
            ln["speaker"], ln["speaker_conf"], ln["_how"] = prev["speaker"], 0.6, "前後の流れ"
