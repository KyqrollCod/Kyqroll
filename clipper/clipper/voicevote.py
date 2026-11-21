"""Speaker labels by combining independent methods on voice-only audio (Demucs stems).

Votes per line (each gives P(male)):
  1. gender classifier  wav2vec2 audio classifier (see GENDER_MODEL; license checked: Apache-2.0)
  2. pitch              WORLD Harvest median F0, mapped through a logistic around 165 Hz
  3. voiceprint         wespeaker embedding vs this video's reference voices, which are built only
                        from lines where 1 and 2 agree strongly (so a scream cannot seed them)
Combined in log-odds. Lines where two methods disagree strongly, or the result is close to 50/50,
go to the review list. Chat text match (TTS reading chat) and "@名前:" override everything.
Roles come from the package's speaker_gender ({配信者: female, 相手: male}); for a same-gender
collab the voiceprint vote decides between the two reference voices.
"""
import math

import numpy as np

SR = 16000
# Two independent classifiers (both Apache-2.0, checked on Hugging Face 2026-11-21): one trained on
# English read speech (LibriSpeech), one on multilingual crowd recordings (Common Voice).
GENDER_MODELS = ("alefiury/wav2vec2-large-xlsr-53-gender-recognition-librispeech",
                 "prithivMLmods/Common-Voice-Gender-Detection")
_GM = {}


def _gender_model(name):
    if name not in _GM:
        import torch
        from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
        fe = AutoFeatureExtractor.from_pretrained(name)
        m = AutoModelForAudioClassification.from_pretrained(name).eval()
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        m.to(dev)
        labels = {str(v).lower(): int(k) for k, v in m.config.id2label.items()}
        _GM[name] = (fe, m, dev, labels)
    return _GM[name]


def p_male_classifier(x, name):
    import torch
    fe, m, dev, labels = _gender_model(name)
    if len(x) < int(0.4 * SR):
        return None
    inp = fe(x, sampling_rate=SR, return_tensors="pt", padding=True)
    with torch.inference_mode():
        logits = m(**{k: v.to(dev) for k, v in inp.items()}).logits[0]
    pr = torch.softmax(logits, -1).cpu().numpy()
    mi = next((i for lab, i in labels.items() if lab in ("male", "m") or lab.startswith("male")), None)
    return float(pr[mi]) if mi is not None else None


def f0_harvest(x):
    import pyworld
    if len(x) < int(0.25 * SR):
        return 0.0
    f0, _ = pyworld.harvest(x.astype(np.float64), SR, f0_floor=70.0, f0_ceil=500.0, frame_period=10.0)
    v = f0[f0 > 0]
    return float(np.median(v)) if len(v) >= 5 else 0.0


def p_male_pitch(f0, mid=165.0, width=18.0):
    if f0 <= 0:
        return None
    return 1.0 / (1.0 + math.exp((f0 - mid) / width))


def _logit(p):
    p = min(max(p, 0.02), 0.98)
    return math.log(p / (1 - p))


def label(lines, segs, embed, chat_line, roles_gender, weights=(1.0, 0.8, 1.0)):
    """lines: subtitle dicts; segs: matching voice-only arrays (or None); embed: fn(x)->unit vector;
    chat_line: fn(text)->bool; roles_gender: {"配信者": "female", "相手": "male"}.
    Sets speaker, speaker_conf and returns per-line vote details."""
    det = []
    for ln, x in zip(lines, segs):
        d = {"text": ln["text"].replace("\n", ""), "start": ln["start"]}
        if ln.get("_forced"):
            d["final"] = ln["speaker"]
            d["how"] = "手動"
        elif chat_line(ln["text"]):
            ln["speaker"], d["final"], d["how"] = "読み上げ", "読み上げ", "チャット一致"
        elif x is None or len(x) < int(0.3 * SR):
            d["how"] = "音声なし"
        else:
            ps = [p_male_classifier(x, n) for n in GENDER_MODELS]
            d["p_cls_each"] = ps
            ps = [p for p in ps if p is not None]
            d["p_cls"] = float(np.mean(ps)) if ps else None
            d["f0"] = f0_harvest(x)
            d["p_pitch"] = p_male_pitch(d["f0"])
            d["emb"] = embed(x)
        det.append(d)
    # Reference voices only from lines where BOTH classifiers agree strongly (timbre, not pitch:
    # a yelling man reaches 250-300 Hz and would seed the wrong voice).
    def both(d, hi):
        e = [p for p in (d.get("p_cls_each") or []) if p is not None]
        return len(e) == 2 and (all(p > 0.85 for p in e) if hi else all(p < 0.15 for p in e))
    male = [d["emb"] for d in det if d.get("emb") is not None and both(d, True)]
    female = [d["emb"] for d in det if d.get("emb") is not None and both(d, False)]
    cm = (np.mean(male, 0) / np.linalg.norm(np.mean(male, 0))) if len(male) >= 3 else None
    cf = (np.mean(female, 0) / np.linalg.norm(np.mean(female, 0))) if len(female) >= 3 else None
    g2role = {g: r for r, g in roles_gender.items()}
    w_cls, w_pitch, w_emb = weights
    for ln, d in zip(lines, det):
        if "final" in d:
            ln["speaker_conf"] = 1.0
            continue
        if d.get("emb") is not None and cm is not None and cf is not None:
            diff = float(d["emb"] @ cm - d["emb"] @ cf)
            d["p_emb"] = 1.0 / (1.0 + math.exp(-diff * 20))
        each = (d.get("p_cls_each") or []) + [None, None]
        a_, b_ = each[0], each[1]
        others = [p_ for p_ in (d.get("p_pitch"), d.get("p_emb")) if p_ is not None]
        if a_ is not None and b_ is not None and ((a_ > 0.85 and b_ > 0.85) or (a_ < 0.15 and b_ < 0.15)):
            # Both timbre classifiers agree: decisive. Pitch fails on screams (and octave errors),
            # so it cannot overturn them; a contradiction from BOTH other methods is still flagged.
            p = (a_ + b_) / 2
            male = p >= 0.5
            clash = bool(others) and all((o < 0.2) if male else (o > 0.8) for o in others) and len(others) == 2
            how = "分類器2つが一致"
        else:
            votes = [(w_cls, a_), (w_cls * 0.5, b_), (w_pitch * 0.6, d.get("p_pitch")), (w_emb * 0.8, d.get("p_emb"))]
            votes = [(w, p_) for w, p_ in votes if p_ is not None]
            if not votes:
                ln.setdefault("speaker", g2role.get("female", "配信者"))
                ln["speaker_conf"], d["final"], d["how"] = 0.3, ln["speaker"], "判定不能"
                continue
            z = sum(w * _logit(p_) for w, p_ in votes) / sum(w for w, _ in votes)
            p = 1.0 / (1.0 + math.exp(-z))
            core = [p_ for p_ in (a_, d.get("p_pitch"), d.get("p_emb")) if p_ is not None]
            clash = any(x > 0.8 for x in core) and any(x < 0.2 for x in core)
            how = "重み付き多数決"
        gender = "male" if p >= 0.5 else "female"
        conf = abs(p - 0.5) * 2 * (0.5 if clash else 1.0)
        ln["speaker"] = g2role.get(gender, "配信者")
        ln["speaker_conf"] = round(conf, 2)
        d.update(p=round(p, 3), final=ln["speaker"], how=how + ("（他の手法と食い違い）" if clash else ""), clash=clash)
    return det
