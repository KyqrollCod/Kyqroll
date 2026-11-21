"""clipper: livestream VOD -> finished Shorts and horizontal clips.

  python -m clipper fetch URL                  # ① PCで: 動画とチャットを取得
  python -m clipper transcribe WORK            # ② 文字起こし（GPUがあれば自動で使用）
  python -m clipper analyze WORK               # ③ 見どころ候補 → candidates.md
  python -m clipper draft WORK --pick 1,2,3    # ④ 候補から clips.yaml を下書き（字幕つき）
  python -m clipper align WORK [--only c01]    # 校正した script（テロップ文）に時刻を付けて subs を作る
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
    reports = []
    for c in _clips(wd, a.only):
        out = os.path.join(out_dir, f"{c['id']}.mp4")
        r = render_clip(wd, c, st, gl, out, words)
        if c.get("format") == "long" and c.get("thumbnail_text"):
            r["thumbnail"] = make_thumbnail(c.get("source") or source_path(wd), float(c.get("thumbnail_at", c["start"])),
                                            c["thumbnail_text"], st, os.path.join(out_dir, f"{c['id']}_thumb.jpg"),
                                            c.get("thumbnail_sticker"))
        reports.append(r)
        print(f"  {r['id']}: {r['duration']}s ({r['segments']} segments, -{r['removed_sec']}s) -> {out}")
    save_json(os.path.join(out_dir, "render.json"), reports)
    return reports


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
    for c in clips:
        path = os.path.join(out_dir, f"{c['id']}.mp4")
        if not os.path.exists(path):
            print(f"  {c['id']}: FAIL\n      - 書き出しファイルがありません: {path}")
            results.append({"file": path, "format": c.get("format"), "pass": False,
                            "checks": [{"name": "exists", "ok": False, "detail": "missing", "hard": True}]})
            ok = False
            continue
        ass = (reports.get(c["id"]) or {}).get("ass") or os.path.join(out_dir, f"{c['id']}.ass")
        r = check(path, c.get("format", "short"), st, ass,
                  os.path.join(out_dir, f"{c['id']}_sheet.png"), getattr(a, "asr", None))
        results.append(r)
        ok &= r["pass"]
        bad = [f"{x['name']}: {x['detail']}" for x in r["checks"] if not x["ok"]]
        print(f"  {c['id']}: {'PASS' if r['pass'] else 'FAIL'}" + ("".join(f"\n      - {b}" for b in bad)))
    save_json(os.path.join(out_dir, "qc.json"), results)
    return ok


def cmd_align(a):
    """clips.yaml: for every clip with `script:` (proofread telop lines), (re)build `subs` with timings."""
    from .render import load_words
    from .subs import align_script
    wd = work_dir(a.work)
    path = os.path.join(wd, "clips.yaml")
    spec = load_yaml(path)
    words = load_words(wd)
    keep = set(a.only.split(",")) if a.only else None
    bad = False
    for c in spec.get("clips", []):
        if not c.get("script") or (keep and c["id"] not in keep):
            continue
        lines, warn = align_script(words, float(c["start"]), float(c["end"]), c["script"])
        c["subs"] = lines
        print(f"  {c['id']}: {len(lines)} lines" + "".join(f"\n      - {w}" for w in warn))
        bad |= bool(warn)
    save_yaml(path, spec)
    return not bad


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
        s.add_argument("--work-root", default=os.path.join(ROOT, "work"))
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
    s = sub.add_parser("align"); s.add_argument("work"); s.add_argument("--only")
    s.set_defaults(f=lambda a: sys.exit(0 if cmd_align(a) else 1))
    s = sub.add_parser("calibrate"); s.add_argument("work"); s.add_argument("--at", type=float, default=600); s.set_defaults(f=cmd_calibrate)
    s = sub.add_parser("run"); fetch_args(s); asr_args(s); s.add_argument("--pick", default="")
    s.add_argument("--formats", default="short"); s.set_defaults(f=cmd_run)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
