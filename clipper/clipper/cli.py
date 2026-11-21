"""clipper: livestream VOD -> finished Shorts and horizontal clips.

  python -m clipper fetch URL                  # ① PCで: 動画とチャットを取得
  python -m clipper transcribe WORK            # ② 文字起こし（GPUがあれば自動で使用）
  python -m clipper analyze WORK               # ③ 見どころ候補 → candidates.md
  python -m clipper draft WORK --pick 1,2,3    # ④ 候補から clips.yaml を下書き（字幕つき）
  python -m clipper align WORK [--only c01]    # 校正した script（テロップ文）に時刻を付けて subs を作る
  python -m clipper build WORK [--only c01]    # clips.src.yaml→align→事前チェック→render→qc を一度に
  python -m clipper render WORK [--only c01]   # ⑤ 書き出し → WORK/out/
  python -m clipper qc WORK                    # ⑥ 品質チェック → WORK/out/qc.json と一覧画像
  python -m clipper run URL --pick 1-5         # ①〜⑥を通しで
  python -m clipper calibrate WORK --at 600    # レイアウト調整用のフレーム画像
"""
import argparse
import os
import sys

from .common import (ROOT, glossary, load_json, load_yaml, media_info, need, run, save_json, save_yaml,
                     source_path, style, work_dir)


def _picks(spec, n):
    """'1,3-5' -> [1,3,4,5]. Out-of-range picks are an error, never silently replaced."""
    out = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    bad = [p for p in out if not 1 <= p <= n]
    if bad:
        sys.exit(f"--pick {bad} は範囲外です（候補は 1〜{n}）")
    return out


def cmd_fetch(a):
    from .fetch import fetch
    wd = fetch(a.url, a.work_root, a.cookies_from_browser, a.max_height)
    print(wd)
    return wd


def cmd_transcribe(a):
    from .transcribe import transcribe
    wd = work_dir(a.work)
    out = transcribe(wd, source_path(wd), glossary(), a.model, a.device,
                     getattr(a, "prompt", None), getattr(a, "batch", None))
    print(f"{len(out['words'])} words, device={out['device']}")


def cmd_analyze(a):
    from .analyze import analyze
    wd = work_dir(a.work)
    src = source_path(wd)
    out = analyze(wd, src, media_info(src)["duration"], style(), glossary())
    print(os.path.join(wd, "candidates.md"))
    for c in out["candidates"][:5]:
        print(f"  {c['rank']:2d}. peak {c['peak']:.0f}s score {c['score']}  {c['transcript'][:60]}")


def draft_clips(wd, picks, formats, st, gl):
    from .subs import auto_lines
    from .render import load_words
    cands = load_json(os.path.join(wd, "candidates.json"))["candidates"]
    words = load_words(wd)
    clips = []
    for p in picks:
        c = cands[p - 1]
        for fmt in formats:
            win = c["short"] if fmt == "short" else c["long"]
            lines = auto_lines(words, win["start"], win["end"], st[fmt]["subs"]["max_chars_per_line"], gl)
            clips.append({
                "id": f"c{p:02d}{'s' if fmt == 'short' else 'l'}",
                "format": fmt,
                "layout": st["short"]["layout"] if fmt == "short" else "full",
                "start": win["start"], "end": win["end"],
                "trim_silence": True,
                "title": "", "hook": "", "band_text": "", "label": "",
                "thumbnail_text": "", "thumbnail_at": c["peak"],
                "zoom": [{"at": c["peak"], "dur": 1.4, "scale": 1.18}],
                "se": [], "overlays": [],
                "subs": [{"start": ln["start"], "end": ln["end"], "text": ln["text"]} for ln in lines],
                "_candidate": p,
            })
    path = os.path.join(wd, "clips.yaml")
    save_yaml(path, {"clips": clips})
    return path


def cmd_draft(a):
    wd = work_dir(a.work)
    n = len(load_json(os.path.join(wd, "candidates.json"))["candidates"])
    picks = _picks(a.pick, n) or list(range(1, min(n, 5) + 1))
    print(draft_clips(wd, picks, a.formats.split(","), style(), glossary()))


def _clips(wd, only):
    spec = load_yaml(os.path.join(wd, "clips.yaml"))
    clips = spec.get("clips", [])
    if only:
        keep = set(only.split(","))
        clips = [c for c in clips if c["id"] in keep]
    return clips


def cmd_render(a):
    from .render import load_words, render_clip
    from .thumb import make_thumbnail
    wd = work_dir(a.work)
    st, gl = style(), glossary()
    words = load_words(wd)
    out_dir = os.path.join(wd, "out")
    os.makedirs(out_dir, exist_ok=True)
    from .progress import current
    solo = _solo_progress(wd, f"{os.path.basename(wd)} の書き出し",
                          [(f"r:{c['id']}", f"書き出し {c['id']}", 10 + 0.35 * (float(c['end']) - float(c['start'])))
                           for c in _clips(wd, a.only)])
    reports = []
    pkg = (load_yaml(os.path.join(wd, "clips.yaml")) or {}).get("package") or {}
    for c in _clips(wd, a.only):
        # Per-video defaults from `package:` (stand-in art, partner name, BGM); a clip may override.
        for key in ("avatar", "partner_name", "bgm", "avatar_speaker", "partner_speaker"):
            if key in pkg and key not in c:
                c[key] = pkg[key]
        if c.get("format", "short") == "short" and pkg.get("short_layout") and "layout_fixed" not in c:
            c["layout"] = pkg["short_layout"]
        out = os.path.join(out_dir, f"{c['id']}.mp4")
        prog = current()
        if prog:
            prog.start(f"r:{c['id']}")
        r = render_clip(wd, c, st, gl, out, words)
        if c.get("format") == "long":
            local = os.path.join(ROOT, "config", "local.yaml")
            intro = c.get("intro", pkg.get("intro", (load_yaml(local) or {}).get("long_intro") if os.path.exists(local) else None))
            if intro or c.get("teaser", True):
                from .render import add_opening
                add_opening(out, r, intro, out, st, teaser=c.get("teaser", pkg.get("teaser", True)))
        if prog:
            prog.done(f"r:{c['id']}", f"{r['duration']}秒")
        if c.get("format") == "long" and c.get("thumbnail_text"):
            r["thumbnail"] = make_thumbnail(c.get("source") or source_path(wd), float(c.get("thumbnail_at", c["start"])),
                                            c["thumbnail_text"], st, os.path.join(out_dir, f"{c['id']}_thumb.jpg"),
                                            c.get("thumbnail_sticker"))
        reports.append(r)
        print(f"  {r['id']}: {r['duration']}s ({r['segments']} segments, -{r['removed_sec']}s) -> {out}")
    _merge_json(os.path.join(out_dir, "render.json"), reports, lambda r: r["id"])
    if solo:
        solo.finish(True, f"{len(reports)}本を書き出しました")
        from .site import refresh
        refresh(wd)
    return reports


def _merge_json(path, new, key):
    """Replace the entries for what was just processed; keep the rest (runs with --only)."""
    old = load_json(path) if os.path.exists(path) else []
    done = {key(r) for r in new}
    save_json(path, [r for r in old if key(r) not in done] + list(new))


def _solo_progress(wd, title, steps):
    """render/qc run on their own still get a progress page (build makes its own)."""
    from .progress import Progress, current
    if current():
        return None
    p = Progress(wd, title, steps)
    print(f"  進捗ページ: {os.path.join(wd, 'progress.html')}", flush=True)
    return p


def cmd_qc(a):
    from .qc import check
    wd = work_dir(a.work)
    st = style()
    out_dir = os.path.join(wd, "out")
    rj = os.path.join(out_dir, "render.json")
    reports = {r["id"]: r for r in load_json(rj)} if os.path.exists(rj) else {}
    results, ok = [], True
    clips = _clips(wd, a.only)
    if not clips:
        print("  FAIL: clips.yaml に検査するクリップがありません")
        return False
    solo = _solo_progress(wd, f"{os.path.basename(wd)} の品質チェック",
                          [(f"q:{c['id']}", f"品質チェック {c['id']}", 20 + 0.08 * (float(c['end']) - float(c['start'])))
                           for c in clips])
    for c in clips:
        path = os.path.join(out_dir, f"{c['id']}.mp4")
        if not os.path.exists(path):
            print(f"  {c['id']}: FAIL\n      - 書き出しファイルがありません: {path}")
            results.append({"file": path, "format": c.get("format"), "pass": False,
                            "checks": [{"name": "exists", "ok": False, "detail": "missing", "hard": True}]})
            ok = False
            continue
        ass = (reports.get(c["id"]) or {}).get("ass") or os.path.join(out_dir, f"{c['id']}.ass")
        from .progress import current
        prog = current()
        if prog:
            prog.start(f"q:{c['id']}")
        r = check(path, c.get("format", "short"), st, ass,
                  os.path.join(out_dir, f"{c['id']}_sheet.png"), getattr(a, "asr", None),
                  opening=float((reports.get(c["id"]) or {}).get("opening") or 0.0))
        results.append(r)
        ok &= r["pass"]
        bad = [f"{x['name']}: {x['detail']}" for x in r["checks"] if not x["ok"]]
        if prog:
            hard = [x["name"] for x in r["checks"] if not x["ok"] and x.get("hard", True)]
            prog.done(f"q:{c['id']}", "合格" if r["pass"] else "不合格: " + ", ".join(hard), ok=r["pass"])
        print(f"  {c['id']}: {'PASS' if r['pass'] else 'FAIL'}" + ("".join(f"\n      - {b}" for b in bad)))
    _merge_json(os.path.join(out_dir, "qc.json"), results, lambda r: os.path.basename(r["file"]))
    if solo:
        solo.finish(ok, "全クリップ合格" if ok else "不合格のクリップがあります")
        from .site import refresh
        refresh(wd)
    return ok


def cmd_align(a):
    """clips.yaml: for every clip with `script:` (proofread telop lines), (re)build `subs` with timings."""
    from .render import load_words
    from .subs import align_script
    from .transcribe import speech_spans
    wd = work_dir(a.work)
    path = os.path.join(wd, "clips.yaml")
    spec = load_yaml(path)
    words = load_words(wd)
    keep = set(a.only.split(",")) if a.only else None
    bad = False
    src = source_path(wd)
    ml = _ml_available() and not getattr(a, "no_ml", False)
    timing = []
    for c in spec.get("clips", []):
        if not c.get("script") or (keep and c["id"] not in keep):
            continue
        s0, s1 = float(c["start"]), float(c["end"])
        speech = speech_spans(c.get("source") or src, s0, s1)
        lines, warn = align_script(words, s0, s1, c["script"], speech)
        c["subs"] = lines
        if ml:   # timing from three estimates on the voice-only stem (see align_ctc.combine_timing)
            from .align_ctc import combine_timing, ctc_starts
            from .voiceprep import speech_on, vocal_words, vocals
            v = vocals(wd, c.get("source") or src, s0, s1)
            vw = vocal_words(wd, v, s0, s1)
            lines_w, _ = align_script(vw, s0, s1, c["script"], None)
            est_w = [(float(x["start"]), float(x["end"])) if x.get("_m") else None for x in lines_w]
            est_c = ctc_starts(lines, v, s0, s0, s1)
            timing += [dict(t, clip=c["id"]) for t in combine_timing(lines, est_w, est_c, speech_on(v, s0), s0, s1)]
        for ln in lines:
            ln.pop("_m", None)
        print(f"  {c['id']}: {len(lines)} lines" + "".join(f"\n      - {w}" for w in warn))
        bad |= bool(warn)
    if timing:
        save_json(os.path.join(wd, "timing_report.json"), timing)
        by = {}
        for t in timing:
            by[t["src"]] = by.get(t["src"], 0) + 1
        later = [t for t in timing if t["after"] - t["before"] > 0.3]
        print(f"  時刻合わせ: 声だけWhisper {by.get('W', 0)}行・強制アライメント {by.get('C', 0)}行・従来 {by.get('O', 0)}行"
              f" ／ 早すぎた行を {len(later)}行 遅らせて修正")
    if not getattr(a, "no_speakers", False) and ml and (spec.get("package") or {}).get("speaker_gender"):
        _label_by_votes(wd, spec, src)
    elif not getattr(a, "no_speakers", False):
        from .diarize import label_lines
        from .progress import current
        # Label every aligned clip (labels must not change with --only) from the stream-wide
        # diarization index (built once per video, cached in diar.npz).
        done = [c for c in spec.get("clips", []) if c.get("subs")]
        chat_p = os.path.join(wd, "chat.json")
        meta = load_json(os.path.join(wd, "meta.json")) if os.path.exists(os.path.join(wd, "meta.json")) else {}
        src = source_path(wd)
        dur = float(meta.get("duration") or media_info(src)["duration"])
        prog = current()
        rep = label_lines(wd, src, dur, done, load_json(chat_p) if os.path.exists(chat_p) else [],
                          on_progress=(lambda f: prog.set_frac("align", 0.1 + 0.85 * f)) if prog else None)
        for name, r in rep.items():
            if name.startswith("_"):
                continue
            how = "・".join(f"{k}{v}" for k, v in r["how"].items())
            print(f"  話者 {name}: {r['lines']}行（{how}） 例: {' / '.join(r['examples'][:3])}")
        review = rep.get("_review", [])
        save_json(os.path.join(wd, "speaker_review.json"), review)
        print(f"  話者の確認候補（自信が低い行）: {len(review)}行 → 動画ページに一覧")
    save_yaml(path, spec)
    return not bad


def _ml_available():
    try:
        import torch  # noqa: F401
        import demucs  # noqa: F401
        import transformers  # noqa: F401
        import pyworld  # noqa: F401
        return True
    except ImportError:
        return False


def _label_by_votes(wd, spec, src):
    """Speakers from several independent methods on voice-only audio (voicevote.py)."""
    from .diarize import _embed, _extractor, _norm, is_chat_line
    from .subs import is_note
    from .voicevote import label
    from .voiceprep import vocals
    pkg = spec.get("package") or {}
    chat_p = os.path.join(wd, "chat.json")
    chat = load_json(chat_p) if os.path.exists(chat_p) else []
    chat_norm = [_norm(m.get("text", "")) for m in chat if len(_norm(m.get("text", ""))) >= 4]
    ex = _extractor()
    lines, segs = [], []
    for c in spec.get("clips", []):
        if not c.get("subs"):
            continue
        s0, s1 = float(c["start"]), float(c["end"])
        v = vocals(wd, c.get("source") or src, s0, s1)
        for ln in c["subs"]:
            if is_note(ln["text"]):
                continue
            a, b = float(ln["start"]), float(ln["end"])
            if b - a < 0.6:
                m = (a + b) / 2
                a, b = m - 0.3, m + 0.3
            lines.append(ln)
            segs.append(v[max(0, int((a - s0) * 16000)):max(0, int((b - s0) * 16000))])
    det = label(lines, segs, lambda x: _embed(ex, x), lambda t: is_chat_line(t, chat_norm), pkg["speaker_gender"])
    review = [{"clip": next(c["id"] for c in spec["clips"] if ln in (c.get("subs") or [])),
               "at": ln["start"], "text": ln["text"].replace("\n", ""), "speaker": ln["speaker"],
               "conf": ln.get("speaker_conf", 0)}
              for ln, d in zip(lines, det) if ln.get("speaker_conf", 1) < 0.6 or d.get("clash")]
    save_json(os.path.join(wd, "speaker_review.json"), review)
    save_json(os.path.join(wd, "speaker_votes.json"),
              [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items() if k != "emb"} for d in det])
    counts = {}
    for ln in lines:
        counts[ln["speaker"]] = counts.get(ln["speaker"], 0) + 1
    print("  話者（複数手法の多数決）: " + "、".join(f"{k} {v}行" for k, v in counts.items())
          + f" ／ 確認候補 {len(review)}行（手法が割れた行・自信が低い行）")


def preflight(wd, only=None):
    """Cheap checks that would otherwise fail only after a full render: every subtitle row fits
    the qc row limit. Returns a list of problems (empty = go)."""
    from .subs import dw, wrap
    st = style()
    probs = []
    for c in _clips(wd, only):
        fmt = c.get("format", "short")
        sc = st[fmt]["subs"]
        limit = st["qc"]["max_line_chars_short" if fmt == "short" else "max_line_chars_long"]
        for ln in c.get("subs") or []:
            rows = wrap(ln["text"], sc["max_chars_per_line"], sc["max_lines"])
            bad = [r for r in rows if dw(r) > limit]
            if bad:
                probs.append(f"{c['id']}: 1行{limit}字超 {bad} ← 「{ln['text']}」に \\n を入れるか短く")
    return probs


def cmd_build(a):
    """One iteration, stopping at the first problem: clips.src.yaml → clips.yaml → align →
    preflight → render → qc. Nothing is rendered while a cheap check still fails."""
    import shutil
    from .progress import Progress
    wd = work_dir(a.work)
    src = os.path.join(wd, "clips.src.yaml")
    dst = os.path.join(wd, "clips.yaml")
    if os.path.exists(src):
        # With --only, keep the already-aligned subs of the other clips (src has none).
        old = {c["id"]: c for c in (load_yaml(dst).get("clips", []) if os.path.exists(dst) else [])}
        shutil.copyfile(src, dst)
        if a.only:
            spec = load_yaml(dst)
            keep = set(a.only.split(","))
            for c in spec.get("clips", []):
                if c["id"] not in keep and old.get(c["id"], {}).get("subs"):
                    c["subs"] = old[c["id"]]["subs"]
            save_yaml(dst, spec)
    clips = _clips(wd, a.only)
    # Rough time estimates (s) only weight the overall bar; the page recalibrates from elapsed time.
    first_diar = not os.path.exists(os.path.join(wd, "diar.npz"))
    steps = [("align", "テロップの時刻合わせ・話者判定" + ("（初回は配信全体を解析）" if first_diar else ""),
              15 + 8 * len(clips) + (300 if first_diar else 0))]
    steps += [(f"r:{c['id']}", f"書き出し {c['id']}", 10 + 0.35 * (float(c['end']) - float(c['start'])))
              for c in clips]
    steps += [(f"q:{c['id']}", f"品質チェック {c['id']}", 20 + 0.08 * (float(c['end']) - float(c['start'])))
              for c in clips]
    prog = Progress(wd, f"{os.path.basename(wd)} の書き出し", steps)
    print(f"  進捗ページ: {os.path.join(wd, 'progress.html')}", flush=True)
    from .site import refresh
    refresh(wd)  # the video page shows a "処理中" banner linking to progress.html
    try:
        prog.start("align")
        if not cmd_align(a):
            prog.done("align", "script の未一致あり", ok=False)
            prog.finish(False, "テロップ文が文字起こしと一致しない行があります（書き出し前に停止）")
            print("  STOP: script の未一致を直してから（render はしていません）")
            return False
        probs = preflight(wd, a.only)
        if probs:
            prog.done("align", "1行の文字数超過", ok=False)
            prog.finish(False, "書き出し前チェックで停止: " + " / ".join(probs[:3]))
            print("  STOP: 書き出し前チェック（render はしていません）" + "".join(f"\n      - {p}" for p in probs))
            return False
        prog.done("align")
        cmd_render(a)
        ok = cmd_qc(a)
        prog.finish(ok, "全クリップ合格" if ok else "品質チェック不合格のクリップがあります")
        return ok
    except Exception as e:
        prog.finish(False, f"エラー: {e}"[:300])
        raise
    finally:
        refresh(wd)


def cmd_site(a):
    from .common import default_work_root
    from .site import write_index, write_video_page
    if a.work:
        wd = work_dir(a.work)
        print(write_video_page(wd))
        print(write_index(os.path.dirname(wd)))
        return
    root = default_work_root()
    for n in sorted(os.listdir(root)):
        wd = os.path.join(root, n)
        if os.path.isdir(wd) and os.path.exists(os.path.join(wd, "meta.json")):
            print(write_video_page(wd))
    print(write_index(root))


def cmd_calibrate(a):
    wd = work_dir(a.work)
    out = os.path.join(wd, f"frame_{int(a.at)}.png")
    run([need("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-ss", str(a.at), "-i", source_path(wd),
         "-frames:v", "1", "-vf", "drawgrid=w=iw/10:h=ih/10:t=1:c=yellow@0.6", out])
    print(out)


def cmd_run(a):
    wd = cmd_fetch(a)
    a.work = wd
    cmd_transcribe(a)
    cmd_analyze(a)
    n = len(load_json(os.path.join(wd, "candidates.json"))["candidates"])
    draft_clips(wd, _picks(a.pick, n) or list(range(1, min(n, 5) + 1)), a.formats.split(","), style(), glossary())
    a.only, a.asr = None, "medium"
    cmd_render(a)
    sys.exit(0 if cmd_qc(a) else 1)


def main(argv=None):
    # GPU libraries: torch must load its cuDNN before ctranslate2 (faster-whisper) does, or the two
    # cuDNN builds clash in one process ("Could not load symbol cudnnGetLibConfig", hard crash).
    try:
        import torch  # noqa: F401
    except ImportError:
        pass
    # Japanese messages must not crash a cp932/cp1252 console (Windows, piped output).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="clipper", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def fetch_args(s):
        s.add_argument("url")
        s.add_argument("--work-root", default=None, help="省略時は config/local.yaml の work_root（動画ごとにフォルダを作る）")
        s.add_argument("--cookies-from-browser", default=None, help="chrome / edge / firefox（自分のログイン済みブラウザ）")
        s.add_argument("--max-height", type=int, default=1080)

    def asr_args(s):
        s.add_argument("--model", default="large-v3")
        s.add_argument("--device", default="auto")
        s.add_argument("--prompt", default=None, help="Whisper の事前プロンプト（配信者名・ゲーム用語）。省略時は glossary の terms")
        s.add_argument("--batch", type=int, default=None, help="バッチ推論の大きさ（GPU既定16、1で逐次）")

    s = sub.add_parser("fetch"); fetch_args(s); s.set_defaults(f=cmd_fetch)
    s = sub.add_parser("transcribe"); s.add_argument("work"); asr_args(s); s.set_defaults(f=cmd_transcribe)
    s = sub.add_parser("analyze"); s.add_argument("work"); s.set_defaults(f=cmd_analyze)
    s = sub.add_parser("draft"); s.add_argument("work"); s.add_argument("--pick", default="")
    s.add_argument("--formats", default="short"); s.set_defaults(f=cmd_draft)
    s = sub.add_parser("render"); s.add_argument("work"); s.add_argument("--only"); s.set_defaults(f=cmd_render)
    s = sub.add_parser("qc"); s.add_argument("work"); s.add_argument("--only")
    s.add_argument("--asr", nargs="?", const="medium", default=None, help="書き出した動画を再度文字起こしして字幕の同期を検証")
    s.set_defaults(f=lambda a: sys.exit(0 if cmd_qc(a) else 1))
    s = sub.add_parser("build", help="src→align→書き出し前チェック→render→qc を1回で（問題があれば render 前に止まる）")
    s.add_argument("work"); s.add_argument("--only")
    s.add_argument("--asr", nargs="?", const="large-v3", default="large-v3")
    s.set_defaults(f=lambda a: sys.exit(0 if cmd_build(a) else 1))
    s = sub.add_parser("site", help="一覧ページ・動画ページ・delivery.md を作り直す（省略時は全動画）")
    s.add_argument("work", nargs="?", default=None)
    s.set_defaults(f=cmd_site)
    s = sub.add_parser("align"); s.add_argument("work"); s.add_argument("--only")
    s.add_argument("--no-speakers", action="store_true", help="話者の色分けをしない")
    s.set_defaults(f=lambda a: sys.exit(0 if cmd_align(a) else 1))
    s = sub.add_parser("calibrate"); s.add_argument("work"); s.add_argument("--at", type=float, default=600); s.set_defaults(f=cmd_calibrate)
    s = sub.add_parser("run"); fetch_args(s); asr_args(s); s.add_argument("--pick", default="")
    s.add_argument("--formats", default="short"); s.set_defaults(f=cmd_run)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
