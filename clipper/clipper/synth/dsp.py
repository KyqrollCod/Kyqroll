"""dsp.py — low-level DSP primitives for the STARLIGHT soundtrack.

Everything is vectorised numpy/scipy. Conventions:
  * sample rate SR = 48 kHz, stereo signals are float64 arrays of shape (2, n)
  * time-varying filters are processed block-wise (coefficients updated per block,
    filter state carried across blocks) — no per-sample Python loops over the track.
"""
from __future__ import annotations

import numpy as np
from scipy import signal
from scipy.ndimage import minimum_filter1d

SR = 48000
BPM = 160
SPB = 60.0 / BPM            # 0.375 s per beat
SPBEAT = 18000              # samples per beat
N_TOTAL = 1_440_000         # 30.000 s
FRAME = 800                 # samples per video frame (60 fps)


# ─── units ────────────────────────────────────────────────────────────────
def b2s(beat: float) -> int:
    """beat → sample index (exact: beats are multiples of 1/8 → integers)."""
    return int(round(beat * SPBEAT))


def b2t(beat: float) -> float:
    return beat * SPB


def mtof(m):
    return 440.0 * 2.0 ** ((np.asarray(m, dtype=float) - 69.0) / 12.0)


def db(x):
    return 20.0 * np.log10(np.maximum(np.abs(x), 1e-12))


def undb(d):
    return 10.0 ** (np.asarray(d, dtype=float) / 20.0)


def rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def tvec(n: int) -> np.ndarray:
    return np.arange(n) / SR


def pan_gains(p):
    """Equal-power pan; p in [-1, 1] → (gL, gR)."""
    a = (np.asarray(p, dtype=float) + 1.0) * (np.pi / 4.0)
    return np.cos(a), np.sin(a)


def to_stereo(x, pan=0.0):
    gl, gr = pan_gains(pan)
    return np.stack([x * gl, x * gr]) * np.sqrt(2.0)  # centre = unity per channel


def smoothstep(e0, e1, x):
    k = np.clip((np.asarray(x, dtype=float) - e0) / (e1 - e0), 0.0, 1.0)
    return k * k * (3.0 - 2.0 * k)


# ─── oscillators ──────────────────────────────────────────────────────────
def phase_from_freq(freq, phase0=0.0):
    """Cumulative phase (cycles) of a frequency curve. freq (..., n) Hz. Sample 0 has phase0."""
    inc = np.asarray(freq, dtype=float) / SR
    ph = np.cumsum(inc, axis=-1) - inc
    p0 = np.asarray(phase0, dtype=float)
    if p0.ndim:
        p0 = p0.reshape(p0.shape + (1,) * (ph.ndim - p0.ndim))
    return ph + p0


def _blep(p, dt):
    out = np.zeros_like(p)
    m = p < dt
    if m.any():
        x = p[m] / dt[m]
        out[m] = x + x - x * x - 1.0
    m = p > 1.0 - dt
    if m.any():
        x = (p[m] - 1.0) / dt[m]
        out[m] = x * x + x + x + 1.0
    return out


def saw(phase, dt):
    """Band-limited (PolyBLEP) sawtooth. phase in cycles (unwrapped ok), dt = f/SR."""
    p = np.mod(phase, 1.0)
    dt = np.broadcast_to(np.minimum(np.asarray(dt, dtype=float), 0.49), p.shape)
    return 2.0 * p - 1.0 - _blep(p, dt)


def square(phase, dt, pw=0.5):
    p = np.mod(phase, 1.0)
    dt = np.broadcast_to(np.minimum(np.asarray(dt, dtype=float), 0.49), p.shape)
    s = np.where(p < pw, 1.0, -1.0)
    return s + _blep(p, dt) - _blep(np.mod(p + 1.0 - pw, 1.0), dt)


# ─── envelopes ────────────────────────────────────────────────────────────
def adsr(gate_s, a=0.002, d=0.2, s=0.7, r=0.05, n_total=None, a_curve=1.0, r_curve=2.0):
    """Gate-length ADSR. Attack linear^a_curve, exponential decay to sustain,
    release = (1-x)^r_curve fade after the gate. Length = gate + release (or n_total)."""
    ng = max(1, int(round(gate_s * SR)))
    nr = max(1, int(round(r * SR)))
    n = n_total if n_total is not None else ng + nr
    t = tvec(n)
    att = np.clip(t / a, 0.0, 1.0) ** a_curve if a > 0 else np.ones(n)
    dec = s + (1.0 - s) * np.exp(-np.maximum(t - a, 0.0) / max(d, 1e-4))
    rel = np.ones(n)
    k = np.arange(n) - ng
    m = k >= 0
    rel[m] = np.clip(1.0 - k[m] / nr, 0.0, 1.0) ** r_curve
    return att * dec * rel


def fades(x, fin=0.001, fout=0.004):
    """Apply short raised-cosine fades at both ends (in place-safe copy)."""
    x = np.array(x, dtype=float, copy=True)
    n = x.shape[-1]
    ni = min(n // 2, max(1, int(fin * SR)))
    no = min(n // 2, max(1, int(fout * SR)))
    wi = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, ni))
    wo = 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, no))
    x[..., :ni] *= wi
    x[..., n - no:] *= wo
    return x


# ─── filters ──────────────────────────────────────────────────────────────
def rbj(kind: str, f0: float, q: float = 0.7071, gain_db: float = 0.0):
    """RBJ cookbook biquad → (b, a) normalised."""
    f0 = float(np.clip(f0, 5.0, 0.49 * SR))
    w0 = 2.0 * np.pi * f0 / SR
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2.0 * q)
    A = 10.0 ** (gain_db / 40.0)
    if kind == 'lp':
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]; a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == 'hp':
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]; a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == 'bp':   # constant 0 dB peak gain
        b = [alpha, 0.0, -alpha]; a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == 'peak':
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]; a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind in ('lowshelf', 'highshelf'):
        sq = 2.0 * np.sqrt(A) * alpha
        if kind == 'lowshelf':
            b = [A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq)]
            a = [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq]
        else:
            b = [A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sq)]
            a = [(A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq]
    else:
        raise ValueError(kind)
    b = np.array(b) / a[0]
    a = np.array(a) / a[0]
    return b, a


def filt(x, kind, f0, q=0.7071, gain_db=0.0):
    b, a = rbj(kind, f0, q, gain_db)
    return signal.lfilter(b, a, x, axis=-1)


def butter_sos(order, fc, btype):
    return signal.butter(order, fc, btype=btype, fs=SR, output='sos')


def sos(x, order, fc, btype):
    return signal.sosfilt(butter_sos(order, fc, btype), x, axis=-1)


def tv_biquad(x, kind, fc, q=0.7071, block=64):
    """Time-varying biquad: coefficients updated every `block` samples (state carried).
    x: (n,) or (c, n); fc: scalar or (n,) cutoff curve (Hz); q scalar or (n,)."""
    x = np.asarray(x, dtype=float)
    one = x.ndim == 1
    X = x[None, :] if one else x
    n = X.shape[-1]
    fc = np.broadcast_to(np.asarray(fc, dtype=float), (n,))
    qq = np.broadcast_to(np.asarray(q, dtype=float), (n,))
    Y = np.empty_like(X)
    zi = np.zeros((X.shape[0], 2))
    for i in range(0, n, block):
        j = min(n, i + block)
        c = (i + j - 1) // 2
        b, a = rbj(kind, fc[c], qq[c])
        Y[:, i:j], zi = signal.lfilter(b, a, X[:, i:j], axis=-1, zi=zi)
    return Y[0] if one else Y


def onepole_lp(x, fc):
    a = np.exp(-2.0 * np.pi * fc / SR)
    return signal.lfilter([1 - a], [1, -a], x, axis=-1)


# ─── reverb & delay ───────────────────────────────────────────────────────
def make_ir(rt60=2.5, length=None, seed=1, predelay=0.012, hf_ratio=0.45, lf_ratio=1.15,
            lowcut=120.0, highcut=10000.0, fade_in=0.006, er_taps=10, er_level=0.35):
    """Synthetic decorrelated stereo IR: 3-band exponentially decaying noise (highs decay
    faster), band-limited, with sparse early reflections. Unit energy per channel."""
    length = length or min(rt60 * 1.25, 6.0)
    n = int(length * SR)
    t = tvec(n)
    r = rng(seed)
    out = []
    lo_s = butter_sos(2, 500, 'lowpass')
    hi_s = butter_sos(2, 3500, 'highpass')
    for ch in range(2):
        nz = r.standard_normal(n)
        lo = signal.sosfilt(lo_s, nz)
        hi = signal.sosfilt(hi_s, nz)
        mid = nz - lo - hi
        e = lambda rt: np.exp(-6.9078 * t / max(rt, 1e-3))
        ir = lo * e(rt60 * lf_ratio) + mid * e(rt60) + hi * e(rt60 * hf_ratio)
        ir *= np.clip(t / fade_in, 0, 1) ** 2
        # early reflections
        if er_taps:
            tt = np.sort(r.uniform(0.004, 0.065, er_taps))
            for k, tk in enumerate(tt):
                i = int(tk * SR)
                ir[i] += er_level * r.choice([-1, 1]) * (1.0 - 0.6 * k / er_taps) * np.sqrt(np.mean(ir[:int(0.08 * SR)] ** 2)) * 6
        ir = signal.sosfilt(butter_sos(2, lowcut, 'highpass'), ir)
        ir = signal.sosfilt(butter_sos(2, highcut, 'lowpass'), ir)
        pd = int(predelay * SR)
        ir = np.concatenate([np.zeros(pd), ir])[:n]
        ir /= np.sqrt(np.sum(ir ** 2)) + 1e-12
        out.append(ir)
    return np.stack(out)


def convolve_reverb(x, ir):
    """Mono-in (L+R)/2, stereo-out wet signal, same length as x."""
    mono = x.mean(axis=0) if x.ndim == 2 else x
    n = mono.shape[-1]
    nz = np.nonzero(np.abs(mono) > 1e-9)[0]
    wet = np.zeros((2, n))
    if nz.size == 0:
        return wet
    s0, s1 = nz[0], nz[-1] + 1
    seg = mono[s0:s1]
    for c in range(2):
        y = signal.fftconvolve(seg, ir[c])[: n - s0]
        wet[c, s0:s0 + y.size] = y
    return wet


def pingpong(x, delay_s, fb=0.42, taps=6, lp=6500.0, hp=300.0, first=1):
    """Ping-pong delay (wet only) as explicit filtered taps alternating R/L."""
    d = int(round(delay_s * SR))
    mono = x.mean(axis=0) if x.ndim == 2 else x
    n = mono.shape[-1]
    out = np.zeros((2, n))
    cur = mono
    bl, al = rbj('lp', lp, 0.6)
    bh, ah = rbj('hp', hp, 0.6)
    for k in range(1, taps + 1):
        cur = signal.lfilter(bl, al, cur)
        cur = signal.lfilter(bh, ah, cur)
        if k * d >= n:
            break
        ch = (first + k - 1) % 2
        out[ch, k * d:] += (fb ** (k - 1)) * cur[: n - k * d]
    return out


# ─── dynamics ─────────────────────────────────────────────────────────────
def compressor(x, thr_db=-14.0, ratio=2.0, attack=0.015, release=0.15, knee_db=6.0, makeup_db=0.0,
               key=None, block=16):
    """Stereo-linked RMS feed-forward compressor at control rate (block samples).
    Returns (y, gain_db_per_sample)."""
    k = x if key is None else key
    p = np.mean(k ** 2, axis=0)
    nb = int(np.ceil(p.size / block))
    pad = nb * block - p.size
    pb = np.pad(p, (0, pad)).reshape(nb, block).mean(axis=1)
    # RMS smoothing ~ 5 ms
    a_rms = np.exp(-block / (0.005 * SR))
    pb = signal.lfilter([1 - a_rms], [1, -a_rms], pb)
    lvl = 10 * np.log10(pb + 1e-12)
    # static curve with soft knee
    over = lvl - thr_db
    gr = np.zeros_like(lvl)
    hk = knee_db / 2
    m1 = over > hk
    gr[m1] = (1 / ratio - 1) * over[m1]
    m2 = (over > -hk) & ~m1
    gr[m2] = (1 / ratio - 1) * (over[m2] + hk) ** 2 / (2 * knee_db)
    # attack/release smoothing of gain reduction (dB) — loop at control rate
    aa = np.exp(-block / (attack * SR))
    ar_ = np.exp(-block / (release * SR))
    g = np.empty_like(gr)
    s = 0.0
    for i in range(gr.size):
        v = gr[i]
        s = aa * s + (1 - aa) * v if v < s else ar_ * s + (1 - ar_) * v
        g[i] = s
    gs = np.interp(np.arange(p.size), np.arange(nb) * block + block / 2, g)
    return x * undb(gs + makeup_db), gs


def oversampled(fn, x, factor=4):
    up = signal.resample_poly(x, factor, 1, axis=-1)
    y = fn(up)
    return signal.resample_poly(y, 1, factor, axis=-1)[..., : x.shape[-1]]


def softclip(x, knee=0.6, ceil=1.0):
    """Linear below `knee`, smooth tanh saturation towards `ceil` above (odd-symmetric)."""
    ax = np.abs(x)
    y = np.where(ax <= knee, ax, knee + (ceil - knee) * np.tanh((ax - knee) / (ceil - knee)))
    return np.sign(x) * y


def true_peak_curve(x, factor=4):
    """Per-sample true-peak estimate: max |4× oversampled| within ±1 sample, max over channels."""
    up = signal.resample_poly(x, factor, 1, axis=-1)
    n = x.shape[-1]
    a = np.abs(up[..., : n * factor]).reshape(x.shape[0], n, factor).max(axis=2).max(axis=0)
    a = np.maximum(a, np.maximum(np.roll(a, 1), np.roll(a, -1)))
    return np.maximum(a, np.abs(x).max(axis=0))


def true_peak_db(x, factor=4):
    up = signal.resample_poly(x, factor, 1, axis=-1)
    return float(db(np.max(np.abs(up))))


def limiter(x, ceiling_db=-1.2, lookahead=0.004, release=0.09, block=8):
    """Look-ahead brick-wall limiter with 4× oversampled peak detection.
    gain = smooth( release( min-window( ceiling / truepeak ) ) ), guaranteed ≤ required."""
    c = undb(ceiling_db)
    tp = true_peak_curve(x)
    g_req = np.minimum(1.0, c / np.maximum(tp, 1e-12))
    L = max(2, int(lookahead * SR))
    h = minimum_filter1d(g_req, size=2 * L + 1, mode='nearest')
    # release smoothing (control rate)
    nb = int(np.ceil(h.size / block))
    hb = np.pad(h, (0, nb * block - h.size), constant_values=1.0).reshape(nb, block).min(axis=1)
    rc = 1.0 - np.exp(-block / (release * SR))
    y = np.empty_like(hb)
    s = 1.0
    for i in range(nb):
        v = hb[i]
        s = v if v < s else s + (v - s) * rc
        y[i] = s
    yr = np.repeat(y, block)[: h.size]
    yr = np.minimum(yr, h)
    # box smoothing of length L (≤ h within radius L/2 → ≤ g_req)
    ker = np.ones(L) / L
    gs = np.convolve(np.pad(yr, (L, L), mode='edge'), ker, mode='same')[L:-L]   # edge-padded (no fade at t=0)
    gs = np.minimum(gs, 1.0)
    return x * gs, gs


# ─── loudness (ITU-R BS.1770-4) ───────────────────────────────────────────
_KB1 = [1.53512485958697, -2.69169618940638, 1.19839281085285]
_KA1 = [1.0, -1.69065929318241, 0.73248077421585]
_KB2 = [1.0, -2.0, 1.0]
_KA2 = [1.0, -1.99004745483398, 0.99007225036621]


def kweight(x):
    return signal.lfilter(_KB2, _KA2, signal.lfilter(_KB1, _KA1, x, axis=-1), axis=-1)


def _block_power(xk, win_s, hop_s):
    """Mean-square (summed over channels) of K-weighted signal in sliding windows.
    Returns (window_end_times, z)."""
    p = np.sum(xk ** 2, axis=0)
    cs = np.concatenate([[0.0], np.cumsum(p)])
    w = int(round(win_s * SR))
    h = int(round(hop_s * SR))
    ends = np.arange(w, p.size + 1, h)
    z = (cs[ends] - cs[ends - w]) / w
    return ends / SR, z


def _lufs(z):
    return -0.691 + 10.0 * np.log10(np.maximum(z, 1e-20))


def lufs_integrated(x, xk=None):
    xk = kweight(x) if xk is None else xk
    if xk.shape[-1] < int(0.4 * SR):
        return -np.inf
    _, z = _block_power(xk, 0.4, 0.1)
    l = _lufs(z)
    g = z[l > -70.0]
    if g.size == 0:
        return -np.inf
    rel = _lufs(np.mean(g)) - 10.0
    g2 = z[(l > -70.0) & (l > rel)]
    return float(_lufs(np.mean(g2))) if g2.size else -np.inf


def lufs_short_term(x, hop=0.05, xk=None):
    xk = kweight(x) if xk is None else xk
    t, z = _block_power(xk, 3.0, hop)
    return t, _lufs(z)


def lufs_momentary(x, hop=0.05, xk=None):
    xk = kweight(x) if xk is None else xk
    t, z = _block_power(xk, 0.4, hop)
    return t, _lufs(z)
