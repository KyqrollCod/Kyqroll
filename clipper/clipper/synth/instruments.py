"""instruments.py — procedural instruments (one function per sound).

Each function returns a float64 stereo array (2, n) starting at the note onset
(sample 0 = onset, first sample is a zero-crossing or faded-in, last samples faded).
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy import signal

from .dsp import (SR, adsr, convolve_reverb, fades, filt, make_ir, mtof, pan_gains, phase_from_freq,
                 rng, saw, smoothstep, sos, square, tv_biquad, tvec, to_stereo, undb)

TAU = 2.0 * np.pi


@lru_cache(maxsize=None)
def ir_cached(name):
    if name == "snare_room":
        return make_ir(rt60=1.05, seed=31, predelay=0.008, hf_ratio=0.5, lowcut=250, highcut=9000)
    if name == "clap_room":
        return make_ir(rt60=0.38, seed=32, predelay=0.004, hf_ratio=0.6, lowcut=300, highcut=10000, er_taps=6)
    if name == "big":
        return make_ir(rt60=4.2, seed=33, predelay=0.02, hf_ratio=0.4, lowcut=90, highcut=9000, er_taps=0)
    if name == "impact_tail":
        return make_ir(rt60=3.2, seed=34, predelay=0.01, hf_ratio=0.35, lowcut=60, highcut=7000, er_taps=0)
    raise KeyError(name)


def conv_short(x, ir):
    """Full (non-truncated) convolution of a short stereo/mono signal with a stereo IR, mono-in."""
    mono = x.mean(axis=0) if x.ndim == 2 else x
    return np.stack([signal.fftconvolve(mono, ir[c]) for c in range(2)])


def pad_to(x, n):
    if x.shape[-1] >= n:
        return x[..., :n]
    return np.concatenate([x, np.zeros(x.shape[:-1] + (n - x.shape[-1],))], axis=-1)


# ─── drums ────────────────────────────────────────────────────────────────
def kick(vel=1.0, seed=0, f_start=160.0, f_end=48.0, tau=0.032, length=0.30, click=1.0, drive=1.6):
    n = int(length * SR)
    t = tvec(n)
    f = f_end + (f_start - f_end) * np.exp(-t / tau) + 260.0 * np.exp(-t / 0.0035)
    body = np.sin(TAU * phase_from_freq(f))
    amp = np.where(t < 0.04, 1.0, np.exp(-(t - 0.04) / 0.095))
    r = rng(seed)
    nz = sos(r.standard_normal(n), 2, 2500, 'highpass')
    clk = (0.55 * nz * np.exp(-t / 0.0016) + 0.35 * np.sin(TAU * 1300 * t) * np.exp(-t / 0.004)) * click
    y = body * amp + clk
    y = np.tanh(drive * y) / np.tanh(drive)
    y = fades(y, 0.0, 0.03)
    return to_stereo(y * vel)


def softkick(vel=1.0, seed=0):
    """Low-passed 'heartbeat' kick for the intro."""
    n = int(0.42 * SR)
    t = tvec(n)
    f = 44.0 + (115.0 - 44.0) * np.exp(-t / 0.045)
    body = np.sin(TAU * phase_from_freq(f))
    amp = np.clip(t / 0.003, 0, 1) * np.where(t < 0.03, 1.0, np.exp(-(t - 0.03) / 0.16))
    y = np.tanh(1.2 * body * amp) / np.tanh(1.2)
    y = filt(y, 'lp', 230.0, 0.7)
    y = fades(y, 0.0, 0.05)
    return to_stereo(y * vel)


def clap(vel=1.0, seed=0, room=0.32):
    n = int(0.42 * SR)
    t = tvec(n)
    r = rng(seed)
    base = r.standard_normal(n)
    nL = 0.75 * base + 0.66 * r.standard_normal(n)
    nR = 0.75 * base + 0.66 * r.standard_normal(n)
    offs = np.array([0.0, 0.0102, 0.0201, 0.0311]) + r.uniform(-0.0006, 0.0006, 4) * np.array([0, 1, 1, 1])
    env = np.zeros(n)
    for i, o in enumerate(offs[:3]):
        d = t - o
        env += np.where(d >= 0, np.clip(d / 0.0004, 0, 1) * np.exp(-np.maximum(d, 0) / 0.0038), 0.0) * (0.75 + 0.1 * i)
    d = t - offs[3]
    env += np.where(d >= 0, np.clip(d / 0.0004, 0, 1) * np.exp(-np.maximum(d, 0) / 0.085), 0.0)
    y = np.stack([nL, nR]) * env
    y = filt(y, 'bp', 1250.0, 0.9) * 2.2
    y = filt(y, 'hp', 450.0, 0.7)
    y = filt(y, 'peak', 3200.0, 1.2, 3.0)
    if room > 0:
        wet = conv_short(y, ir_cached("clap_room"))[:, :n]
        y = y + room * wet * 3.0
    y = fades(y, 0.0, 0.06)
    return y * vel / (np.max(np.abs(y)) + 1e-9) * 0.9


def snare(vel=1.0, seed=0, big=True, tone=190.0, pitch_st=0.0):
    """Drop snare (big=True: body + noise + layered clap + big room) or roll snare (dry, short)."""
    length = 0.5 if big else 0.2
    n = int(length * SR)
    t = tvec(n)
    r = rng(seed)
    ft = tone * 2 ** (pitch_st / 12.0)
    f = ft * (1.0 + 0.32 * np.exp(-t / 0.008))
    ph = phase_from_freq(f)
    body = np.sin(TAU * ph) + 0.45 * np.sin(TAU * 1.53 * ph + 0.7)
    body *= np.clip(t / 0.0008, 0, 1) * np.exp(-t / (0.06 if big else 0.035))
    nz = np.stack([r.standard_normal(n), r.standard_normal(n)])
    nz = filt(nz, 'hp', 1600.0, 0.7)
    nz = filt(nz, 'peak', 5200.0, 0.9, 4.0)
    nenv = np.clip(t / 0.0006, 0, 1) * np.exp(-t / (0.15 if big else 0.06))
    y = 0.95 * body[None, :] + 0.8 * nz * nenv
    y = np.tanh(1.3 * y) / np.tanh(1.3)
    if big:
        y = y + 0.55 * pad_to(clap(1.0, seed + 7, room=0.0), n)
        wet = conv_short(y, ir_cached("snare_room"))
        tail = int(1.3 * SR)
        y = pad_to(y, tail) + 0.42 * pad_to(wet, tail)
    y = fades(y, 0.0, 0.05 if big else 0.02)
    return y * vel / (np.max(np.abs(y)) + 1e-9) * 0.95


_HAT_F = np.array([205.3, 304.4, 369.6, 522.7, 540.0, 800.0]) * 1.85


def hat(vel=1.0, seed=0, open_=False, pan=0.0):
    length = 0.34 if open_ else 0.065
    n = int(length * SR)
    t = tvec(n)
    r = rng(seed)
    metal = np.zeros(n)
    for fi in _HAT_F:
        metal += square(phase_from_freq(np.full(n, fi), r.uniform()), fi / SR)
    metal = filt(filt(metal / 6.0, 'bp', 8200.0, 0.9), 'hp', 6500.0, 0.7)
    nz = filt(r.standard_normal(n), 'hp', 7200.0, 0.7)
    y = 0.6 * metal + 0.7 * nz
    tau = 0.085 if open_ else 0.012
    env = np.clip(t / 0.0004, 0, 1) * np.exp(-t / tau)
    y = fades(y * env, 0.0, 0.03 if open_ else 0.008)
    y = y / (np.max(np.abs(y)) + 1e-9)
    return to_stereo(y, pan) * vel


def crash(vel=1.0, seed=0, length=2.3):
    n = int(length * SR)
    t = tvec(n)
    r = rng(seed)
    fr = np.array([293.7, 427.3, 596.8, 823.1, 1150.2, 1523.6]) * r.uniform(0.98, 1.02, 6)
    sq = [square(phase_from_freq(np.full(n, f), r.uniform()), f / SR) for f in fr]
    metal = sq[0] * sq[1] + sq[2] * sq[3] + sq[4] * sq[5]
    nz = np.stack([r.standard_normal(n), r.standard_normal(n)])
    y = 0.35 * metal[None, :] / 3.0 + nz
    y = filt(y, 'hp', 3800.0, 0.7)
    y = filt(y, 'peak', 8500.0, 0.8, 3.0)
    y = filt(y, 'lp', 15000.0, 0.7)
    env = np.clip(t / 0.0012, 0, 1) * (0.72 * np.exp(-t / 0.62) + 0.28 * np.exp(-t / 0.09))
    y = fades(y * env, 0.0, 0.25)
    return y * vel / (np.max(np.abs(y)) + 1e-9)


def reverse_cymbal(length_s, vel=1.0, seed=0):
    c = crash(1.0, seed, length=max(2.3, length_s + 0.2))
    rev = c[:, ::-1]
    n = int(round(length_s * SR))
    y = rev[:, -n:].copy()
    t = np.linspace(0, 1, n)
    y *= t ** 1.2  # extra swell shaping
    y = fades(y, 0.02, 0.003)
    return y * vel / (np.max(np.abs(y)) + 1e-9)


# ─── tonal instruments ────────────────────────────────────────────────────
_SS_CENTS = np.array([-24.6, -17.9, -11.2, -4.7, 0.0, 5.3, 11.9, 18.4, 25.1])
_SS_PAN = np.array([-0.95, 0.75, -0.5, 0.3, 0.0, -0.28, 0.55, -0.78, 1.0])
_SS_AMP = np.array([0.7, 0.75, 0.8, 0.88, 1.0, 0.88, 0.8, 0.75, 0.7])


def supersaw(notes, gate_s, vel=1.0, seed=0, width=0.9, scoop_st=-2.0, scoop_s=0.04,
             attack=0.002, decay=0.2, sustain=0.78, release=0.06, fc_peak=10000.0, fc_sus=3800.0,
             fc_tau=0.11, q=0.85, wobble_rate=0.0, wobble_depth=0.0, fc_curve=None, amp_curve=None,
             detune=1.0, drive=1.25, sub_oct=0.0):
    """Band-limited 9-voice supersaw chord with pitch scoop, LP filter envelope, stereo spread."""
    n = int(round((gate_s + release) * SR))
    t = tvec(n)
    r = rng(seed)
    pitch = np.zeros(n)
    if scoop_st:
        pitch = scoop_st * (1.0 - np.clip(t / scoop_s, 0, 1)) ** 2
    gl, gr = pan_gains(_SS_PAN * width)
    L = np.zeros(n)
    R = np.zeros(n)
    notes = list(notes)
    for m in notes:
        semis = m + (_SS_CENTS * detune / 100.0)[:, None] + pitch[None, :]
        f = mtof(semis)
        ph = phase_from_freq(f, r.uniform(0, 1, len(_SS_CENTS)))
        s = saw(ph, f / SR) * _SS_AMP[:, None]
        L += (s * gl[:, None]).sum(axis=0)
        R += (s * gr[:, None]).sum(axis=0)
    if sub_oct > 0:
        fs = mtof(min(notes) - 12 + pitch)
        sub = np.sin(TAU * phase_from_freq(fs)) * sub_oct * 3.0
        L += sub
        R += sub
    y = np.stack([L, R]) / (np.sqrt(len(notes) * len(_SS_CENTS)) * 1.6)
    if fc_curve is not None:
        fc = np.asarray(fc_curve, dtype=float)
        fc = fc[:n] if fc.size >= n else np.pad(fc, (0, n - fc.size), mode='edge')
    else:
        fc = fc_sus + (fc_peak - fc_sus) * np.exp(-t / fc_tau)
    y = tv_biquad(y, 'lp', fc, q, block=64)
    y = filt(y, 'hp', 110.0, 0.7)
    env = adsr(gate_s, attack, decay, sustain, release, n_total=n)
    if amp_curve is not None:
        ac = np.asarray(amp_curve, dtype=float)
        ac = ac[:n] if ac.size >= n else np.pad(ac, (0, n - ac.size), mode='edge')
        env = env * ac
    if wobble_rate > 0 and wobble_depth > 0:
        env *= 1.0 - wobble_depth * (0.5 - 0.5 * np.cos(TAU * wobble_rate * t))
    y = y * env
    y = np.tanh(drive * y) / np.tanh(drive)
    return fades(y, 0.0005, 0.004) * vel


def pluck(midi, gate_s, vel=1.0, seed=0, bright=1.0, tail=0.35):
    """Bright pluck: 2 detuned saws → fast LP envelope."""
    n = int(round((gate_s + tail) * SR))
    t = tvec(n)
    r = rng(seed)
    f0 = float(mtof(midi))
    out = []
    for c, cents in enumerate((-6.0, 6.5)):
        f = f0 * 2 ** (cents / 1200.0)
        s = saw(phase_from_freq(np.full(n, f), r.uniform()), f / SR)
        s += 0.35 * (square(phase_from_freq(np.full(n, f * 2), r.uniform()), 2 * f / SR, 0.3) + 0.4)  # DC-free pulse
        out.append(s)
    y = np.stack(out) * 0.6
    fc = 450.0 + 7500.0 * bright * np.exp(-t / 0.055)
    y = tv_biquad(y, 'lp', fc, 1.1, block=64)
    env = np.clip(t / 0.001, 0, 1) * np.exp(-t / 0.26)
    rel = np.ones(n)
    g = int(gate_s * SR)
    rel[g:] = np.exp(-(np.arange(n - g)) / (0.09 * SR))
    y = y * env * rel
    return fades(y, 0.0, 0.01) * vel


def pluck_bass(midi, gate_s, vel=1.0, seed=0):
    n = int(round((gate_s + 0.07) * SR))
    t = tvec(n)
    r = rng(seed)
    f0 = float(mtof(midi))
    s = np.zeros(n)
    for cents in (-5.0, 5.0):
        f = f0 * 2 ** (cents / 1200.0)
        s += saw(phase_from_freq(np.full(n, f), r.uniform()), f / SR)
    s *= 0.5
    s = tv_biquad(s, 'lp', 260.0 + 3200.0 * np.exp(-t / 0.045), 1.2, block=64)
    sub = np.sin(TAU * f0 * t)
    env = adsr(gate_s, 0.0015, 0.1, 0.55, 0.06, n_total=n)
    y = (0.8 * s + 0.75 * sub) * env
    y = np.tanh(1.4 * y) / np.tanh(1.4)
    return to_stereo(fades(y, 0.0, 0.006)) * vel


def bell(midi, gate_s, vel=1.0, seed=0, ratio=3.5, index=2.8, ring=1.5, bright=1.0, width=0.35):
    """2-operator FM bell + sine octave + glass partial; index envelope; L/R micro-detune."""
    n = int(round((gate_s + ring) * SR))
    t = tvec(n)
    r = rng(seed)
    f = float(mtof(midi))
    i_max = max(0.15, (19000.0 - f) / (ratio * f) - 1.0)
    i0 = min(index * bright, i_max)
    i1 = min(0.3, i0)
    I = i1 + (i0 - i1) * np.exp(-t / 0.16)
    out = []
    for c, cents in enumerate((-2.5 * width, 2.5 * width)):
        fc = f * 2 ** (cents / 1200.0)
        p0 = r.uniform()
        mod = np.sin(TAU * (ratio * fc * t + p0))
        car = np.sin(TAU * fc * t + I * mod)
        octv = 0.32 * np.sin(TAU * 2.0 * fc * t) * np.exp(-t / 0.32)
        glass = 0.0
        if 5.4 * fc < 18000:
            glass = 0.1 * bright * np.sin(TAU * 5.4 * fc * t) * np.exp(-t / 0.07)
        out.append(car + octv + glass)
    y = np.stack(out)
    env = np.clip(t / 0.0015, 0, 1) * np.exp(-t / 0.6)
    g = int(gate_s * SR) + int(0.12 * SR)
    rel = np.ones(n)
    rel[g:] = np.exp(-np.arange(n - g) / (0.3 * SR))
    y = y * env * rel
    return fades(y, 0.0, 0.03) * vel * 0.8


def chip(midi, gate_s, vel=1.0, seed=0, pw=0.25, vib_cents=14.0, vib_rate=5.6):
    """Kawaii chiptune double for the hook: band-limited 25 % pulse (DC-free), delayed vibrato,
    gentle LP — sits under the FM bell to give the melody body and a 'game' sparkle."""
    rel = 0.06
    n = int(round((gate_s + rel) * SR))
    t = tvec(n)
    r = rng(seed)
    vib = vib_cents / 100.0 * smoothstep(0.07, 0.16, t) * np.sin(TAU * vib_rate * t + r.uniform(0, TAU))
    f = mtof(midi + vib)
    y = square(phase_from_freq(f, r.uniform()), f / SR, pw) + (1.0 - 2.0 * pw)
    y = filt(y, 'lp', 5200.0, 0.7)
    env = adsr(gate_s, 0.003, 0.14, 0.55, rel, n_total=n)
    return to_stereo(fades(y * env, 0.0005, 0.004)) * vel * 0.5


def pad_chord(notes, gate_s, vel=1.0, seed=0, attack=0.9, release=0.9):
    n = int(round((gate_s + release) * SR))
    t = tvec(n)
    r = rng(seed)
    L = np.zeros(n)
    R = np.zeros(n)
    cents = np.array([-8.5, 0.0, 7.8])
    pans = np.array([-0.7, 0.1, 0.65])
    gl, gr = pan_gains(pans)
    for m in notes:
        f = mtof(m + cents / 100.0)[:, None] * np.ones((1, n))
        # slow drift (chorus-like)
        f = f * (1.0 + 0.0009 * np.sin(TAU * (0.21 + 0.07 * np.arange(3))[:, None] * t[None, :] + r.uniform(0, TAU, (3, 1))))
        s = saw(phase_from_freq(f, r.uniform(0, 1, 3)), f / SR)
        L += (s * gl[:, None]).sum(0)
        R += (s * gr[:, None]).sum(0)
    y = np.stack([L, R]) / np.sqrt(3 * len(notes))
    a = np.clip(t / attack, 0, 1)
    a = 0.5 - 0.5 * np.cos(np.pi * a)
    g = int(gate_s * SR)
    rel = np.ones(n)
    rel[g:] = 0.5 + 0.5 * np.cos(np.pi * np.clip(np.arange(n - g) / (release * SR), 0, 1))
    return y * a * rel * vel


def bass808(events, n_total):
    """Continuous 808 track (phase-continuous, glides). events: dicts with
    start, gate (samples), midi, vel, [glideTo, glideTime]."""
    freq = np.full(n_total, 40.0)
    amp = np.zeros(n_total)
    evs = sorted(events, key=lambda e: e["start"])
    prev_m, prev_end, prev_lvl = None, -10 ** 9, 0.0
    rel = int(0.045 * SR)
    for i, e in enumerate(evs):
        s0 = e["start"]
        nxt = evs[i + 1]["start"] if i + 1 < len(evs) else n_total
        gate_end = s0 + e["gate"]
        seg_end = min(nxt, gate_end + rel, n_total)
        idx = np.arange(s0, seg_end)
        tt = (idx - s0) / SR
        m_t = float(e["midi"])
        legato = prev_m is not None and s0 <= prev_end + 8
        if "glideTo" in e:
            gt = e.get("glideTime", 1.1)
            m = m_t + (e["glideTo"] - m_t) * smoothstep(0.05, gt, tt)
        elif legato:
            m = m_t + (prev_m - m_t) * np.exp(-tt / 0.02)
        else:
            m = m_t + 1.2 * np.exp(-tt / 0.012)
        freq[idx] = mtof(m)
        v = e["vel"]
        body = v * (0.78 + 0.22 * np.exp(-tt / 0.25)) * np.exp(-tt / (2.2 if "glideTo" not in e else 0.9))
        if legato:
            a = np.clip(tt / 0.006, 0, 1)
            env = prev_lvl * (1 - a) + body * a
        else:
            env = body * np.clip(tt / 0.003, 0, 1)
        k = idx - gate_end
        env = np.where(k > 0, env * np.clip(1 - k / rel, 0, 1) ** 2, env)
        if seg_end == nxt and nxt < n_total and seg_end < gate_end + rel:
            pass  # next note continues from this level
        amp[idx] = env
        prev_m = float(m[-1])
        prev_end = seg_end
        prev_lvl = float(env[-1])
    ph = phase_from_freq(freq)
    y = np.sin(TAU * ph) + 0.16 * np.sin(2 * TAU * ph + 0.4) + 0.05 * np.sin(3 * TAU * ph)
    y = y * amp
    drive = 1.9
    y = np.tanh(drive * y) / np.tanh(drive)
    y = signal.lfilter(*_lp_coeffs(3500.0), y)
    return to_stereo(y)


def _lp_coeffs(fc):
    from dsp import rbj
    return rbj('lp', fc, 0.7)


# ─── FX ───────────────────────────────────────────────────────────────────
def noise_riser(length_s, seed=0, f0=300.0, f1=8000.0, db0=-32.0, pitch=(50, 74), pitch_db=-8.0, q=2.2):
    n = int(round(length_s * SR))
    t = tvec(n)
    u = t / length_s
    r = rng(seed)
    nz = np.stack([r.standard_normal(n), r.standard_normal(n)])
    fc = f0 * (f1 / f0) ** (u ** 1.25)
    y = tv_biquad(nz, 'bp', fc, q, block=128) * 1.8
    y += 0.25 * tv_biquad(nz, 'hp', fc * 1.5, 0.7, block=128) * u ** 2
    y *= undb(db0 * (1 - u) ** 1.4)
    if pitch is not None:
        m = pitch[0] + (pitch[1] - pitch[0]) * u ** 1.7
        ss = np.zeros((2, n))
        gl, gr = pan_gains(np.array([-0.8, 0.0, 0.8]))
        for k, c in enumerate((-14.0, 0.0, 14.0)):
            for octv in (0, 12):
                f = mtof(m + octv + c / 100.0)
                s = saw(phase_from_freq(f, r.uniform()), f / SR) * (1.0 if octv == 0 else 0.5)
                ss[0] += s * gl[k]
                ss[1] += s * gr[k]
        ss = tv_biquad(ss, 'lp', 800.0 + 9000.0 * u ** 2, 0.9, block=128) / 3.0
        ss *= undb(pitch_db + -26.0 * (1 - u) ** 1.2)
        y = y + ss
    return fades(y, 0.05, 0.003)


def downlifter(length_s, seed=0):
    n = int(round(length_s * SR))
    t = tvec(n)
    u = t / length_s
    r = rng(seed)
    nz = np.stack([r.standard_normal(n), r.standard_normal(n)])
    fc = 9000.0 * (250.0 / 9000.0) ** (u ** 0.7)
    y = tv_biquad(nz, 'bp', fc, 1.6, block=128) * 1.6
    y *= np.exp(-u * 3.2)
    return fades(y, 0.004, 0.1)


def impact(vel=1.0, size=1.0, seed=0, boom_tau=None, boom_gain=1.0):
    length = 2.2 + 1.2 * size
    n = int(length * SR)
    t = tvec(n)
    r = rng(seed)
    f = 30.0 + 22.0 * np.exp(-t / 0.28) + 60.0 * np.exp(-t / 0.012)
    ph = phase_from_freq(f)
    boom = (np.sin(TAU * ph) + 0.18 * np.sin(2 * TAU * ph)) * np.clip(t / 0.002, 0, 1) * np.exp(-t / (boom_tau or 0.55 * size))
    boom = np.tanh(1.6 * boom) / np.tanh(1.6)
    nz = np.stack([r.standard_normal(n), r.standard_normal(n)])
    burst = tv_biquad(nz, 'lp', 300.0 + 9000.0 * np.exp(-t / 0.07), 0.7, block=128) * np.exp(-t / 0.11)
    burst *= np.clip(t / 0.0008, 0, 1)
    tail_src = burst[:, : int(0.35 * SR)]
    tail = conv_short(tail_src, ir_cached("impact_tail"))
    tail = pad_to(tail, n)
    rest = 0.42 * burst + (0.5 + 0.25 * size) * tail * 0.8
    norm = np.max(np.abs(boom[None, :] + rest)) + 1e-9      # level set by the full-boom version
    y = fades(boom_gain * boom[None, :] + rest, 0.0, 0.4)
    return y * vel / norm


def tick(midi, vel=1.0, seed=0):
    n = int(0.16 * SR)
    t = tvec(n)
    f = float(mtof(midi))
    y = np.sin(TAU * f * t + 1.4 * np.exp(-t / 0.012) * np.sin(TAU * 2.0 * f * t))
    y += 0.3 * np.sin(TAU * 2 * f * t) * np.exp(-t / 0.02)
    y *= np.clip(t / 0.0006, 0, 1) * np.exp(-t / 0.045)
    r = rng(seed)
    y += 0.25 * filt(r.standard_normal(n), 'hp', 6000.0) * np.exp(-t / 0.0015)
    return to_stereo(fades(y, 0.0, 0.02)) * vel


def shimmer(seed=0):
    """t=0 'star ignites' — bell cluster (Gmaj9 upper tones) strummed up, through a huge
    reverb, plus an octave-up copy of the reverb (pitch-shifted by 2× resampling)."""
    notes = [86, 90, 93, 95, 98, 102]
    n = int(3.2 * SR)
    dry = np.zeros((2, n))
    for k, m in enumerate(notes):
        s = int((0.024 * k + 0.004 * k * k) * SR)
        b = bell(m, 0.3, 0.8 - 0.06 * k, seed + k, index=1.6, ring=1.6, bright=0.8, width=1.0)
        L = min(b.shape[1], n - s)
        dry[:, s:s + L] += b[:, :L]
    wet = conv_short(dry, ir_cached("big"))[:, :n]
    up = signal.resample_poly(wet, 1, 2, axis=-1)
    oct_ = pad_to(up, n)
    y = 0.55 * dry + 1.1 * wet + 0.35 * oct_
    t = tvec(n)
    y *= np.clip(1.0 - (t - 2.4) / 0.8, 0, 1) ** 2
    return fades(y, 0.0, 0.05)


def reverse_swell(src, length_s, ir):
    """Reverse reverb: reverse(src) → reverb → reverse; returns the `length_s` swell that
    ends exactly where src begins."""
    rev = src[:, ::-1]
    wet = conv_short(rev, ir)
    sw = wet[:, ::-1]
    # in `sw`, the original onset sits at index len(sw) - len(src) ... the swell precedes it
    onset = sw.shape[1] - src.shape[1]
    n = int(round(length_s * SR))
    seg = sw[:, max(0, onset - n): onset]
    seg = pad_to(seg[:, ::-1], n)[:, ::-1]
    return fades(seg, 0.03, 0.002)
