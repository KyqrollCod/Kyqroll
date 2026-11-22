"""Where the source already has music (the game's own BGM, lobby/result-screen music, a jingle).

Our BGM must never play over another song (owner, 2026-11-22: two songs at once is a no). An
AudioSet classifier (AST, BSD-3) tags 1 s hops of the source audio; spans where "Music" is
likely become `music_spans`, and render mutes our BGM there with short fades.
Cached per window in cache/music_<start>_<end>.json."""
import json
import os
import subprocess

import numpy as np

from .common import need

MODEL = "MIT/ast-finetuned-audioset-10-10-0.4593"
SR = 16000
WIN, HOP = 2.0, 1.0
THRESH = 0.35       # P(Music) on a 2 s window; game SFX + speech stay well below
MIN_LEN = 1.5       # ignore music blips shorter than this
_M = {}


def _model():
    if "m" not in _M:
        import torch
        from transformers import ASTFeatureExtractor, ASTForAudioClassification
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        fe = ASTFeatureExtractor.from_pretrained(MODEL)
        m = ASTForAudioClassification.from_pretrained(MODEL).to(dev).eval()
        idx = [i for lbl, i in m.config.label2id.items() if lbl in ("Music", "Video game music", "Background music",
                                                                    "Theme music", "Soundtrack music")]
        _M["m"] = (fe, m, dev, idx)
    return _M["m"]


def _audio(src, start, end):
    p = subprocess.run([need("ffmpeg"), "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", src,
                        "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True)
    return np.frombuffer(p.stdout, np.float32)


def music_prob(src, start, end):
    """[(t_source, p_music)] every HOP seconds."""
    import torch
    fe, m, dev, idx = _model()
    x = _audio(src, start, end)
    n = int(WIN * SR)
    starts = list(range(0, max(1, len(x) - n + 1), int(HOP * SR)))
    out = []
    for b in range(0, len(starts), 16):
        chunk = [x[s:s + n] if len(x[s:s + n]) == n else np.pad(x[s:s + n], (0, n - len(x[s:s + n])))
                 for s in starts[b:b + 16]]
        feats = fe(chunk, sampling_rate=SR, return_tensors="pt")["input_values"].to(dev)
        with torch.no_grad():
            pr = torch.sigmoid(m(feats).logits)[:, idx].max(dim=1).values.cpu().numpy()
        out += [(start + s / SR + WIN / 2, float(p)) for s, p in zip(starts[b:b + 16], pr)]
    return out


def music_spans(wd, src, start, end):
    """Source-time spans [a, b] where music is already playing."""
    cache = os.path.join(wd, "cache", f"music_{start:.1f}_{end:.1f}.json")
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as fh:
            return json.load(fh)["spans"]
    from .common import gpu_lock
    with gpu_lock("ゲーム内の曲の検出"):
        probs = music_prob(src, start, end)
    spans, cur = [], None
    for t, p in probs:
        if p >= THRESH:
            cur = [t - HOP / 2, t + HOP / 2] if cur is None else [cur[0], t + HOP / 2]
        elif cur is not None:
            spans.append(cur)
            cur = None
    if cur is not None:
        spans.append(cur)
    spans = [[round(a, 2), round(b, 2)] for a, b in spans if b - a >= MIN_LEN]
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump({"spans": spans, "probs": [[round(t, 2), round(p, 3)] for t, p in probs]}, fh)
    return spans
