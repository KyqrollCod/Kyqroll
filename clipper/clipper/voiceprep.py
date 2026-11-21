"""Voice-only audio for analysis: Demucs (htdemucs) separates the speech from game sound, music and
effects. Speaker and timing analysis run on these stems, not on the mixed stream audio.

Stems are cached per clip window in <video>/cache/vocals_<start>_<end>.npy (16 kHz mono float16).
"""
import os
import subprocess

import numpy as np

from .common import need

SR = 16000
_MODEL = None


def _demucs():
    global _MODEL
    if _MODEL is None:
        import torch
        from demucs.pretrained import get_model
        m = get_model("htdemucs")
        m.eval()
        if torch.cuda.is_available():
            m.cuda()
        _MODEL = m
    return _MODEL


def _pcm(src, start, dur, sr, ch):
    p = subprocess.run([need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
                        "-i", src, "-vn", "-ac", str(ch), "-ar", str(sr), "-f", "f32le", "-"], stdout=subprocess.PIPE, check=True)
    return np.frombuffer(p.stdout, dtype=np.float32).reshape(-1, ch).T.copy()


_WHISPER = None


def vocal_words(wd, audio, start, end, prompt=None):
    """Word timestamps from Whisper large-v3 run on the voice-only stem (cached). With the game
    and music removed, word starts are much closer to when the words are actually spoken."""
    import json
    global _WHISPER
    path = os.path.join(wd, "cache", f"vwords_{start:.2f}_{end:.2f}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    from .transcribe import _cuda_dll_paths
    _cuda_dll_paths()
    from faster_whisper import WhisperModel
    if _WHISPER is None:
        import ctranslate2
        dev = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        _WHISPER = WhisperModel("large-v3", device=dev, compute_type="float16" if dev == "cuda" else "int8")
    segs, _ = _WHISPER.transcribe(audio, language="ja", word_timestamps=True, vad_filter=True,
                                  vad_parameters={"min_silence_duration_ms": 200}, beam_size=5,
                                  condition_on_previous_text=False, initial_prompt=prompt)
    words = [{"start": round(start + w.start, 3), "end": round(start + w.end, 3), "word": w.word}
             for s in segs for w in (s.words or []) if w.word.strip()]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(words, fh, ensure_ascii=False)
    return words


def speech_on(audio, start):
    """Speech regions (absolute seconds) in a voice-only stem."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    opts = VadOptions(threshold=0.45, min_speech_duration_ms=120, min_silence_duration_ms=120, speech_pad_ms=20)
    return [(start + s["start"] / SR, start + s["end"] / SR) for s in get_speech_timestamps(audio, opts)]


def vocals(wd, src, start, end):
    """16 kHz mono speech-only audio for [start, end] of the source (cached)."""
    cdir = os.path.join(wd, "cache")
    os.makedirs(cdir, exist_ok=True)
    path = os.path.join(cdir, f"vocals_{start:.2f}_{end:.2f}.npy")
    if os.path.exists(path):
        return np.load(path).astype(np.float32)
    import torch
    from demucs.apply import apply_model
    model = _demucs()
    x = _pcm(src, start, end - start, model.samplerate, 2)
    wav = torch.from_numpy(x)
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    with torch.no_grad():
        out = apply_model(model, wav[None].to(dev), device=dev, split=True, overlap=0.25, progress=False)[0]
    v = out[model.sources.index("vocals")].cpu().numpy() * (ref.std().item() + 1e-8)
    v = v.mean(0)
    # resample 44.1k -> 16k
    import torchaudio.functional as AF
    v16 = AF.resample(torch.from_numpy(v), model.samplerate, SR).numpy()
    np.save(path, v16.astype(np.float16))
    return v16.astype(np.float32)
