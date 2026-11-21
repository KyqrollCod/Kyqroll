"""Speech to word-timestamped transcript with faster-whisper (GPU if present)."""
import os
import re
import subprocess

import numpy as np

from .common import need, save_json


def _pcm16k(src):
    """Decode with ffmpeg ourselves: avoids faster-whisper's PyAV decoder and its version clashes."""
    p = subprocess.run([need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", src, "-vn", "-ac", "1",
                        "-ar", "16000", "-f", "f32le", "-"], stdout=subprocess.PIPE, check=True)
    return np.frombuffer(p.stdout, dtype=np.float32)


def speech_spans(src, start, end):
    """Where someone is actually talking in [start, end] (source seconds), from Silero VAD on the
    audio itself. Telop starts are snapped to these: Whisper's word starts run early."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    p = subprocess.run([need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}",
                        "-t", f"{end - start:.3f}", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                       stdout=subprocess.PIPE, check=True)
    audio = np.frombuffer(p.stdout, dtype=np.float32)
    opts = VadOptions(threshold=0.5, min_speech_duration_ms=120, min_silence_duration_ms=120, speech_pad_ms=20)
    return [(start + s["start"] / 16000, start + s["end"] / 16000) for s in get_speech_timestamps(audio, opts)]


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


def transcribe(wd, src, gl, model_name="large-v3", device="auto", prompt=None, batch_size=None):
    """prompt: Whisper initial prompt; defaults to the glossary terms. Pass the stream's own names
    and game terms for a non-mahjong stream so the mahjong list does not bias recognition.
    batch_size: >1 uses BatchedInferencePipeline (several times faster on a GPU); default 16 on CUDA."""
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
    if prompt is None:
        prompt = "、".join(gl.get("terms", [])[:80])
    if batch_size is None:
        batch_size = 16 if device == "cuda" else 1
    common = dict(language="ja", word_timestamps=True, beam_size=5, initial_prompt=prompt or None,
                  no_speech_threshold=0.6, compression_ratio_threshold=2.4)
    if batch_size > 1:
        from faster_whisper import BatchedInferencePipeline
        segments, info = BatchedInferencePipeline(model=model).transcribe(
            audio, batch_size=batch_size, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300}, **common)
    else:
        segments, info = model.transcribe(
            audio, vad_filter=True, vad_parameters={"min_silence_duration_ms": 300},
            condition_on_previous_text=False, **common)
    total = len(audio) / 16000
    words, segs = [], []
    last_report = 0.0
    for s in segments:
        if s.end - last_report >= 600:
            last_report = s.end
            print(f"  transcribe {s.end / 60:.0f}/{total / 60:.0f} min", flush=True)
        segs.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()})
        for w in s.words or []:
            if w.word.strip():
                words.append({"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word,
                              "p": round(w.probability, 3)})
    segs, words, dropped = clean_transcript(segs, words, prompt)
    if dropped:
        print(f"  removed {dropped} hallucinated words (repetition loops / prompt echo)")
    out = {"model": model_name, "device": device, "language": info.language, "segments": segs, "words": words}
    save_json(os.path.join(wd, "transcript.json"), out)
    return out


_PUNCT = re.compile(r"[\s、。,.!！?？・…ー〜~]")
_LOOP = re.compile(r"(\D{2,16}?)\1{4,}")  # never digits: 100000 must stay 100000


def _norm(t):
    return _PUNCT.sub("", t)


def collapse_loops(words, keep=4, max_unit=12):
    """Whisper (especially batched, which cannot condition on previous text) sometimes loops on a
    phrase for tens of seconds ("きたきたきた…" x200). A streamer may really say a phrase a few times,
    so keep the first `keep` repeats of any 1..max_unit-word unit and drop the rest of the run.
    Japanese tokens are short (終/わ/った/か/もし/ん/ない is one 7-token phrase), hence max_unit 12."""
    keys = [_norm(w["word"]) for w in words]
    out, i, n = [], 0, len(words)
    while i < n:
        best = None
        for k in range(1, max_unit + 1):
            unit = keys[i:i + k]
            if len(unit) < k or not "".join(unit):
                break
            r = 1
            while keys[i + r * k:i + (r + 1) * k] == unit:
                r += 1
            if r > keep and (best is None or r * k > best[0] * best[1]):
                best = (r, k)
        if best:
            r, k = best
            kept = [dict(w) for w in words[i:i + keep * k]]
            # The time stays spoken: a real chant must not be trimmed as silence later.
            kept[-1]["end"] = max(kept[-1]["end"], words[i + r * k - 1]["end"])
            out += kept
            i += r * k
        else:
            out.append(words[i])
            i += 1
    return out


def clean_transcript(segs, words, prompt=None):
    """Drop repetition loops and segments that only echo the initial prompt. Returns
    (segments, words, number of words dropped)."""
    n0 = len(words)
    phrases = [_norm(p) for p in re.split(r"[。、,，\n（）()]", prompt or "") if len(_norm(p)) >= 4]
    echo = []
    keep_segs = []
    for s in segs:
        t = _norm(s["text"])
        rest, hits = t, 0
        for p in phrases:
            hits += rest.count(p)
            rest = rest.replace(p, "")
        # An echo is long and repeats the prompt; a shouted single term (「国士無双！」) is speech.
        if phrases and t and not rest and len(t) >= 12 and hits >= 2:
            echo.append((s["start"], s["end"]))
            continue
        s = dict(s, text=_LOOP.sub(lambda m: m.group(1) * 4, s["text"]))
        keep_segs.append(s)
    if echo:
        words = [w for w in words if not any(a - 0.05 <= w["start"] < b + 0.05 for a, b in echo)]
    words = collapse_loops(words)
    return keep_segs, words, n0 - len(words)
