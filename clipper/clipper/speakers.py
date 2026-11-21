"""Who is speaking each telop line: 読み上げ (chat TTS), 男性, 女性.

Evidence first, in this order:
  1. 読み上げ: the line is a chat message (the TTS bot reads chat verbatim)
  2. pitch (F0) when it is unambiguous: < low Hz 男性, > high Hz 女性
  3. otherwise the nearer voice by speaker embedding (wespeaker ResNet34 via sherpa-onnx),
     against centroids of the lines settled by 2
A script line can force its speaker: "@男性:テキスト". The model file lives in
clipper/models/ (see README); without it, labeling is skipped.
"""
import difflib
import os
import re
import subprocess

import numpy as np

from .common import ROOT, need

MODEL = os.path.join(ROOT, "models", "wespeaker_en_voxceleb_resnet34.onnx")
_NORM = re.compile(r"[\s、。,.!！?？…「」『』（）()・~〜ーwｗ]")


def _norm(t):
    t = _NORM.sub("", str(t))
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in t)


def _pcm(src, start, end):
    p = subprocess.run([need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}",
                        "-t", f"{end - start:.3f}", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                       stdout=subprocess.PIPE, check=True)
    return np.frombuffer(p.stdout, dtype=np.float32)


def f0_median(x, sr=16000):
    """Median pitch of voiced 40 ms frames by autocorrelation (70-400 Hz); 0 if unvoiced."""
    n, hop = int(0.04 * sr), int(0.02 * sr)
    lo, hi = int(sr / 400), int(sr / 70)
    if len(x) < n:
        return 0.0
    rms = np.sqrt(np.mean(x ** 2)) + 1e-9
    out = []
    for i in range(0, len(x) - n, hop):
        f = x[i:i + n] - np.mean(x[i:i + n])
        if np.sqrt(np.mean(f ** 2)) < rms * 0.6:
            continue
        ac = np.correlate(f, f, "full")[n - 1:]
        if ac[0] <= 0:
            continue
        seg = ac[lo:hi]
        k = int(np.argmax(seg)) + lo
        if ac[k] / ac[0] > 0.45:
            out.append(sr / k)
    return float(np.median(out)) if out else 0.0


def label_clips(src, clips, chat=None, low=165.0, high=230.0, min_len=0.5):
    """Set ln['speaker'] on every non-note subtitle line of `clips` (source time). Returns a
    report: {name: {'lines': n, 'f0': median, 'examples': [...]}}. Lines inside one clip are
    decoded from a single audio read."""
    import sherpa_onnx
    from .subs import is_note
    if not os.path.exists(MODEL):
        print(f"  speakers: モデルがありません（{MODEL}）。話者の色分けは行いません")
        return {}
    cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=MODEL, num_threads=4, provider="cpu")
    ex = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
    items = []  # (clip, line, embedding, f0)
    for c in clips:
        subs = [ln for ln in (c.get("subs") or []) if not is_note(ln["text"])]
        if not subs:
            continue
        a0, a1 = float(c["start"]), float(c["end"])
        audio = _pcm(src, a0, a1)
        for ln in subs:
            s, e = float(ln["start"]), float(ln["end"])
            if e - s < min_len:  # very short lines: widen a little for a usable embedding
                mid = (s + e) / 2
                s, e = mid - min_len / 2, mid + min_len / 2
            seg = audio[max(0, int((s - a0) * 16000)):max(0, int((e - a0) * 16000))]
            if len(seg) < 16000 * 0.3:
                continue
            st = ex.create_stream()
            st.accept_waveform(16000, seg)
            st.input_finished()
            v = np.array(ex.compute(st), dtype=np.float32)
            items.append((c, ln, v / (np.linalg.norm(v) + 1e-9), f0_median(seg)))
    if not items:
        return {}
    # 1) Chat read aloud: the line IS a chat message (not a longer line that quotes one,
    #    like 「〜って言われた」, which is the streamer).
    chat_n = [_norm(m.get("text", "")) for m in (chat or []) if len(_norm(m.get("text", ""))) >= 4]

    def is_tts(text):
        t = _norm(text)
        return len(t) >= 4 and any(len(t) <= len(m) * 1.25 and difflib.SequenceMatcher(None, t, m).ratio() >= 0.7
                                   for m in chat_n)

    # 2) Pitch where it is unambiguous; 3) otherwise the nearer voice, from confident lines.
    # Embeddings alone did not separate the voices under game audio (all pairs 0.6-0.9 cosine),
    # pitch did (partner 110-180 Hz, streamer 200-380 Hz), so pitch leads and embeddings break ties.
    label = {}
    for i, (c, ln, v, f0) in enumerate(items):
        if ln.get("speaker"):
            label[i] = ln["speaker"]          # set by hand in the script (@名前:)
        elif is_tts(ln["text"]):
            label[i] = "読み上げ"
        elif 0 < f0 < low:
            label[i] = "男性"
        elif f0 > high:
            label[i] = "女性"
    cent = {}
    for name in ("男性", "女性"):
        vs = [items[i][2] for i, n in label.items() if n == name]
        if len(vs) >= 3:
            m = np.mean(vs, axis=0)
            cent[name] = m / (np.linalg.norm(m) + 1e-9)
    for i, (c, ln, v, f0) in enumerate(items):
        if i not in label:
            label[i] = max(cent, key=lambda n: float(v @ cent[n])) if cent else "女性"
    report = {}
    for i, (c, ln, v, f0) in enumerate(items):
        ln["speaker"] = label[i]
        r = report.setdefault(label[i], {"lines": 0, "f0": [], "examples": []})
        r["lines"] += 1
        if f0 > 0:
            r["f0"].append(f0)
        if len(r["examples"]) < 6:
            r["examples"].append(ln["text"].replace("\n", ""))
    for r in report.values():
        r["f0"] = round(float(np.median(r["f0"])), 1) if r["f0"] else 0.0
    return report
