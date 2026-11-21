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


def test_align_script_times_proofread_lines():
    # Whisper JA tokens straddle words (「いいねーう」「ちやっちまえ」); proofread lines get char timings,
    # a repeated phrase does not pull the match ahead, notes are timed by neighbours, no overlaps.
    from clipper.subs import align_script
    toks = ["いいねーう", "ちやっちまえ、", "戦力バブリタイム", "戦力バブリタイムは", "私の", "全", "力バブリタイムって", "何すんの?"]
    words, t = [], 0.0
    for tk in toks:
        words.append({"start": t, "end": t + 1.0, "word": tk})
        t += 1.5
    script = ["いいねー", "うちやっちまえ", "全力バブリタイム", "（ゲーム音声）", "全力バブリタイムは私の", "*全力バブリタイムって何すんの？"]
    lines, warn = align_script(words, 0, t, script)
    assert not [w for w in warn if w.startswith("未一致")], warn
    assert [ln["text"] for ln in lines][1] == "うちやっちまえ"
    assert lines[2]["start"] < 4.6, lines[2]          # first 戦力バブリタイム, not the later 全力
    assert lines[5].get("emph") and lines[5]["start"] > 7.4, lines[5]  # the 全 token at 7.5 s
    for a, b in zip(lines, lines[1:]):
        assert a["end"] <= b["start"] + 1e-6, (a, b)


def test_cut_silences_removes_dead_air_inside_word_spans():
    from clipper.timeline import cut_silences
    # One stretched token kept 4204-4208 although only silence was there.
    out = cut_silences([[4199.0, 4212.0]], [(4204.6, 3.4), (4210.0, 0.6)], keep=[])
    assert out == [[4199.0, 4204.8], [4207.8, 4212.0]], out
    # A forced keep (silent game-over screen) is never cut.
    assert cut_silences([[10.0, 30.0]], [(15.0, 5.0)], keep=[(14.0, 21.0)]) == [[10.0, 30.0]]


def test_keep_ranges_survive_silence_trim():
    # A silent game-over screen between two lines must stay when listed in `keep`.
    tl = style()["timeline"]
    words = [{"start": 10.0, "end": 11.0, "word": "a"}, {"start": 30.0, "end": 31.0, "word": "b"}]
    clip = {"start": 9, "end": 32, "trim_silence": True}
    base = keep_ranges(clip, words, tl)
    assert not any(a <= 20 <= b for a, b in base), base
    kept = keep_ranges(dict(clip, keep=[[18, 24]]), words, tl)
    assert any(a <= 18 and 24 <= b for a, b in kept), kept
    assert not any(a <= 15 <= b for a, b in kept), kept


def test_transcript_loops_and_prompt_echo_removed():
    # A 3 h stream came back with "きた" x200 and the prompt sentence echoed as speech.
    from clipper.transcribe import clean_transcript
    words = [{"start": i * 0.2, "end": i * 0.2 + 0.2, "word": "きた"} for i in range(200)]
    words += [{"start": 50 + i * 0.2, "end": 50.2 + i * 0.2, "word": w} for i, w in enumerate(["やば", "い", "あった", "。"])]
    words += [{"start": 60 + i, "end": 60.5 + i, "word": w} for i, w in enumerate(["後半", "は", "Call", " of", " Duty", "。"])]
    segs = [{"start": 0, "end": 40, "text": "きた" * 200}, {"start": 50, "end": 51, "text": "やばいあった。"},
            {"start": 60, "end": 66, "text": "後半はCall of Duty。後半はCall of Duty。"}]
    s2, w2, dropped = clean_transcript(segs, words, "ろあろああの配信。後半はCall of Duty。")
    assert [w["word"] for w in w2] == ["きた"] * 4 + ["やば", "い", "あった", "。"], [w["word"] for w in w2]
    assert len(s2) == 2 and s2[0]["text"] == "きた" * 4 and dropped == 196 + 6
    # Real short repeats survive.
    short = [{"start": i, "end": i + 1, "word": "やばい"} for i in range(3)]
    assert len(clean_transcript([], short, None)[1]) == 3


def test_review_findings_transcript_and_align():
    # Independent review of the local-run commit; each case reproduced before the fix.
    from clipper.transcribe import clean_transcript, collapse_loops
    from clipper.subs import align_script
    prompt = "雀魂、役満、国士無双、テンパイ、おばあちゃん"
    # 1. A shouted single term is speech, not a prompt echo.
    segs = [{"start": 0, "end": 1, "text": "国士無双！"}, {"start": 2, "end": 3, "text": "おばあちゃん！"}]
    words = [{"start": 0, "end": 1, "word": "国士無双！"}, {"start": 2, "end": 3, "word": "おばあちゃん！"}]
    s2, w2, _ = clean_transcript(segs, words, prompt)
    assert len(s2) == 2 and len(w2) == 2
    # 2. A real chant keeps its time span after collapsing.
    chant = [{"start": 10 + i * 0.4, "end": 10.3 + i * 0.4, "word": "きた"} for i in range(8)]
    kept = collapse_loops(chant)
    assert len(kept) == 4 and kept[-1]["end"] == chant[-1]["end"]
    # 9. Digits never collapse.
    s3, _, _ = clean_transcript([{"start": 0, "end": 1, "text": "賞金100000円"}], [], None)
    assert s3[0]["text"] == "賞金100000円"
    # 3. A line missing from the transcript does not steal letters from later lines.
    toks = [("おはよう", 0), ("ちょっとまって", 4), ("いやいやいや", 7), ("ばか", 9)]
    ws = [{"start": t, "end": t + 1.5, "word": w} for w, t in toks]
    lines, warn = align_script(ws, 0, 12, ["おはよう", "やばいやばい", "ちょっとまって", "いやいやいや", "ばか"])
    by = {ln["text"]: ln for ln in lines}
    assert 3.8 <= by["ちょっとまって"]["start"] <= 4.1, by["ちょっとまって"]
    assert by["いやいやいや"]["end"] - by["いやいやいや"]["start"] >= 0.7
    assert any("やばいやばい" in w for w in warn), warn
    # 4. Consecutive notes share the gap and never push the next spoken line late.
    ws = [{"start": 0, "end": 1.0, "word": "おはようございます"}, {"start": 3.0, "end": 4.0, "word": "それでは始めます"}]
    lines, _ = align_script(ws, 0, 5, ["おはようございます", "（BGM）", "(英語音声)", "それでは始めます"])
    assert all(b["end"] - b["start"] > 0.3 for b in lines[1:3]), lines
    assert 2.9 <= lines[3]["start"] <= 3.0, lines[3]
    # Katakana telop vs hiragana ASR, and a line after long unscripted talk.
    ws = [{"start": 0, "end": 1, "word": "あ、きも、きも"}]
    ws += [{"start": 2 + i, "end": 2.8 + i, "word": "なになになにぐろいしぬしぬ"} for i in range(10)]
    ws += [{"start": 20, "end": 22, "word": "ゾンビモードだったね"}]
    lines, warn = align_script(ws, 0, 23, ["キモ！キモ！", "*ゾンビモード\nだったね"])
    assert not warn and lines[0]["start"] < 1 and lines[1]["start"] >= 19.9, (lines, warn)


def test_review_findings_ranges():
    from clipper.timeline import cut_silences
    tl = style()["timeline"]
    # 5. A keep that only touches a long silence does not save all of it.
    out = cut_silences([[0.0, 60.0]], [(23.5, 30.0)], keep=[(18.0, 24.0)])
    assert any(a <= 20 <= b for a, b in out) and not any(a <= 40 <= b for a, b in out), out
    # 8. No transcript words + keep: the whole clip stays.
    assert keep_ranges({"start": 0, "end": 60, "keep": [[18, 24]]}, [], tl) == [[0.0, 60.0]]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
