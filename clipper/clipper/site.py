"""Static pages for the work root, served by `python -m http.server` (or opened as files):

  <root>/index.html          every video folder as a card
  <root>/<video>/index.html  every clip: player, title/description/hashtags with copy buttons,
                             QC result, speaker legend, links to sheet/thumbnail
  <root>/<video>/out/delivery.md   the same text for pasting

Titles and descriptions come from clips.src.yaml (`package:` + per-clip `title`, `description`).
"""
import html
import json
import os
import time
from urllib.parse import quote

from .common import load_json, load_yaml, media_info, style

CSS = """
:root{--bg:#0f1115;--card:#181b22;--line:#2a2f3a;--text:#e9edf3;--sub:#9aa3b2;--accent:#3ea8ff;--ok:#5ad17a;--ng:#ff5a5a;--warn:#ffc04d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font-family:"Yu Gothic UI","Hiragino Sans","Noto Sans JP",Meiryo,sans-serif;font-size:14px;line-height:1.6}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header{position:sticky;top:0;z-index:5;background:rgba(15,17,21,.92);backdrop-filter:blur(6px);
border-bottom:1px solid var(--line);padding:12px 20px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header h1{font-size:17px;margin:0;font-weight:700}.crumb{color:var(--sub);font-size:13px}
main{padding:20px;max-width:1280px;margin:0 auto}
.meta{display:flex;gap:18px;flex-wrap:wrap;color:var(--sub);font-size:13px;margin-bottom:14px}
.meta b{color:var(--text);font-weight:600}
.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:13px;margin-bottom:18px}
.legend span{display:inline-flex;align-items:center;gap:6px;background:var(--card);border:1px solid var(--line);
padding:3px 10px;border-radius:999px}.legend i{width:10px;height:10px;border-radius:50%;display:inline-block}
.banner{background:#1d2a38;border:1px solid #2d4a66;border-radius:10px;padding:10px 14px;margin-bottom:16px}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
.grid.long{grid-template-columns:repeat(auto-fill,minmax(520px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;display:flex;flex-direction:column}
.card video,.card img.cover{width:100%;display:block;background:#000}
.short video{aspect-ratio:9/16;max-height:520px;object-fit:contain}.long video{aspect-ratio:16/9}
.body{padding:12px 14px;display:flex;flex-direction:column;gap:8px}
.row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tag{font-size:12px;padding:1px 8px;border-radius:999px;border:1px solid var(--line);color:var(--sub)}
.ok{color:var(--ok);border-color:#2f6b40}.ng{color:var(--ng);border-color:#7a2f2f}.warn{color:var(--warn);border-color:#7a5f22}
.title{font-weight:700;font-size:15px}
.field{background:#11141a;border:1px solid var(--line);border-radius:8px;padding:8px 10px;position:relative;white-space:pre-wrap;word-break:break-all}
.field small{display:block;color:var(--sub);font-size:11px;margin-bottom:2px}
.copy{position:absolute;top:6px;right:6px;font-size:11px;background:#232836;color:var(--text);border:1px solid var(--line);
border-radius:6px;padding:2px 8px;cursor:pointer}.copy:hover{border-color:var(--accent)}
.links{font-size:12px;display:flex;gap:12px;flex-wrap:wrap}
h2{font-size:15px;margin:26px 0 10px;color:var(--sub);font-weight:600}
.vcard{display:flex;gap:14px;padding:12px;align-items:center}.vcard img{width:220px;aspect-ratio:16/9;object-fit:cover;border-radius:8px;background:#000}
.empty{color:var(--sub)}
nav.side{position:fixed;left:0;top:0;bottom:0;width:176px;background:#12151b;border-right:1px solid var(--line);
padding:16px 10px;display:flex;flex-direction:column;gap:4px;z-index:6}
nav.side .brand{font-weight:700;font-size:14px;padding:4px 10px 12px;color:var(--text)}
nav.side a{display:block;padding:8px 10px;border-radius:8px;color:var(--sub);font-size:13px}
nav.side a:hover{background:#1b2029;color:var(--text);text-decoration:none}
nav.side a.on{background:#1d2a38;color:var(--text);border-left:3px solid var(--accent)}
body.has-side header,body.has-side main{margin-left:176px}
@media (max-width:860px){nav.side{position:sticky;bottom:auto;width:auto;flex-direction:row;overflow-x:auto;padding:6px 10px;
border-right:0;border-bottom:1px solid var(--line)}nav.side .brand{display:none}nav.side a{white-space:nowrap}
body.has-side header,body.has-side main{margin-left:0}}
.song{display:grid;grid-template-columns:1fr auto;gap:6px 14px;padding:12px 14px}
.song audio{width:100%;height:32px}.song .k{font-family:Consolas,monospace;color:var(--accent)}
.sit{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-bottom:16px;overflow:hidden}
.sit>.h{padding:12px 14px;border-bottom:1px solid var(--line);background:#151922}
.sit>.h b{font-size:15px}.sit>.h div{color:var(--sub);font-size:13px}
.song+.song{border-top:1px solid var(--line)}
pre.code{background:#11141a;border:1px solid var(--line);border-radius:8px;padding:10px 12px;overflow:auto;font-size:12px}
"""

NAV = [("tasks.html", "動いているタスク"), ("index.html", "動画一覧"), ("music.html", "曲リスト"), ("se.html", "効果音"),
       ("_投稿/", "投稿の記録"), ("_編集手順.md", "編集手順")]


def _nav(active):
    links = "".join(f"<a class='{'on' if href == active else ''}' href='/{_u(href)}'>{_e(label)}</a>" for href, label in NAV)
    return f"<nav class='side'><div class='brand'>切り抜き制作</div>{links}</nav>"

JS = """<script>
function cp(btn){const t=btn.parentElement.querySelector('.v').innerText;
 (navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(()=>{btn.textContent='コピー済み';
 setTimeout(()=>btn.textContent='コピー',1200)}).catch(()=>{const a=document.createElement('textarea');a.value=t;
 document.body.appendChild(a);a.select();document.execCommand('copy');a.remove();btn.textContent='コピー済み'})}
</script>"""


def _e(t):
    return html.escape(str(t or ""))


def _u(path):
    return quote(path.replace("\\", "/"))


def _page(title, head_html, body_html, refresh=None, active="index.html"):
    r = f"<meta http-equiv='refresh' content='{refresh}'>" if refresh else ""
    return (f"<!doctype html><html lang='ja'><head><meta charset='utf-8'>{r}"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{_e(title)}</title>"
            f"<style>{CSS}</style></head><body class='has-side'>{_nav(active)}<header>{head_html}</header>"
            f"<main>{body_html}</main>{JS}</body></html>")


def _spec(wd):
    for name in ("clips.src.yaml", "clips.yaml"):
        p = os.path.join(wd, name)
        if os.path.exists(p):
            return load_yaml(p) or {}
    return {}


def _progress(wd):
    p = os.path.join(wd, "progress.json")
    if not os.path.exists(p):
        return None
    try:
        return load_json(p)
    except (ValueError, OSError):
        return None


def credit(pkg):
    links = " ／ ".join(pkg.get("streamer_links") or [])
    s = f"元配信 {pkg.get('source_url', '')} ／ 配信者 {pkg.get('streamer', '')}"
    return s + (f" {links}" if links else "")


def clip_rows(wd):
    spec = _spec(wd)
    pkg = spec.get("package") or {}
    out = os.path.join(wd, "out")
    qc = {}
    qp = os.path.join(out, "qc.json")
    if os.path.exists(qp):
        for r in load_json(qp):
            qc[os.path.splitext(os.path.basename(r["file"]))[0]] = r
    rows = []
    for c in spec.get("clips", []):
        cid, fmt = c["id"], c.get("format", "short")
        mp4 = os.path.join(out, f"{cid}.mp4")
        dur = None
        if os.path.exists(mp4):
            try:
                dur = media_info(mp4)["duration"]
            except Exception:
                dur = None
        # A clip may override the package tags (a stream with two games: tag only the clip's game).
        tags = c.get("hashtags") or pkg.get("hashtags_short" if fmt == "short" else "hashtags_long", "")
        rows.append({
            "id": cid, "format": fmt, "title": c.get("title") or "", "desc": c.get("description") or "",
            "credit": credit(pkg) if pkg else "", "tags": tags, "dur": dur, "qc": qc.get(cid),
            "mp4": f"out/{cid}.mp4" if os.path.exists(mp4) else None,
            "thumb": f"out/{cid}_thumb.jpg" if os.path.exists(os.path.join(out, f"{cid}_thumb.jpg")) else None,
            "sheet": f"out/{cid}_sheet.png" if os.path.exists(os.path.join(out, f"{cid}_sheet.png")) else None,
            "thumb_text": c.get("thumbnail_text") or "",
            "collab": c.get("collab") or pkg.get("collab"),   # a clip may name its own partner(s)
        })
    return spec, pkg, rows


def _dur(s):
    if not s:
        return "—"
    s = int(round(s))
    return f"{s // 60}分{s % 60:02d}秒" if s >= 60 else f"{s}秒"


def _qc_tag(q):
    if not q:
        return "<span class='tag'>未チェック</span>"
    soft = [c for c in q["checks"] if not c["ok"] and not c.get("hard", True)]
    hard = [c for c in q["checks"] if not c["ok"] and c.get("hard", True)]
    if hard:
        return f"<span class='tag ng' title='{_e(', '.join(c['name'] for c in hard))}'>不合格</span>"
    t = "<span class='tag ok'>品質チェック合格</span>"
    if soft:
        t += f" <span class='tag warn' title='{_e(', '.join(c['name'] for c in soft))}'>注意 {len(soft)}件</span>"
    return t


def _field(label, value):
    if not value:
        return ""
    return (f"<div class='field'><small>{_e(label)}</small><span class='v'>{_e(value)}</span>"
            f"<button class='copy' onclick='cp(this)'>コピー</button></div>")


def write_video_page(wd):
    spec, pkg, rows = clip_rows(wd)
    meta = load_json(os.path.join(wd, "meta.json")) if os.path.exists(os.path.join(wd, "meta.json")) else {}
    name = os.path.basename(wd.rstrip("\\/"))
    st = style()
    names = pkg.get("speaker_names") or {}
    legend = "".join(f"<span><i style='background:{col}'></i>{_e(names.get(k, k))}（{_e(k)}）</span>"
                     for k, col in st["short"]["speakers"].items() if k != "default")
    prog = _progress(wd)
    banner = ""
    if prog and not prog.get("result"):
        banner = (f"<div class='banner'>⏳ 処理中 {int(prog.get('overall', 0) * 100)}%　"
                  f"<a href='progress.html'>進捗ページを見る</a></div>")
    sections = []
    for fmt, label in (("short", "ショート"), ("long", "横型")):
        cards = []
        for r in [r for r in rows if r["format"] == fmt]:
            media = (f"<video controls preload='metadata' src='{_u(r['mp4'])}'"
                     + (f" poster='{_u(r['thumb'])}'" if r["thumb"] else "") + "></video>") if r["mp4"] \
                else "<div class='body empty'>まだ書き出していません</div>"
            links = " ".join(x for x in (
                f"<a href='{_u(r['mp4'])}' download>動画ファイル</a>" if r["mp4"] else "",
                f"<a href='{_u(r['thumb'])}' target='_blank'>サムネイル</a>" if r["thumb"] else "",
                f"<a href='{_u(r['sheet'])}' target='_blank'>一覧画像</a>" if r["sheet"] else "") if x)
            title_full = r["title"] + (f" {r['tags']}" if fmt == "short" and r["tags"] else "")
            cards.append(
                f"<div class='card {fmt}'>{media}<div class='body'>"
                f"<div class='row'><span class='tag'>{_e(r['id'])}</span><span class='tag'>{_dur(r['dur'])}</span>"
                f"{_qc_tag(r['qc'])}</div>"
                f"{_field('タイトル', title_full)}"
                f"{_field('説明文', (r['desc'] + chr(10) + r['credit']).strip())}"
                f"{_field('ハッシュタグ', r['tags']) if fmt == 'long' else ''}"
                f"{_field('サムネイル文字', r['thumb_text']) if r['thumb_text'] else ''}"
                f"<div class='links'>{links}</div></div></div>")
        if cards:
            sections.append(f"<h2>{label}（{len(cards)}本）</h2><div class='grid {fmt}'>{''.join(cards)}</div>")
    # Lines whose speaker the analysis was unsure about: one click plays that moment.
    review_html = ""
    rv_p = os.path.join(wd, "speaker_review.json")
    if os.path.exists(rv_p):
        review = load_json(rv_p)
        rj = os.path.join(wd, "out", "render.json")
        times = {r["id"]: r.get("line_times", {}) for r in (load_json(rj) if os.path.exists(rj) else [])}
        items = []
        for r in review:
            t = times.get(r["clip"], {}).get(r["text"])
            link = (f"<a href='out/{_u(r['clip'])}.mp4#t={max(0, t - 0.5):.1f}' target='_blank'>▶ {_dur(t)}</a>"
                    if t is not None else "")
            col = st["short"]["speakers"].get(r["speaker"], "#ccc")
            items.append(f"<tr><td>{_e(r['clip'])}</td><td>{link}</td><td>{_e(r['text'])}</td>"
                         f"<td><span style='color:{col}'>{_e(names.get(r['speaker'], r['speaker']))}</span></td>"
                         f"<td>{int(r['conf'] * 100)}%</td></tr>")
        if items:
            review_html = (f"<details class='card' style='padding:10px 14px;margin-bottom:18px'><summary>"
                           f"話者の確認候補 {len(items)}行（自動判定の自信が低い行。違っていたら行を教えてください）"
                           f"</summary><table style='width:100%;margin-top:8px;font-size:13px'>"
                           f"<tr style='color:var(--sub)'><td>クリップ</td><td>位置</td><td>テロップ</td><td>判定</td>"
                           f"<td>自信</td></tr>{''.join(items)}</table></details>")
    # Lines whose timing estimates disagree by more than 2 s (W / C / original).
    tr_p = os.path.join(wd, "timing_report.json")
    if os.path.exists(tr_p):
        rj = os.path.join(wd, "out", "render.json")
        times = {r["id"]: r.get("line_times", {}) for r in (load_json(rj) if os.path.exists(rj) else [])}
        items = []
        for r in load_json(tr_p):
            if not r.get("early"):
                continue
            t = times.get(r["clip"], {}).get(r["text"])
            link = (f"<a href='out/{_u(r['clip'])}.mp4#t={max(0, t - 1.0):.1f}' target='_blank'>▶ {_dur(t)}</a>"
                    if t is not None else "")
            items.append(f"<tr><td>{_e(r['clip'])}</td><td>{link}</td><td>{_e(r['text'])}</td>"
                         f"<td>{r['early']:.1f}秒</td></tr>")
        if items:
            review_html += (f"<details class='card' style='padding:10px 14px;margin-bottom:18px'><summary>"
                            f"タイミングの確認候補 {len(items)}行（声が聞こえる前にテロップが出ている可能性。早い・遅いを教えてください）"
                            f"</summary><table style='width:100%;margin-top:8px;font-size:13px'>"
                            f"<tr style='color:var(--sub)'><td>クリップ</td><td>位置</td><td>テロップ</td><td>声より早い</td></tr>"
                            f"{''.join(items)}</table></details>")
    passed = sum(1 for r in rows if r["qc"] and r["qc"].get("pass"))
    info = "".join(f"<span>{k} <b>{_e(v)}</b></span>" for k, v in (
        ("配信者", pkg.get("streamer") or meta.get("uploader")), ("コラボ", pkg.get("collab")),
        ("ゲーム", pkg.get("game")), ("配信日", meta.get("upload_date")),
        ("合格", f"{passed}/{len(rows)}本")) if v)
    src = pkg.get("source_url") or meta.get("webpage_url")
    if src:
        info += f"<span><a href='{_e(src)}' target='_blank'>元配信を開く</a></span>"
    head = (f"<a class='crumb' href='../index.html'>← 一覧</a><h1>{_e(meta.get('title') or name)}</h1>"
            f"<span class='crumb'>{_e(name)}</span>")
    body = (banner + f"<div class='meta'>{info}</div>"
            + (f"<div class='legend'>字幕の色：{legend}</div>" if legend else "") + review_html + "".join(sections))
    with open(os.path.join(wd, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(_page(meta.get("title") or name, head, body, refresh=5 if banner else None))
    write_delivery(wd, meta, pkg, rows)
    return os.path.join(wd, "index.html")


def write_delivery(wd, meta, pkg, rows):
    if not any(r["title"] for r in rows):
        return
    lines = [f"# 納品メモ：{pkg.get('streamer', '')}「{meta.get('title', '')}」", "",
             f"元配信: {pkg.get('source_url', meta.get('webpage_url', ''))}",
             f"配信者: {pkg.get('streamer', '')}（{' ／ '.join(pkg.get('streamer_links') or [])}）"]
    if pkg.get("collab"):
        lines.append(f"コラボ: {pkg['collab']}")
    if pkg.get("game"):
        lines.append(f"ゲーム: {pkg['game']}")
    lines.append(f"（{time.strftime('%Y-%m-%d %H:%M')} に clips.src.yaml から自動生成）")
    for r in rows:
        kind = "ショート" if r["format"] == "short" else "横型"
        lines += ["", f"## {r['id']}.mp4（{kind} {_dur(r['dur'])}）",
                  f"- タイトル: {r['title']}" + (f" {r['tags']}" if r["format"] == "short" else "")]
        if r["format"] == "long":
            lines.append(f"- ハッシュタグ: {r['tags']}")
            if r["thumb"]:
                lines.append(f"- サムネイル: {r['id']}_thumb.jpg（{r['thumb_text']}）")
        lines += ["- 説明:", f"  - {r['desc']}", f"  - {r['credit']}"]
    names = pkg.get("speaker_names") or {}
    if names:
        lines += ["", "## 字幕の色", "- " + "／".join(f"{v}＝{k}" for k, v in names.items())]
    os.makedirs(os.path.join(wd, "out"), exist_ok=True)
    with open(os.path.join(wd, "out", "delivery.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def write_ready(wd):
    """Hand a finished stream to the publishing side: out/ready.json lists every clip with what an
    upload needs. Refuses (returns the reasons) unless every clip exists and passed qc, so a
    half-done stream is never published. The publishing side never edits this file; it records
    uploads in out/published.json."""
    from .common import load_json as _lj
    spec, pkg, rows = clip_rows(wd)
    problems = [f"{r['id']}: 書き出しなし" for r in rows if not r["mp4"]]
    problems += [f"{r['id']}: 品質チェック不合格または未実施" for r in rows if r["mp4"] and not (r["qc"] or {}).get("pass")]
    if not rows:
        problems.append("クリップがありません")
    if problems:
        return problems
    mp = os.path.join(wd, "meta.json")
    meta = _lj(mp) if os.path.exists(mp) else {}
    out = os.path.join(wd, "out")
    data = {
        "stream_title": meta.get("title"), "stream_date": meta.get("upload_date"),
        "source_url": pkg.get("source_url") or meta.get("webpage_url"),
        "streamer": pkg.get("streamer"), "streamer_links": pkg.get("streamer_links") or [],
        "collab": pkg.get("collab"), "game": pkg.get("game"),
        "made": time.strftime("%Y-%m-%d %H:%M"),
        "clips": [{
            "id": r["id"], "format": r["format"], "duration": round(r["dur"] or 0, 1),
            "file": os.path.join(out, f"{r['id']}.mp4"),
            "thumbnail": os.path.join(out, f"{r['id']}_thumb.jpg") if r["thumb"] else None,
            "title": r["title"], "description": r["desc"], "hashtags": r["tags"], "credit": r["credit"], "collab": r.get("collab"),
        } for r in rows],
    }
    with open(os.path.join(out, "ready.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    return []


def write_index(root):
    cards = []
    for n in sorted(os.listdir(root), reverse=True):
        wd = os.path.join(root, n)
        if not os.path.isdir(wd) or not os.path.exists(os.path.join(wd, "meta.json")):
            continue
        meta = load_json(os.path.join(wd, "meta.json"))
        spec, pkg, rows = clip_rows(wd)
        cover = next((r["thumb"] for r in rows if r["thumb"]), None) or next((r["sheet"] for r in rows if r["sheet"]), None)
        passed = sum(1 for r in rows if r["qc"] and r["qc"].get("pass"))
        shorts = sum(1 for r in rows if r["format"] == "short")
        prog = _progress(wd)
        state = (f"<span class='tag warn'>処理中 {int(prog.get('overall', 0) * 100)}%</span>"
                 if prog and not prog.get("result") else
                 (f"<span class='tag ok'>合格 {passed}/{len(rows)}本</span>" if rows else "<span class='tag'>未編集</span>"))
        img = f"<img src='{_u(n + '/' + cover)}'>" if cover else "<img>"
        cards.append(
            f"<a class='card vcard' href='{_u(n)}/index.html'>{img}<div class='body'>"
            f"<div class='title'>{_e(meta.get('title') or n)}</div>"
            f"<div class='row'><span class='tag'>{_e(pkg.get('streamer') or meta.get('uploader'))}</span>"
            f"<span class='tag'>{_e(meta.get('upload_date', ''))}</span>"
            f"<span class='tag'>ショート{shorts}・横型{len(rows) - shorts}</span>{state}</div>"
            f"<div class='crumb'>{_e(n)}</div></div></a>")
    body = "<div style='display:flex;flex-direction:column;gap:12px'>" + "".join(cards) + "</div>" if cards \
        else "<p class='empty'>まだ動画がありません。</p>"
    head = "<h1>切り抜き制作</h1><span class='crumb'>動画ごとのフォルダ一覧</span>"
    with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(_page("切り抜き制作", head, body))
    write_music(root)
    write_se(root)
    return os.path.join(root, "index.html")


def _lj(p, default=None):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _age(p):
    try:
        return time.time() - os.path.getmtime(p)
    except OSError:
        return None


def _ago(sec):
    if sec is None:
        return "—"
    sec = int(sec)
    return f"{sec}秒前" if sec < 60 else (f"{sec // 60}分前" if sec < 3600 else f"{sec // 3600}時間前")


def _gpu_busy():
    import tempfile
    path = os.path.join(tempfile.gettempdir(), "clipper_gpu.lock")
    if not os.path.exists(path):
        return False
    try:
        fh = open(path, "a+")
    except OSError:
        return True
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        return False
    except OSError:
        return True
    finally:
        fh.close()


def write_tasks(root):
    """One page for "what is running right now" plus where every stream is in the flow
    (prepare → edit → qc → ready → scheduled). Rebuilt on every request by `clipper serve`."""
    now = time.time()
    running, board = [], []
    plog = os.path.join(root, "prepare.log")
    pa = _age(plog)
    if pa is not None and pa < 600:
        last = ""
        try:
            with open(plog, encoding="utf-8", errors="replace") as fh:
                lines = [ln.strip() for ln in fh.readlines()[-30:] if ln.strip() and "Deprecated" not in ln]
            cur = next((ln for ln in reversed(lines) if ln.startswith("==")), "")
            last = (cur + " ／ " if cur else "") + (lines[-1] if lines else "")
        except OSError:
            pass
        running.append(("過去配信の準備（取得・文字起こし）", last, _ago(pa), "/prepare.log"))
    wlog = os.path.join(root, "_状況", "watch.log")
    wa = _age(wlog)
    if wa is not None and wa < 3600:
        try:
            with open(wlog, encoding="utf-8", errors="replace") as fh:
                wl = [ln.strip() for ln in fh.readlines()[-12:] if ln.strip() and "Deprecated" not in ln]
            running.append(("新着アーカイブの監視（20分ごと）", " ／ ".join(wl[-2:]), _ago(wa), "/_%E7%8A%B6%E6%B3%81/watch.log"))
        except OSError:
            pass
    if _gpu_busy():
        running.append(("GPU 使用中", "文字起こし・声の分離・品質チェックの聞き取りのどれかが動いています", "いま", ""))
    for note in (_lj(os.path.join(root, "_状況", "作業中.json"), {}) or {}).get("tasks", []):
        running.append((note.get("who", "作業"), note.get("what", ""), note.get("since", ""), note.get("link", "")))
    rec = _lj(os.path.join(root, "_投稿", "投稿記録.json"), {}) or {}
    ra = _age(os.path.join(root, "_投稿", "投稿記録.json"))
    if ra is not None and ra < 1800:
        running.append(("YouTube 予約投稿（投稿担当）", f"記録済み {len(rec.get('videos') or [])}本", _ago(ra), "/_投稿/"))
    holds = (_lj(os.path.join(root, "_投稿", "hold.json"), {}) or {}).get("hold", [])
    published = {}
    for v in rec.get("videos") or []:
        published.setdefault(v.get("stream"), []).append(v)
    for n in sorted(os.listdir(root), reverse=True):
        wd = os.path.join(root, n)
        if not os.path.isdir(wd) or n.startswith("_") or not os.path.exists(os.path.join(wd, "meta.json")):
            continue
        meta = _lj(os.path.join(wd, "meta.json"), {}) or {}
        prog = _lj(os.path.join(wd, "progress.json"))
        pg = _age(os.path.join(wd, "progress.json"))
        if prog and not prog.get("result") and pg is not None and pg < 900:
            step = next((s for s in prog.get("steps", []) if s.get("state") == "run"), {})
            running.append((f"{prog.get('title') or n}", f"{step.get('label', '')} ／ 全体 {int(prog.get('overall', 0) * 100)}%",
                            _ago(pg), f"/{_u(n)}/progress.html"))
        qc = _lj(os.path.join(wd, "out", "qc.json"), []) or []
        passed = sum(1 for r in qc if r.get("pass"))
        ready = os.path.exists(os.path.join(wd, "out", "ready.json"))
        pub = published.get(n, [])
        held = any(n.startswith(h.get("stream_prefix", "~")) for h in holds)
        if not os.path.exists(os.path.join(wd, "transcript.json")):
            stage, cls = "準備中", "warn"
        elif not os.path.exists(os.path.join(wd, "clips.src.yaml")):
            stage, cls = "編集待ち", ""
        elif not ready:
            stage, cls = ("編集中" if passed < len(qc) or not qc else "確認待ち"), "warn"
        elif held:
            stage, cls = "投稿保留", "ng"
        elif pub:
            stage, cls = f"予約済み {len(pub)}本", "ok"
        else:
            stage, cls = "投稿待ち", "ok"
        nxt = min((v.get("scheduled_at", "") for v in pub if v.get("scheduled_at")), default="")
        board.append(f"<tr><td>{_e(meta.get('upload_date', ''))}</td><td><a href='/{_u(n)}/index.html'>{_e(meta.get('title') or n)}</a></td>"
                     f"<td><span class='tag {cls}'>{_e(stage)}</span></td><td>{passed}/{len(qc)}</td>"
                     f"<td>{_e(nxt[5:16].replace('T', ' ') if nxt else '—')}</td></tr>")
    run_html = "".join(f"<div class='card' style='padding:10px 14px;margin-bottom:8px'><div class='row'><b>{_e(a)}</b>"
                       f"<span class='crumb'>{_e(c)}</span>" + (f"<a href='{_e(d)}'>詳細</a>" if d else "") +
                       f"</div><div class='crumb'>{_e(b)}</div></div>" for a, b, c, d in running) \
        or "<p class='empty'>いま動いている処理はありません。</p>"
    queue = _lj(os.path.join(root, "_投稿", "queue.json"), []) or []
    done_ids = {(v.get("stream"), v.get("clip")) for v in rec.get("videos") or []}
    soon = sorted([q for q in queue if q.get("scheduled_at")], key=lambda q: q["scheduled_at"])[:20]
    q_html = "".join(f"<tr><td>{_e(q['scheduled_at'][5:16].replace('T', ' '))}</td><td>{'ショート' if q.get('format') == 'short' else '横型'}</td>"
                     f"<td>{_e(q.get('title'))}</td><td><span class='tag {'ok' if (q.get('stream'), q.get('clip')) in done_ids else ''}'>"
                     f"{'予約済み' if (q.get('stream'), q.get('clip')) in done_ids else '予定'}</span></td></tr>" for q in soon)
    hold_html = "".join(f"<div class='banner'>保留: {_e(h.get('stream_prefix'))} — {_e(h.get('reason'))}</div>" for h in holds)
    eq = _lj(os.path.join(root, "_状況", "編集待ち.json"), {}) or {}
    eq_rows = [(x, "新着", "ok") for x in eq.get("fresh", [])] + [(x, "ストック", "") for x in eq.get("stock", [])]
    eq_html = ("<h2>編集待ちリスト（新着が先、ストックはその後）</h2><table class='tbl'><tr><th>順</th><th>区分</th><th>配信日</th><th>配信</th><th>準備</th></tr>"
               + "".join(f"<tr><td>{i + 1}</td><td><span class='tag {c}'>{k}</span></td><td>{_e(x.get('date'))}</td>"
                         f"<td>{_e(x.get('title'))}</td><td>{'済' if x.get('prepared') else '準備中'}</td></tr>"
                         for i, (x, k, c) in enumerate(eq_rows[:12])) + "</table>") if eq_rows else ""
    body = (f"<h2>いま動いている処理</h2>{run_html}{hold_html}{eq_html}"
            "<h2>配信ごとの段階（準備 → 編集 → 品質チェック → 投稿待ち → 予約）</h2>"
            "<table class='tbl'><tr><th>配信日</th><th>配信</th><th>段階</th><th>合格</th><th>最初の公開予定</th></tr>"
            + "".join(board) + "</table>"
            + (f"<h2>予約投稿の予定（早い順）</h2><table class='tbl'><tr><th>公開日時</th><th>形式</th><th>タイトル</th><th>状態</th></tr>{q_html}</table>"
               if q_html else ""))
    head = f"<h1>動いているタスク</h1><span class='crumb'>{time.strftime('%H:%M:%S')} 時点・10秒ごとに自動更新</span>"
    css = ("<style>.tbl{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line)}"
           ".tbl td,.tbl th{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;font-size:13px}"
           ".tbl th{color:var(--sub);font-weight:600}</style>")
    out = os.path.join(root, "tasks.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(_page("動いているタスク", head, css + body, refresh=10, active="tasks.html"))
    return out


def write_music(root):
    """The music list: <root>/_素材/BGM/曲リスト.yaml (the single source) → music.html and 曲リスト.md.
    Songs are grouped by the situation they fit, each with a player, its key for clips.src.yaml,
    the point where it gets going, and its license."""
    src = os.path.join(root, "_素材", "BGM", "曲リスト.yaml")
    if not os.path.exists(src):
        return None
    doc = load_yaml(src) or {}
    sits, songs, reqs = doc.get("situations") or [], doc.get("songs") or [], doc.get("requests") or []
    by = {}
    for s in songs:
        by.setdefault(s.get("situation"), []).append(s)

    def rel(p):
        p = str(p).replace("\\", "/")
        r = root.replace("\\", "/").rstrip("/") + "/"
        return "/" + _u(p[len(r):]) if p.startswith(r) else ""

    def sec(v):
        return f"{int(v) // 60}:{int(v) % 60:02d}" if v is not None else "—"
    parts = ["<div class='banner'>編集で使ってよい曲の一覧です（場面ごと）。<b>key</b> を clips.src.yaml の "
             "<code>bgm:</code> や <code>bgm_switch: {bgm: …}</code> に書くと使えます。音量は曲ごとに自動でそろいます。"
             "曲を足したら <code>_素材/BGM/曲リスト.yaml</code> に追記し、<code>python -m clipper site</code> で"
             "このページと 曲リスト.md を作り直します（追記は義務）。</div>",
             "<pre class='code'>bgm: chill_223am            # 土台の曲（key）\nbgm_offset: 12              # 曲の盛り上がり位置から始める（秒）\n"
             "bgm_switch: {at: 5123.4, bgm: dotabata_party}   # 山場（元配信の秒）から切り替え</pre>"]
    md = ["# 曲リスト（場面別）", "",
          "編集で使ってよい曲の一覧。ここは `曲リスト.yaml` から自動生成される（直接編集しない）。",
          "曲を足したら `曲リスト.yaml` に追記して `python -m clipper site` を実行する（追記は義務）。", "",
          "使い方: clips.src.yaml に `bgm: <key>`、山場で切り替えるなら `bgm_switch: {at: <元配信の秒>, bgm: <key>}`、"
          "曲の盛り上がりから始めるなら `bgm_offset: <秒>`。", ""]
    for st in sits:
        lst = by.get(st["key"], [])
        parts.append(f"<section class='sit' id='{_e(st['key'])}'><div class='h'><b>{_e(st['name'])}</b>"
                     f"<div>{_e(st.get('when'))}</div><div>使いどころ: {_e(st.get('use'))}</div></div>")
        md += [f"## {st['name']}", "", f"- 場面: {st.get('when')}", f"- 使いどころ: {st.get('use')}", "",
               "| key | 曲名 / 作曲 | 向いている場面 | 盛り上がり | 長さ | メモ |", "|---|---|---|---|---|---|"]
        for s in lst:
            a = rel(s.get("file", ""))
            hook = s.get("hook_sec")
            only = ("<span class='tag warn'>ショート専用</span>" if s.get("shorts_only") else "") + \
                ("<span class='tag'>横型の土台OK</span>" if s.get("long_base") else "<span class='tag'>スポット用（横型は bgm_spots で）</span>")
            where = (f"<a href='{_e(s.get('page'))}' target='_blank'>配布ページ</a>" if s.get("page")
                     else f"<span>{_e(s.get('source'))}</span>")
            player = f"<audio controls preload='none' src='{a}'></audio>" if a else ""
            jump = (f"<button class='copy' style='position:static' onclick=\"const au=this.parentElement."
                    f"querySelector('audio');au.currentTime={hook};au.play()\">盛り上がりから再生</button>"
                    if a and hook else "")
            parts.append(
                f"<div class='song'><div><div class='row'><span class='title'>{_e(s['title'])}</span>"
                f"<span class='crumb'>{_e(s.get('artist'))}</span>"
                f"<span class='tag k' title='clips.src.yaml に書く名前'>{_e(s['key'])}</span>{only}</div>"
                f"<div>{_e(s.get('scenes'))}</div><div class='crumb'>{_e(s.get('note'))}</div>"
                f"<div class='links'><span>盛り上がり {sec(hook)}</span><span>長さ {sec(s.get('duration'))}</span>"
                f"<span>音量補正 {s.get('gain_db', 0):+}dB</span>{where}"
                f"<span>{_e(s.get('license'))}</span></div></div>"
                f"<div style='min-width:260px'>{player}{jump}</div></div>")
            md.append(f"| `{s['key']}` | {s['title']} / {s.get('artist')} | {s.get('scenes')} | {sec(hook)} | "
                      f"{sec(s.get('duration'))} | {'【ショート専用】' if s.get('shorts_only') else ''}{'【横型の土台OK】' if s.get('long_base') else '【スポット用】'}{s.get('note')} |")
        if not lst:
            parts.append("<div class='song empty'>まだ曲がありません</div>")
        parts.append("</section>")
        md.append("")
    if reqs:
        parts.append("<h2>オーナーに音源提供を依頼中の曲</h2><div class='sit'>" + "".join(
            f"<div class='song'><div><div class='row'><span class='title'>{_e(r['title'])}</span>"
            f"<span class='crumb'>{_e(r.get('artist'))}</span></div><div>{_e(r.get('scenes'))}</div>"
            f"<div class='crumb'>{_e(r.get('why'))}</div></div><div class='tag warn'>{_e(r.get('status'))}</div></div>"
            for r in reqs) + "</div>")
        md += ["## オーナーに音源提供を依頼中の曲", "", "| 曲名 | アーティスト | 使いたい場面 | 状況 |", "|---|---|---|---|"]
        md += [f"| {r['title']} | {r.get('artist')} | {r.get('scenes')} | {r.get('status')} |" for r in reqs]
        md.append("")
    md += ["## 方針", "",
           "- 曲は配布元の利用条件を確認してから使う（作曲者ごとの追加条件は 曲リスト.yaml の artist_terms）。",
           "- ショートの権利もの楽曲は、作曲者が明確に禁止していない限り使ってよい（オーナー判断 2026-11-22。"
           "Content ID の申し立ては収益が権利者に回る扱いとして許容）。申し立ての結果は投稿担当が published.json に記録する。",
           "- 【ショート専用】の曲（権利もの）は横型に使わない。横型は申し立てで地域ブロックされると流入が止まるため。",
           "- 歌入りの曲は声とぶつかるので、セリフの少ない山場（転）や締めに使う。",
           "- Claude が入手できない曲はオーナーに依頼する（上の表）。届いた音源は files/ に置き、曲リスト.yaml に追記する。", ""]
    with open(os.path.join(root, "_素材", "BGM", "曲リスト.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    head = f"<h1>曲リスト</h1><span class='crumb'>{len(songs)}曲・場面別（{_e(doc.get('updated', ''))} 更新）</span>"
    out = os.path.join(root, "music.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(_page("曲リスト", head, "".join(parts), active="music.html"))
    return out


def write_se(root):
    """The SE list: <root>/_素材/SE/効果音リスト.yaml (the single source) → se.html and 効果音リスト.md."""
    src = os.path.join(root, "_素材", "SE", "効果音リスト.yaml")
    if not os.path.exists(src):
        return None
    doc = load_yaml(src) or {}
    cats, sounds = doc.get("categories") or {}, doc.get("sounds") or []
    by = {}
    for x in sounds:
        by.setdefault(x.get("cat"), []).append(x)
    r = root.replace("\\", "/").rstrip("/") + "/"

    def rel(path):
        path = str(path).replace("\\", "/")
        return "/" + _u(path[len(r):]) if path.startswith(r) else ""
    parts = ["<div class='banner'>効果音の一覧です（場面ごと）。自動の効果音は場面ごとにこの中から毎回違う音が選ばれます。"
             "手で置くときは clips.src.yaml のクリップに <code>se: [{at: 元配信秒, cat: fail}]</code>（カテゴリから自動で選ぶ）"
             "か <code>{at: …, key: fail_tin1}</code>（音を指定）。<b>効果音は適量に</b>（ショートは1分に6個まで・3秒以上あける）。"
             "出典: 効果音ラボ（収益化OK・クレジット不要。ファイルの再配布と、効果音を紹介する動画は禁止）。</div>"]
    md = ["# 効果音リスト", "", "元データは 効果音リスト.yaml（このファイルは python -m clipper site で作り直す）。", "",
          "- 自動: ズーム→whoosh、叫び(!)→surprise、強調(*)→pop、読み上げ→read、ショートの最初の keep→impact。カテゴリ内で毎回違う音。",
          "- 手動: `se: [{at: <元配信秒>, cat: <カテゴリ>}]` または `{at: …, key: <key>}`。効果音は適量に（ショートは1分に6個まで、3秒以上あける）。",
          "- 出典: 効果音ラボ https://soundeffect-lab.info/ （収益化OK・クレジット不要。再配布・効果音を紹介する動画・Content ID 登録は禁止）。", ""]
    for cat, use in cats.items():
        items = by.get(cat) or []
        parts.append(f"<h2>{_e(cat)} — {_e(use)}（{len(items)}）</h2>")
        md += [f"## {cat} — {use}", "", "| key | 音 | 秒 |", "|---|---|---|"]
        for x in items:
            parts.append(f"<div class='song'><b>{_e(x.get('title', ''))}</b> <code>{_e(x['key'])}</code> "
                         f"{_e(x.get('sec', ''))}秒 <audio controls preload='none' src='{rel(x.get('file', ''))}'></audio></div>")
            md.append(f"| {x['key']} | {x.get('title', '')} | {x.get('sec', '')} |")
        md.append("")
    with open(os.path.join(root, "_素材", "SE", "効果音リスト.md"), "w", encoding="utf-8") as fh:
        fh.write(chr(10).join(md))
    head = f"<h1>効果音</h1><span class='crumb'>{len(sounds)}種・場面別</span>"
    out = os.path.join(root, "se.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(_page("効果音", head, "".join(parts), active="se.html"))
    return out


def refresh(wd):
    """Rebuild this video's page and the root index. Never raises: pages are a convenience."""
    try:
        write_video_page(wd)
        write_index(os.path.dirname(os.path.abspath(wd)))
    except Exception as e:  # noqa: BLE001
        print(f"  ページの更新に失敗（処理は続行）: {e}")
