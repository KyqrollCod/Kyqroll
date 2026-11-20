"""Speech to word-timestamped transcript with faster-whisper (GPU if present)."""
import os
import subprocess

import numpy as np

from .common import need, save_json


def _pcm16k(src):
    """Decode with ffmpeg ourselves: avoids faster-whisper's PyAV decoder and its version clashes."""
    p = subprocess.run([need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", src, "-vn", "-ac", "1",
                        "-ar", "16000", "-f", "f32le", "-"], stdout=subprocess.PIPE, check=True)
    return np.frombuffer(p.stdout, dtype=np.float32)


def _cuda_dll_paths():
    """On Windows, pip's nvidia-cublas/cudnn wheels put DLLs where ctranslate2 can't see them."""
    if os.name != "nt":
        return
    import importlib.util
    for pkg in ("nvidia.cublas", "nvidia.cudnn"):
        spec = importlib.util.find_spec(pkg)
        if spec and spec.submodule_search_locations:
            for base in spec.submodule_search_locations:
                b = os.path.join(base, "bin")
                if os.path.isdir(b):
                    os.add_dll_directory(b)
                    os.environ["PATH"] = b + os.pathsep + os.environ.get("PATH", "")


def transcribe(wd, src, gl, model_name="large-v3", device="auto"):
    _cuda_dll_paths()
    from faster_whisper import WhisperModel

    audio = _pcm16k(src)
    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    compute = "float16" if device == "cuda" else "int8"
    model = WhisperModel(model_name, device=device, compute_type=compute)
    prompt = "、".join(gl.get("terms", [])[:80])
    segments, info = model.transcribe(
        audio, language="ja", word_timestamps=True, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300}, beam_size=5,
        condition_on_previous_text=False, initial_prompt=prompt or None,
        no_speech_threshold=0.6, compression_ratio_threshold=2.4)
    words, segs = [], []
    for s in segments:
        segs.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()})
        for w in s.words or []:
            if w.word.strip():
                words.append({"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word,
                              "p": round(w.probability, 3)})
    out = {"model": model_name, "device": device, "language": info.language, "segments": segs, "words": words}
    save_json(os.path.join(wd, "transcript.json"), out)
    return out
