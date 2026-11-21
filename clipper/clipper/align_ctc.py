"""Exact telop timing by CTC forced alignment of the proofread text against the voice-only audio.

Whisper word timestamps run early (up to 1-2 s after a pause), which made telops appear before
the line was spoken and spoil the punchline. Here each line's text is aligned, character by
character, inside a window around its estimated position with torchaudio's MMS forced aligner
(multilingual; Japanese is romanized with pykakasi). A '*' token at both ends absorbs other
speech in the window, so only the line itself is located.
"""
import re

import numpy as np

SR = 16000
_B = None
_KK = None


def _bundle():
    global _B
    if _B is None:
        import torch
        import torchaudio
        b = torchaudio.pipelines.MMS_FA
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        _B = (b, b.get_model(with_star=True).to(dev).eval(), b.get_tokenizer(), b.get_aligner(), dev)
    return _B


def romaji_words(text):
    """'おで、おまえ食べる' -> ['ode', 'omae', 'taberu'] (only a-z, MMS_FA's alphabet)."""
    global _KK
    if _KK is None:
        import pykakasi
        _KK = pykakasi.kakasi()
    out = []
    for item in _KK.convert(text):
        w = re.sub(r"[^a-z]", "", item.get("hepburn", "").lower())
        if w:
            out.append(w)
    return out


def ctc_starts(lines, audio, offset, clip_start, clip_end, min_score=0.2):
    """Forced-alignment (start, end) for each line, or None; lines are not modified."""
    from .subs import is_note
    out, prev_end = [], clip_start
    for ln in lines:
        if is_note(ln["text"]):
            out.append(None)
            continue
        s, e = float(ln["start"]), float(ln["end"])
        a, b = max(prev_end - 0.05, s - 2.0, clip_start), min(e + 2.5, clip_end)
        r = align_line(audio, offset, ln["text"].replace("\n", ""), a, b) if b > a else None
        if r and r[2] >= min_score and r[1] > r[0]:
            out.append((r[0], r[1], r[2]))
            prev_end = r[1]
        else:
            out.append(None)
    return out


def combine_timing(lines, est_w, est_c, speech, clip_start, clip_end, too_early=0.8, late_ok=0.3):
    """Final telop times from three estimates per line:
      W  Whisper word timing on the voice-only stem (best on clean speech, but a word after a pause
         can be stretched early, and near-silence can be hallucinated)
      C  CTC forced alignment of the proofread text (robust placement, but often 0.2-1 s late)
      O  the original estimate (mixed audio; often 1-3 s early)
    Rule: use W unless it is much earlier than C (then C); without W use C; without both keep O.
    Then never start in silence before the voice (snap to the next speech onset)."""
    from .subs import display_rules, is_note, snap_to_speech
    stats = []
    olds = [float(x["start"]) for x in lines]
    for i, (ln, w, c) in enumerate(zip(lines, est_w, est_c)):
        if is_note(ln["text"]):
            continue
        old, old_e = olds[i], float(ln["end"])
        # Where the NEXT line starts by its original estimate. A later estimate for this line
        # matched a later repeat of the phrase (or is CTC's late bias): it is not this line.
        nxt = next((olds[j] for j in range(i + 1, len(lines)) if not is_note(lines[j]["text"])), clip_end)
        if w is not None and not (old - 0.8 <= w[0] < nxt):
            w = None
        if c is not None and not (c[0] < nxt):
            c = None
        # Base: the original estimate (it passed the speech/telop qc). Move it only when another
        # method shows the line starts clearly LATER (an early telop spoils the punchline).
        src, s, e = "O", old, old_e
        if w is not None and w[0] - old > late_ok:
            src, s, e = "W", w[0], max(w[1], old_e)
        elif w is None and c is not None and c[0] - old > 0.5:
            # CTC runs 0.2-1 s late: keep a margin, never earlier than the original.
            src, s, e = "C", max(old, c[0] - 0.25), max(c[1], old_e)
        s = snap_to_speech(s, speech, max(s + 0.3, e - 0.2)) if speech else s
        ln["start"], ln["end"] = s, max(e, s + 0.3)
        # Still showing in silence > 0.7 s before anyone speaks (beyond the snap's reach): the
        # estimates disagree and a person should check it (an early telop can spoil the joke).
        early = 0.0
        if speech and not any(a - 0.05 <= s <= b for a, b in speech):
            nxt_on = next((a for a, _ in speech if a > s), None)
            early = round(nxt_on - s, 2) if nxt_on is not None else 0.0
        stats.append({"text": ln["text"].replace("\n", ""), "before": round(old, 2), "after": round(s, 2), "src": src,
                      "w": None if w is None else round(w[0], 2), "c": None if c is None else round(c[0], 2),
                      "early": early if early > 0.7 else 0.0})
    for i in range(1, len(lines)):
        if lines[i]["start"] < lines[i - 1]["start"]:
            lines[i]["start"] = lines[i - 1]["start"] + 0.05
    for i in range(len(lines) - 1):
        lines[i]["end"] = min(lines[i]["end"], lines[i + 1]["start"])
    display_rules(lines, clip_start, clip_end)
    return stats


def refine_lines(lines, audio, offset, clip_start, clip_end, min_score=0.2, max_shift=3.0):
    """Re-time every spoken line by forced alignment (windows ±2 s around the estimate, never
    before the previous line). Returns per-line stats: (text, old_start, new_start, score, used)."""
    from .subs import display_rules, is_note
    stats = []
    prev_end = clip_start
    for ln in lines:
        if is_note(ln["text"]):
            continue
        s, e = float(ln["start"]), float(ln["end"])
        a = max(prev_end - 0.05, s - 2.0, clip_start)
        b = min(e + 2.0, clip_end)
        r = align_line(audio, offset, ln["text"].replace("\n", ""), a, b) if b > a else None
        used = bool(r and r[2] >= min_score and abs(r[0] - s) <= max_shift and r[1] > r[0])
        if used:
            ln["start"], ln["end"] = r[0], max(r[1], r[0] + 0.3)
            prev_end = r[1]
        else:
            prev_end = max(prev_end, s)
        stats.append((ln["text"].replace("\n", ""), s, float(ln["start"]), r[2] if r else None, used))
    for i in range(1, len(lines)):           # keep chronological after re-timing
        if lines[i]["start"] < lines[i - 1]["start"]:
            lines[i]["start"] = lines[i - 1]["start"] + 0.05
    for i in range(len(lines) - 1):          # a line ends before the next begins
        lines[i]["end"] = min(lines[i]["end"], lines[i + 1]["start"])
    display_rules(lines, clip_start, clip_end)
    return stats


def align_line(audio, offset, text, a, b):
    """Locate `text` inside audio[a:b] (seconds, relative to `offset` = audio start time).
    Returns (start, end, score) in absolute seconds, or None."""
    import torch
    bundle, model, tok, aligner, dev = _bundle()
    words = romaji_words(text)
    if not words:
        return None
    i0, i1 = max(0, int((a - offset) * SR)), min(len(audio), int((b - offset) * SR))
    if i1 - i0 < int(0.3 * SR):
        return None
    wav = torch.from_numpy(np.ascontiguousarray(audio[i0:i1], dtype=np.float32))[None].to(dev)
    with torch.inference_mode():
        emission, _ = model(wav)
    # '*' (star) absorbs whatever else is said in the window, before and after the line.
    transcript = ["*"] + words + ["*"]
    try:
        spans = aligner(emission[0], tok(transcript))
    except Exception:
        return None
    ratio = (i1 - i0) / emission.shape[1] / SR
    core = spans[1:-1]
    if not core or not core[0] or not core[-1]:
        return None
    s = core[0][0].start * ratio
    e = core[-1][-1].end * ratio
    scores = [t.score for w in core for t in w]
    return offset + i0 / SR + s, offset + i0 / SR + e, float(np.mean(scores)) if scores else 0.0
