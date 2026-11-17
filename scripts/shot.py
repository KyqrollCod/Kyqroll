"""Screenshot an LP at phone (390x844) and PC (1280x800) widths, full page.
Usage: python scripts/shot.py <path/to/index.html | https://url> <out_dir>"""
import sys, pathlib
from playwright.sync_api import sync_playwright
arg = sys.argv[1]
src = arg if arg.startswith(("http://", "https://")) else pathlib.Path(arg).resolve().as_uri()
out = pathlib.Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    for name, w, h in (("sp", 390, 844), ("pc", 1280, 800)):
        pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        pg.goto(src); pg.wait_for_load_state("networkidle")
        overflow = pg.evaluate("document.documentElement.scrollWidth > innerWidth")
        pg.screenshot(path=str(out / f"{name}.png"), full_page=True)
        print(f"{name} {w}px ok, horizontal overflow={overflow}")
        pg.close()
    b.close()
