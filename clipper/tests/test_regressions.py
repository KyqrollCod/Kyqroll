"""Regression tests for defects found in independent review (each reproduced before the fix)."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import numpy as np  # noqa: E402

from clipper.analyze import _smooth, analyze  # noqa: E402
from clipper.chat import normalize_chat  # noqa: E402
from clipper.cli import main  # noqa: E402
from clipper.common import glossary, media_info, save_json, save_yaml, style  # noqa: E402
from clipper.render import render_clip  # noqa: E402
from clipper.subs import auto_lines, dw, wrap  # noqa: E402
from clipper.timeline import Mapper, keep_ranges  # noqa: E402


def _ff(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def _vod(path, dur, audio="sine=f=330", fps=30):
    a = ["-f", "lavfi", "-i", f"{audio}:d={dur}"] if audio else []
    _ff("-f", "lavfi", "-i", f"testsrc2=s=1280x720:r={fps}:d={dur}", *a,
        "-c:v", "libx264", "-preset", "ultrafast", *(["-c:a", "aac"] if audio else []), "-shortest", path)


def test_render_picks_video_not_info_json():
    wd = tempfile.mkdtemp()
    _vod(os.path.join(wd, "source.mp4"), 20)
    open(os.path.join(wd, "source.info.json"), "w").write("{}")
    open(os.path.join(wd, "source.live_chat.json"), "w").write("")
    r = render_clip(wd, {"id": "a", "format": "short", "start": 2, "end": 18, "trim_silence": False, "subs": []},
                    style(), glossary(), os.path.join(wd, "out", "a.mp4"), [])
    assert media_info(r["out"])["height"] == 1920


def test_silent_and_no_audio_sources_render():
    wd = tempfile.mkdtemp()
    _vod(os.path.join(wd, "source.mp4"), 20, audio=None)
    r = render_clip(wd, {"id": "b", "format": "short", "start": 1, "end": 17, "trim_silence": False, "subs": []},
                    style(), glossary(), os.path.join(wd, "out", "b.mp4"), [])
    assert media_info(r["out"])["has_audio"]


def test_short_vod_analyze_and_edge_highlight():
    assert len(_smooth(np.zeros(31), 60)) == 31
    wd = tempfile.mkdtemp()
    src = os.path.join(wd, "source.mp4")
    # flat quiet audio with a loud burst at t=10..12 near the start
    _vod(src, 90, audio="aevalsrc='0.02*sin(2*PI*300*t)+0.4*between(t,10,12)*sin(2*PI*300*t)'")
    out = analyze(wd, src, 90, style(), glossary())
    assert abs(out["candidates"][0]["peak"] - 11) <= 4, out["candidates"][0]
    wd2 = tempfile.mkdtemp()
    _vod(os.path.join(wd2, "source.mp4"), 30)
    analyze(wd2, os.path.join(wd2, "source.mp4"), 30, style(), glossary())


def test_grid_segments_keep_av_sync():
    wd = tempfile.mkdtemp()
    _vod(os.path.join(wd, "source.mp4"), 200)
    segs = [[100 + i, 100.6 + i] for i in range(80)]
    r = render_clip(wd, {"id": "c", "format": "short", "start": 100, "end": 180, "segments": segs, "subs": []},
                    style(), glossary(), os.path.join(wd, "out", "c.mp4"), [])
    p = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                        "stream=nb_read_frames", "-of", "csv=p=0", r["out"]], capture_output=True, text=True)
    frames = int(p.stdout.strip())
    assert abs(frames / r["fps"] - r["duration"]) < 0.1, (frames, r["duration"])


def test_apostrophe_in_paths():
    base = tempfile.mkdtemp(prefix="O'Brien, [x] ")
    wd = os.path.join(base, "work's")
    os.makedirs(wd)
    _vod(os.path.join(wd, "source.mp4"), 12)
    r = render_clip(wd, {"id": "d", "format": "short", "start": 1, "end": 11, "trim_silence": False,
                         "hook": "テスト", "subs": [{"start": 2, "end": 5, "text": "字幕"}]},
                    style(), glossary(), os.path.join(wd, "out", "d.mp4"), [])
    assert os.path.exists(r["out"]) and os.path.exists(r["ass"])


def test_twitch_chat_with_long_header():
    d = {"FileInfo": {"Version": 1}, "video": {"description": "x" * 5000},
         "comments": [{"content_offset_seconds": 3.5, "message": {"body": "LUL"}}]}
    p = os.path.join(tempfile.mkdtemp(), "c.json")
    json.dump(d, open(p, "w"), indent=2)
    assert normalize_chat(p) == [{"t": 3.5, "text": "LUL"}]


def test_subtitle_edges():
    assert wrap("あ\nい\nう", 11, 2) == ["あ", "いう"]
    ws = [{"start": i * .2, "end": i * .2 + .18, "word": c} for i, c in enumerate("これはいけるかもしれない。")]
    assert all(len(l["text"]) > 2 for l in auto_lines(ws, 0, 10, 11, {"replace": {}}))
    assert all(dw(r) <= 11 for r in wrap("ThisIsAVeryLongEnglishWordWithoutSpaces", 11, 2)[:1])


def test_segments_sorted_and_validated():
    r = keep_ranges({"start": 0, "end": 20, "segments": [[10, 12], [0, 2], [1, 3]]}, [], {})
    assert r == [[0.0, 3.0], [10.0, 12.0]]
    assert Mapper(r).to_out_clamped(1) == 1.0
    try:
        keep_ranges({"id": "x", "start": 0, "end": 5, "segments": [[8, 9]]}, [], {})
        raise AssertionError("empty segments accepted")
    except ValueError:
        pass


def test_cli_rejects_bad_pick_and_empty_qc():
    wd = tempfile.mkdtemp()
    save_json(os.path.join(wd, "candidates.json"), {"candidates": [{"short": {"start": 0, "end": 5},
                                                                    "long": {"start": 0, "end": 5}, "peak": 2}]})
    for argv in (["draft", wd, "--pick", "3"], ["qc", wd]):
        save_yaml(os.path.join(wd, "clips.yaml"), {"clips": []})
        try:
            main(argv)
            raise AssertionError(f"{argv} should fail")
        except SystemExit as e:
            assert e.code not in (0, None), argv


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
