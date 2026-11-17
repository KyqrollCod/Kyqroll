"""LP/HP diagnosis report tool (Coconala listing D, skill §2b).

Two steps, so Claude writes the judgement and the script does the mechanics:

  python scripts/diagnose.py collect <url-or-path> <out_dir>
      -> out_dir/sp.png (390px), pc.png (1280px), facts.json (page facts with element boxes)

  (Claude writes out_dir/findings.json, see FINDINGS_EXAMPLE below)

  python scripts/diagnose.py render <out_dir> [--title "..."] [--client "..."] [--page "label instead of URL"]
      -> out_dir/report.html and out_dir/report.pdf (A4), with numbered marks on the screenshots

findings.json:
[
  {"title": "最初の画面で何の教室か分からない", "why": "...", "how": "...",
   "view": "sp", "box": [x, y, w, h]},      # box in screenshot pixels; omit "box" for no mark
  ...
]
"""
import html
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

VIEWS = {"sp": (390, 844), "pc": (1280, 800)}

FACTS_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const box = el => { const r = el.getBoundingClientRect();
    return [Math.round(r.left + scrollX), Math.round(r.top + scrollY), Math.round(r.width), Math.round(r.height)]; };
  const txt = el => (el.innerText || el.value || el.alt || '').trim().replace(/\s+/g, ' ').slice(0, 120);
  const heads = [...document.querySelectorAll('h1,h2,h3')].filter(vis).map(e => ({tag: e.tagName, text: txt(e), box: box(e)}));
  const ctas = [...document.querySelectorAll('a,button,input[type=submit]')].filter(vis)
    .filter(e => /申込|申し込|予約|体験|相談|問い合わせ|お問合せ|LINE|無料|応募|購入|登録/.test(txt(e)))
    .map(e => ({text: txt(e), href: e.href || '', box: box(e)}));
  const small = [...document.querySelectorAll('p,li,span,a,td,dd,dt')].filter(vis)
    .filter(e => e.childElementCount === 0 && txt(e).length > 8 && parseFloat(getComputedStyle(e).fontSize) < 14)
    .slice(0, 15).map(e => ({text: txt(e), size: getComputedStyle(e).fontSize, box: box(e)}));
  const imgsNoAlt = [...document.images].filter(vis).filter(i => !i.alt).length;
  const priceHits = (document.body.innerText.match(/[0-9０-９,，]+\s*円/g) || []).slice(0, 10);
  const firstView = [...document.querySelectorAll('h1,h2,h3,p,a,button')].filter(vis)
    .filter(e => e.getBoundingClientRect().top < innerHeight).map(txt).filter(Boolean).slice(0, 15);
  return {
    title: document.title, url: location.href, viewport: [innerWidth, innerHeight],
    pageHeight: document.documentElement.scrollHeight,
    horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
    headings: heads, ctas, smallText: small, imagesWithoutAlt: imgsNoAlt, prices: priceHits,
    firstViewText: firstView, hasViewportMeta: !!document.querySelector('meta[name=viewport]'),
    telLinks: document.querySelectorAll('a[href^="tel:"]').length,
  };
}
"""


def collect(src: str, out: pathlib.Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    url = src if src.startswith(("http://", "https://")) else pathlib.Path(src).resolve().as_uri()
    facts = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, (w, h) in VIEWS.items():
            pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
            pg.goto(url, wait_until="networkidle", timeout=60000)
            pg.wait_for_timeout(800)
            pg.screenshot(path=str(out / f"{name}.png"), full_page=True)
            facts[name] = pg.evaluate(FACTS_JS)
            pg.close()
        b.close()
    (out / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, f in facts.items():
        print(f"{name}: height={f['pageHeight']} overflow={f['horizontalOverflow']} "
              f"headings={len(f['headings'])} ctas={len(f['ctas'])} small={len(f['smallText'])}")


CSS = """
@page{size:A4;margin:14mm 12mm}
*{box-sizing:border-box}
body{font-family:"Noto Sans JP","Yu Gothic","Meiryo",sans-serif;color:#2f2a26;font-size:10.5pt;line-height:1.7;margin:0}
h1{font-size:20pt;margin:0 0 4mm}
.meta{color:#6b625a;margin-bottom:6mm}
.summary{background:#fbf6ee;border:1px solid #e8dccb;border-radius:3mm;padding:4mm 5mm;margin-bottom:6mm}
.item{break-inside:avoid;border-left:2mm solid #3f7a5c;padding:1mm 0 1mm 4mm;margin:0 0 5mm}
.item h2{font-size:12.5pt;margin:0 0 1mm}
.num{display:inline-block;width:7mm;height:7mm;border-radius:50%;background:#c8553d;color:#fff;text-align:center;
     line-height:7mm;font-size:10pt;margin-right:2mm}
.lbl{font-weight:700;color:#3f7a5c}
.slice{break-before:page;break-inside:avoid}
.shot{position:relative;margin:0 auto;border:1px solid #ccc}
.shot img{display:block;max-width:none}
.mark{position:absolute;border:3px solid #c8553d;border-radius:8px}
.mark span{position:absolute;left:-12px;top:-12px;width:24px;height:24px;border-radius:50%;background:#c8553d;
           color:#fff;font-size:13px;font-weight:700;text-align:center;line-height:24px}
.cap{font-weight:700;margin:2mm 0}
.foot{color:#6b625a;font-size:9pt;margin-top:6mm}
"""


def render(out: pathlib.Path, title: str, client: str, page_label: str = "") -> None:
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    facts = json.loads((out / "facts.json").read_text(encoding="utf-8"))
    e = html.escape
    items = "".join(
        f'<div class="item"><h2><span class="num">{i}</span>{e(f["title"])}</h2>'
        f'<div><span class="lbl">なぜ：</span>{e(f["why"])}</div>'
        f'<div><span class="lbl">どう直す：</span>{e(f["how"])}</div></div>'
        for i, f in enumerate(findings, 1))
    shots = ""
    usable_mm = 240  # image height that fits one A4 page with the caption
    for view, label, width_mm in (("sp", "スマホ（幅390px）", 95), ("pc", "PC（幅1280px）", 186)):
        w_px = VIEWS[view][0]
        total = facts[view]["pageHeight"]
        mm_per_px = width_mm / w_px
        slice_px = int(usable_mm / mm_per_px)
        starts = list(range(0, total, slice_px))
        for n, top in enumerate(starts, 1):
            h = min(slice_px, total - top)
            marks = ""
            for i, f in enumerate(findings, 1):
                if f.get("view") != view or not f.get("box"):
                    continue
                x, y, bw, bh = f["box"]
                if not (top <= y < top + h):
                    continue
                bh = min(bh, top + h - y)
                marks += (f'<div class="mark" style="left:{x*mm_per_px:.1f}mm;top:{(y-top)*mm_per_px:.1f}mm;'
                          f'width:{bw*mm_per_px:.1f}mm;height:{bh*mm_per_px:.1f}mm"><span>{i}</span></div>')
            part = f"（{n}/{len(starts)}）" if len(starts) > 1 else ""
            shots += (f'<div class="slice"><div class="cap">{label}{part}</div>'
                      f'<div class="shot" style="width:{width_mm}mm;height:{h*mm_per_px:.1f}mm;overflow:hidden">'
                      f'<img src="{view}.png" style="width:{width_mm}mm;margin-top:-{top*mm_per_px:.1f}mm">{marks}</div></div>')
    page = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>{e(title)}</title>
<style>{CSS}</style></head><body>
<h1>{e(title)}</h1>
<div class="meta">{e(client)}　対象ページ：{e(page_label or facts['sp']['url'])}</div>
<div class="summary">改善点を、申込への影響が大きい順に{len(findings)}個まとめました。番号は、後半の画面画像の印と対応しています。
上から順に直すと、少ない手間で効果が出やすくなります。</div>
{items}
<div class="shots">{shots}</div>
<div class="foot">このレポートは改善のご提案です。申込数の増加をお約束するものではありません。
画面の確認・分析・文章の作成に生成AIを活用し、内容を確認したうえでお届けしています。</div>
</body></html>"""
    (out / "report.html").write_text(page, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto((out / "report.html").resolve().as_uri(), wait_until="networkidle")
        pg.pdf(path=str(out / "report.pdf"), format="A4", print_background=True,
               margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
        b.close()
    print("report.pdf written,", len(findings), "findings")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "collect" and len(sys.argv) == 4:
        collect(sys.argv[2], pathlib.Path(sys.argv[3]))
    elif cmd == "render" and len(sys.argv) >= 3:
        args = sys.argv[3:]
        opt = {k: v for k, v in zip(args[::2], args[1::2])}
        render(pathlib.Path(sys.argv[2]), opt.get("--title", "ページ診断レポート"), opt.get("--client", ""), opt.get("--page", ""))
    else:
        print(__doc__)
        sys.exit(1)
