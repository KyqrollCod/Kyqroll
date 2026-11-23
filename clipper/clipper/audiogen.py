"""Original BGM loops and sound effects, synthesized in code.

No third-party audio is used, so there is nothing to license or credit. Files are generated on
first use into clipper/assets/bgm/ and clipper/assets/se/ (both outside git):

  BGM (seamless loops):  comical (bouncy major, 112 BPM)  /  tension (dark minor, 92 BPM)
  SE:  pop (emphasis), whoosh (zoom), impact (payoff / game over), ding (chat read aloud),
       boing (comic beat), sparkle (hook)
"""
import os
import wave

import numpy as np

from .common import ROOT
from .synth import dsp as D
from .synth import instruments as I

SR = D.SR
BGM_DIR = os.path.join(ROOT, "assets", "bgm")
SE_DIR = os.path.join(ROOT, "assets", "se")
SE_NAMES = ("pop", "whoosh", "impact", "ding", "boing", "sparkle")
BGM_NAMES = ("comical", "tension")


def _write(path, x):
    x = np.clip(np.asarray(x, dtype=np.float64), -1, 1)
    pcm = (x.T * 32767).astype("<i2")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def _place(buf, x, t, gain=1.0):
    i = int(round(t * SR))
    if i >= buf.shape[1]:
        return
    n = min(x.shape[1], buf.shape[1] - i)
    buf[:, i:i + n] += gain * x[:, :n]


def _norm(x, lufs):
    cur = D.lufs_integrated(x)
    if np.isfinite(cur):
        x = x * D.undb(lufs - cur)
    y, _ = D.limiter(x, ceiling_db=-1.5)
    return y


# --- sound effects -------------------------------------------------------------------------

def _sine_glide(f0, f1, dur, curve=2.0):
    n = int(dur * SR)
    t = np.linspace(0, 1, n)
    f = f0 + (f1 - f0) * t ** curve
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph)


def se_pop():
    n = int(0.12 * SR)
    env = np.exp(-np.linspace(0, 1, n) * 9)
    x = _sine_glide(520, 1250, 0.12, 0.6) * env
    x = np.vstack([x, x]) * 0.9
    x[:, :int(0.004 * SR)] *= np.linspace(0, 1, int(0.004 * SR))
    return x + 0.25 * I.pad_to(I.tick(96), x.shape[1])


def se_whoosh():
    x = I.noise_riser(0.38, seed=3, f0=500, f1=6500, db0=-30, pitch=(60, 72), pitch_db=-20)
    n = x.shape[1]
    env = np.sin(np.linspace(0, np.pi, n)) ** 1.5
    return x * env * 0.55


def se_impact():
    x = I.impact(vel=1.0, size=0.9, seed=2)
    return x[:, :int(1.4 * SR)] * np.linspace(1, 0, int(1.4 * SR)) ** 0.5


def se_ding():
    a = I.bell(88, 0.5, vel=0.9, seed=1)
    b = I.bell(95, 0.5, vel=0.7, seed=2)
    out = np.zeros((2, int(1.1 * SR)))
    _place(out, a, 0.0)
    _place(out, b, 0.09)
    return out * 0.6


def se_boing():
    n = int(0.45 * SR)
    t = np.linspace(0, 1, n)
    f = 180 + 260 * np.exp(-t * 4) + 25 * np.sin(2 * np.pi * 14 * t * (1 - t))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 3.2)
    return np.vstack([x, x]) * 0.8


def se_sparkle():
    out = np.zeros((2, int(0.9 * SR)))
    for k, m in enumerate((84, 88, 91, 96)):
        _place(out, I.chip(m, 0.07, vel=0.6, seed=k), 0.05 * k)
        _place(out, I.bell(m + 12, 0.2, vel=0.25, seed=k), 0.05 * k)
    return out * 0.7


# --- BGM loops -------------------------------------------------------------------------------

def _loop(bars, bpm, render):
    """Render `bars` bars plus a tail, then fold the tail onto the start: a seamless loop."""
    beat = 60.0 / bpm
    n = int(round(bars * 4 * beat * SR))
    buf = np.zeros((2, n + int(4 * SR)))
    render(buf, beat)
    loop = buf[:, :n].copy()
    loop[:, :buf.shape[1] - n] += buf[:, n:]
    return loop


def bgm_comical(seed=0):
    prog = [(60, 64, 67), (57, 60, 64), (53, 57, 60), (55, 59, 62)]   # C Am F G
    motif = [72, 74, 76, 79, 76, 74, 72, None, 74, 76, 79, 81, 79, 76, 74, None]

    def render(buf, b):
        for bar in range(16):
            ch = prog[bar % 4]
            t0 = bar * 4 * b
            for k in range(8):                                   # pluck arpeggio, 8ths
                m = ch[(0, 1, 2, 1)[k % 4]] + (12 if k >= 4 else 0)
                _place(buf, I.pluck(m, b * 0.45, vel=0.55, seed=bar * 8 + k, bright=0.8), t0 + k * b / 2, 0.55)
            for k, m in enumerate((ch[0] - 24, ch[2] - 24, ch[0] - 12, ch[2] - 24)):   # bouncy bass
                _place(buf, I.pluck_bass(m, b * 0.7, vel=0.8, seed=bar * 4 + k), t0 + k * b, 0.6)
            for k in (0, 2):
                _place(buf, I.softkick(vel=0.8, seed=bar + k), t0 + k * b, 0.7)
            for k in (1, 3):
                _place(buf, I.clap(vel=0.45, seed=bar + k), t0 + k * b, 0.35)
            for k in range(8):
                _place(buf, I.hat(vel=0.35 if k % 2 else 0.22, seed=bar * 8 + k), t0 + k * b / 2, 0.3)
            if bar % 8 >= 4:                                     # chip melody on every other phrase
                for k, m in enumerate(motif[(bar % 2) * 8:(bar % 2) * 8 + 8]):
                    if m:
                        _place(buf, I.chip(m, b * 0.4, vel=0.45, seed=bar * 8 + k), t0 + k * b / 2, 0.35)

    x = _loop(16, 112, render)
    x, _ = D.compressor(x, thr_db=-18, ratio=2.5)
    return _norm(x, -16.0)


def bgm_tension(seed=0):
    prog = [(57, 60, 64), (53, 57, 60), (50, 53, 57), (52, 56, 59)]   # Am F Dm E

    def render(buf, b):
        for bar in range(16):
            ch = prog[bar % 4]
            t0 = bar * 4 * b
            _place(buf, I.pad_chord([m - 12 for m in ch], 4 * b, vel=0.5, seed=bar, attack=0.6, release=1.2), t0, 0.35)
            for k in range(4):
                _place(buf, I.pluck(ch[k % 3] - 12, b * 0.25, vel=0.5, seed=bar * 4 + k, bright=0.5), t0 + k * b, 0.45)
            _place(buf, I.softkick(vel=0.9, seed=bar), t0, 0.7)
            _place(buf, I.softkick(vel=0.6, seed=bar + 50), t0 + 2.5 * b, 0.5)
            for k in range(16):
                _place(buf, I.tick(100 if k % 4 == 0 else 96, vel=0.25, seed=bar * 16 + k), t0 + k * b / 4, 0.12)
            if bar % 4 == 3:
                _place(buf, I.bell(ch[2] + 12, b * 2, vel=0.35, seed=bar), t0 + 2 * b, 0.3)

    x = _loop(16, 92, render)
    x, _ = D.compressor(x, thr_db=-20, ratio=2.0)
    return _norm(x, -18.0)


_SE = {"pop": se_pop, "whoosh": se_whoosh, "impact": se_impact, "ding": se_ding, "boing": se_boing,
       "sparkle": se_sparkle}
_BGM = {"comical": bgm_comical, "tension": bgm_tension}


def se_catalog():
    """The SE list kept with the work folders (<work_root>/_素材/SE/効果音リスト.yaml): {key: sound}."""
    from .common import default_work_root, load_yaml
    p = os.path.join(default_work_root(), "_素材", "SE", "効果音リスト.yaml")
    if not os.path.exists(p):
        return {}
    return {s["key"]: s for s in (load_yaml(p) or {}).get("sounds") or [] if s.get("key")}


# Built-in fallbacks per category when the SE list is missing.
_SE_FALLBACK = {"pop": "pop", "whoosh": "whoosh", "impact": "impact", "read": "ding", "fail": "boing",
                "tsukkomi": "boing", "success": "sparkle", "surprise": "impact", "shock": "boing"}
# Mix level per category (the list's files are peak-normalized to -4 dBFS; SE stay under the voice).
SE_LEVEL = {"pop": 0.28, "whoosh": 0.28, "impact": 0.38, "tsukkomi": 0.38, "fail": 0.38, "shock": 0.36,
            "success": 0.36, "surprise": 0.36, "horror": 0.32, "read": 0.24, "bleep": 0.55}


def se_variants(cat):
    return sorted(k for k, s in se_catalog().items() if s.get("cat") == cat)


def se_pick(cat, seed):
    """A sound of the category, rotating with `seed` so repeated cues don't all sound the same."""
    keys = se_variants(cat)
    if keys:
        return se_path(keys[seed % len(keys)])
    return se_path(_SE_FALLBACK.get(cat, "pop"))


def se_path(name):
    if name not in _SE:
        s = se_catalog().get(name)
        if s:
            return s["file"]
        if name in _SE_FALLBACK or name in SE_LEVEL:
            return se_pick(name, 0)
        raise ValueError(f"効果音「{name}」がありません（効果音リスト.yaml の key かカテゴリを指定）")
    p = os.path.join(SE_DIR, f"{name}.wav")
    if not os.path.exists(p):
        _write(p, _norm(_SE[name](), -18.0))
    return p


def music_catalog():
    """The music list kept with the work folders (<work_root>/_素材/BGM/曲リスト.yaml): {key: song}."""
    from .common import default_work_root, load_yaml
    p = os.path.join(default_work_root(), "_素材", "BGM", "曲リスト.yaml")
    if not os.path.exists(p):
        return {}
    songs = (load_yaml(p) or {}).get("songs") or []
    return {s["key"]: s for s in songs if s.get("key")}


def bgm_path(name):
    """A built-in BGM (comical, tension) or a song key from the music list."""
    if name not in _BGM:
        song = music_catalog().get(name)
        if song:
            return song["file"]
        raise ValueError(f"BGM「{name}」がありません（comical / tension か、曲リスト.yaml の key を指定）")
    p = os.path.join(BGM_DIR, f"{name}.wav")
    if not os.path.exists(p):
        _write(p, _BGM[name]())
    return p


def make_all(force=False):
    out = []
    for n in SE_NAMES:
        p = os.path.join(SE_DIR, f"{n}.wav")
        if force and os.path.exists(p):
            os.remove(p)
        out.append(se_path(n))
    for n in BGM_NAMES:
        p = os.path.join(BGM_DIR, f"{n}.wav")
        if force and os.path.exists(p):
            os.remove(p)
        out.append(bgm_path(n))
    return out
