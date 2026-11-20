"""End-to-end: synthetic VOD -> analyze -> draft -> render (all layouts) -> QC must pass.

  python -m pytest tests -q        (or: python tests/test_pipeline.py)
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from clipper.common import glossary, load_json, load_yaml, save_json, save_yaml, style  # noqa: E402
from clipper.analyze import analyze  # noqa: E402
from clipper.cli import draft_clips, main  # noqa: E402

DUR = 300
PEAK = 150
PHRASES = ["今日は雀魂で役満を狙います", "これはいけるかもしれない", "待って待って", "嘘でしょ",
           "国士無双テンパイきた", "ロン！役満です", "ありえない", "チャットありがとう", "次の局いきます"]


def speech_plan(seed=3):
    rnd = random.Random(seed)
    t, spans = 2.0, []
    while t < DUR - 3:
        d = rnd.uniform(1.2, 3.5)
        spans.append((t, min(DUR - 1, t + d)))
        t += d + rnd.choice([0.2, 0.3, 0.4, 1.5, 2.5])
    return spans


def make_source(wd):
    spans = speech_plan()
    # Speech-like audio: amplitude-modulated tones only inside spans; a loud burst at the peak.
    expr = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in spans)
    vol = f"(0.25*({expr})+0.6*between(t,{PEAK - 1},{PEAK + 3}))"
    aexpr = f"{vol}*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*5*t))"
    src = os.path.join(wd, "source.mp4")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30:duration={DUR}",
                    "-f", "lavfi", "-i", f"aevalsrc='{aexpr}':s=48000:d={DUR}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", src], check=True)
    words = []
    rnd = random.Random(5)
    for i, (a, b) in enumerate(spans):
        phrase = PHRASES[i % len(PHRASES)] if abs(a - PEAK) > 6 else "ロン！役満です"
        step = (b - a) / len(phrase)
        for k, ch in enumerate(phrase):
            words.append({"start": round(a + k * step, 3), "end": round(a + (k + 1) * step, 3), "word": ch})
    save_json(os.path.join(wd, "transcript.json"), {"words": words, "segments": []})
    chat = [{"t": t + rnd.random(), "text": rnd.choice(["こんばんは", "がんばれ", "888", "かわいい"])}
            for t in range(0, DUR, 2)]
    chat += [{"t": PEAK + 6 + rnd.random() * 6, "text": rnd.choice(["草", "wwwww", "役満！？", "えぐい", "神"])}
             for _ in range(80)]
    save_json(os.path.join(wd, "chat.json"), sorted(chat, key=lambda m: m["t"]))
    return src


def test_end_to_end():
    wd = tempfile.mkdtemp(prefix="clipper_test_")
    try:
        src = make_source(wd)
        st, gl = style(), glossary()
        cands = analyze(wd, src, DUR, st, gl)["candidates"]
        assert cands, "no candidates"
        top = cands[0]
        assert abs(top["peak"] - PEAK) < 15, f"top candidate {top['peak']} not near planted peak {PEAK}"
        assert top["short"]["start"] < PEAK < top["short"]["end"]

        draft_clips(wd, [1], ["short", "long"], st, gl)
        spec = load_yaml(os.path.join(wd, "clips.yaml"))
        short, long_ = spec["clips"]
        short.update(hook="一点読みで国士無双ロン!?", band_text="雀魂×役満", title="テスト")
        long_.update(label="【雀魂】東2局", thumbnail_text="バケモノ役満『国士無双』",
                     start=max(0, PEAK - 140), end=PEAK + 140)
        variants = [short, dict(short, id="c01s_split", layout="split"),
                    dict(short, id="c01s_crop", layout="crop", hook="", band_text=""), long_]
        assert short["subs"], "draft has no subtitles"
        save_yaml(os.path.join(wd, "clips.yaml"), {"clips": variants})

        main(["render", wd])
        try:
            main(["qc", wd])
        except SystemExit as e:
            qc = load_json(os.path.join(wd, "out", "qc.json"))
            bad = [(r["file"], [c for c in r["checks"] if not c["ok"]]) for r in qc if not r["pass"]]
            raise AssertionError(f"QC failed: {bad}") if e.code else e
        qc = load_json(os.path.join(wd, "out", "qc.json"))
        assert len(qc) == 4 and all(r["pass"] for r in qc), qc
        assert os.path.exists(os.path.join(wd, "out", "c01l_thumb.jpg"))
        print("OK", wd)
        return wd
    except Exception:
        print("work dir kept:", wd)
        raise


if __name__ == "__main__":
    keep = test_end_to_end()
    if "--clean" in sys.argv:
        shutil.rmtree(keep)
