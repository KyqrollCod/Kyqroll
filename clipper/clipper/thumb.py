"""Thumbnail in the genre's proven shape: huge outlined text band, key word in red 『』, framed."""
import io
import subprocess
import os
import re

from PIL import Image, ImageDraw, ImageFont

from .common import fonts_dir, need


def grab_frame(src, t):
    p = subprocess.run([need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", src,
                        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], stdout=subprocess.PIPE, check=True)
    return Image.open(io.BytesIO(p.stdout)).convert("RGB")


def _cover(img, W, H):
    r = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * r + 0.5), int(img.height * r + 0.5)), Image.LANCZOS)
    x, y = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((x, y, x + W, y + H))


def _runs(text):
    """Split 'バケモノ役満『ドラ一色』' into [(text, is_key)]: the word inside 『』 is the key."""
    out, pos = [], 0
    for m in re.finditer(r"『([^』]+)』", text):
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out += [("『", False), (m.group(1), True), ("』", False)]
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out


def lift_dark(img, target=105.0, max_gain=2.2):
    """Night levels and horror games give near-black frames that vanish in a feed. When the mean
    luminance is low, brighten toward `target` (gamma-like, so highlights do not clip first)."""
    import math
    from PIL import ImageStat
    mean = ImageStat.Stat(img.convert("L")).mean[0]
    if mean >= target * 0.8:
        return img
    goal = min(target, mean * max_gain)
    # Pure gamma: 255 stays 255 and bright HUD/faces compress instead of clipping to white.
    gamma = max(0.35, math.log(goal / 255) / math.log(max(mean, 1.0) / 255))
    lut = [int(255 * (i / 255) ** gamma + 0.5) for i in range(256)]
    return img.point(lut * 3)


STYLES = ("band", "bottom", "punch", "avatar", "zoom", "bubble")


def _pick(salt, seed, n_items, step=1):
    """Pick for seed "<stream>:<clip id>": a per-stream start plus the clip number, so the long videos
    of one stream never share a style/palette/font, and streams start at different places."""
    import re
    stream, _, cid = str(seed).rpartition(":")
    n = int(re.sub(r"\D", "", cid) or 0)
    return (_h(f"{salt}:{stream or seed}") + n * step) % n_items


def _h(s):
    """Independent, well-spread picks per salt (crc32 of salt+seed is linear, so picks correlated)."""
    import hashlib
    return int(hashlib.md5(str(s).encode("utf-8")).hexdigest()[:8], 16)


def design(st, seed="", font=None, palette=None):
    """Font file + colour palette for a thumbnail. Each is picked from the clip id with its own salt,
    so layout, typeface and colours vary independently (owner 2026-11-23: 色合いやフォントも色々)."""
    th, fonts = st["thumbnail"], st.get("fonts") or {}
    pals = th.get("palettes") or {"classic": {}}
    auto = [k for k in th.get("auto_palettes") or sorted(pals) if k in pals]
    pk = palette if palette in pals else auto[_pick("pal", seed, len(auto), 3)]
    cands = th.get("fonts") or ["dela"]
    fk = font if font in fonts else cands[_pick("font", seed, len(cands), 2)]
    ffile = (fonts.get(fk) or [st["font_impact_file"]])[0]
    p = {"text": "#FFFFFF", "key": "#FF4040", "stroke": "#000000", "accent": "#FFE600", "accent2": "#FF2020",
         "band": "#000000", **(pals.get(pk) or {})}
    return {"font": os.path.join(fonts_dir(st), ffile), "font_key": fk, "palette": pk, **p}


def make_thumbnail(src, t, text, st, out_path, sticker=None, style=None, avatar=None, focus=None, seed="",
                   font=None, palette=None):
    """Several proven thumbnail shapes so a channel's grid isn't one pattern (owner 2026-11-23).
    style: band (top band, the original) / bottom (slanted band bottom-left) / punch (huge tilted
    text, no band) / avatar (streamer art left, text right) / zoom (zoomed frame, caption boxes) /
    bubble (speech bubble). Unset: picked from the clip id so neighbours differ."""
    style = style or STYLES[_pick("style", seed, len(STYLES))]
    if style == "avatar" and not (avatar and os.path.exists(avatar)):
        style = "punch"
    dz = design(st, seed, font, palette)
    if style != "band":
        return _styled(src, t, text, st, out_path, style, avatar, focus, dz)
    text = str(text).replace("\\n", "").replace("\n", "")
    th = st["thumbnail"]
    W, H = th["size"]
    img = _cover(lift_dark(grab_frame(src, t)), W, H)
    d = ImageDraw.Draw(img)
    bh = th["band_h"]
    th = {**th, "band_color": dz["band"], "text_color": dz["text"], "key_color": dz["key"],
          "stroke_color": dz["stroke"], "border_colors": [dz["accent2"], dz["accent"]]}
    d.rectangle([0, 0, W, bh], fill=th["band_color"])
    font_path = dz["font"]
    runs = _runs(text)
    size = int(bh * 0.86)
    while size > 40:
        f = ImageFont.truetype(font_path, size)
        width = sum(d.textlength(s, font=f) for s, _ in runs) + th["stroke"] * 2
        if width <= W - 30:
            break
        size -= 4
    f = ImageFont.truetype(font_path, size)
    x = (W - sum(d.textlength(s, font=f) for s, _ in runs)) / 2
    y = (bh - size) / 2 - size * 0.08
    for s, key in runs:
        d.text((x, y), s, font=f, fill=th["key_color"] if key else th["text_color"],
               stroke_width=th["stroke"], stroke_fill=th["stroke_color"])
        x += d.textlength(s, font=f)
    c1, c2 = th["border_colors"]
    d.rectangle([0, bh, W, bh + 8], fill=c2)
    d.rectangle([0, bh + 8, W, bh + 12], fill=c1)
    d.rectangle([0, 0, W - 1, H - 1], outline=c1, width=8)
    if sticker and os.path.exists(sticker):
        sk = Image.open(sticker).convert("RGBA")
        r = (H * 0.55) / sk.height
        sk = sk.resize((int(sk.width * r), int(sk.height * r)), Image.LANCZOS)
        img.paste(sk, (W - sk.width - 10, H - sk.height - 10), sk)
    img.save(out_path, quality=95)
    return out_path


_FONT = {"path": None}


def _font(st, size):
    return ImageFont.truetype(_FONT["path"] or os.path.join(fonts_dir(st), st["font_impact_file"]), size)


def _rgba(hexc, a):
    h = hexc.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def _lw(d, ln, f):
    return sum(d.textlength(s, font=f) for s, _ in _runs(ln))


def _fit_lines(d, st, lines, max_w, max_h, start=200):
    size = start
    while size > 36:
        f = _font(st, size)
        if max(_lw(d, ln, f) for ln in lines) <= max_w and size * 1.12 * len(lines) <= max_h:
            return f, size
        size -= 4
    return _font(st, size), size


def _draw_lines(d, lines, f, size, x0, y0, colors=("#FFFFFF", "#FF4040"), stroke=14, stroke_fill="#000000"):
    y = y0
    for ln in lines:
        x = x0
        for s, key in _runs(ln):
            d.text((x, y), s, font=f, fill=colors[1] if key else colors[0], stroke_width=stroke, stroke_fill=stroke_fill)
            x += d.textlength(s, font=f)
        y += size * 1.12


def _split2(line):
    """One long line → two, breaking before the 『key』 when there is one, else in the middle."""
    k, e = line.find("『"), line.find("』")
    if 2 < k < len(line) - 2:
        cut = k
    elif 0 <= e < len(line) - 2:
        cut = e + 1
    else:
        cut = len(line) // 2
        while cut < len(line) - 1 and line[cut] in "』」）！？ー〜、。ゃゅょっャュョッ":
            cut += 1
    return [line[:cut], line[cut:]]


def _styled(src, t, text, st, out_path, style, avatar, focus, dz):
    from PIL import ImageEnhance, ImageFilter
    _FONT["path"] = dz["font"]
    TX, KY, SK, AC = dz["text"], dz["key"], dz["stroke"], dz["accent"]
    W, H = st["thumbnail"]["size"]
    frame = lift_dark(grab_frame(src, t))
    lines = [x for x in str(text).replace("\\n", "\n").split("\n") if x.strip()] or [str(text)]
    if len(lines) == 1 and len(lines[0]) > 9 and style in ("punch", "avatar", "bubble"):
        lines = _split2(lines[0])
    if style == "zoom":
        fx, fy = focus or (0.5, 0.45)
        cw, ch = int(frame.width / 1.55), int(frame.height / 1.55)
        x = int(min(max(0, frame.width * fx - cw / 2), frame.width - cw))
        y = int(min(max(0, frame.height * fy - ch / 2), frame.height - ch))
        frame = frame.crop((x, y, x + cw, y + ch))
    img = _cover(frame, W, H)
    if style in ("punch", "bubble"):   # quiet the background so the words pop
        img = ImageEnhance.Brightness(img).enhance(0.72)
    d = ImageDraw.Draw(img, "RGBA")
    if style == "bottom":
        bh = 210
        d.polygon([(0, H - bh - 30), (int(W * 0.74), H - bh), (int(W * 0.70), H), (0, H)], fill=_rgba(dz["band"], 225))
        d.polygon([(0, H - bh - 42), (int(W * 0.745), H - bh - 12), (int(W * 0.74), H - bh), (0, H - bh - 30)],
                  fill=AC)
        f, size = _fit_lines(d, st, lines[:2], int(W * 0.62), bh - 30, 150)
        _draw_lines(d, lines[:2], f, size, 34, H - bh - 4, colors=(TX, KY), stroke=10, stroke_fill=SK)
    elif style == "punch":
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dl = ImageDraw.Draw(layer)
        f, size = _fit_lines(dl, st, lines[:2], int(W * 0.86), int(H * 0.62), 230)
        _draw_lines(dl, lines[:2], f, size, 60, int(H * 0.14), colors=(TX, KY), stroke=16, stroke_fill=SK)
        layer = layer.rotate(4, resample=Image.BICUBIC, center=(W // 2, H // 2))
        img.paste(layer, (0, 0), layer)
        d = ImageDraw.Draw(img, "RGBA")
        d.rectangle([0, 0, W - 1, H - 1], outline=AC, width=10)
    elif style == "avatar":
        art = Image.open(avatar).convert("RGBA")
        r = (H * 1.05) / art.height
        art = art.resize((int(art.width * r), int(art.height * r)), Image.LANCZOS)
        halo = Image.new("RGBA", art.size, _rgba(AC, 0))
        halo.putalpha(art.split()[3].filter(ImageFilter.GaussianBlur(14)).point(lambda a: min(255, a * 2)))
        pos = (-int(art.width * 0.18), H - art.height + 40)
        img.paste(halo, pos, halo)
        img.paste(art, pos, art)
        d = ImageDraw.Draw(img, "RGBA")
        bx = int(W * 0.43)
        f, size = _fit_lines(d, st, lines[:3], W - bx - 36, int(H * 0.66), 190)
        _draw_lines(d, lines[:3], f, size, bx, 40, colors=(TX, KY), stroke=14, stroke_fill=SK)
    elif style == "zoom":
        f, size = _fit_lines(d, st, lines[:2], int(W * 0.80), int(H * 0.40), 140)
        y = 30
        for ln in lines[:2]:
            d.rectangle([30, y - 6, 30 + _lw(d, ln, f) + 75, y + size * 1.08], fill=_rgba(dz["band"], 235))
            _draw_lines(d, [ln], f, size, 52, y, colors=(TX if dz["band"] != TX else SK, KY), stroke=0)
            y += int(size * 1.25)
        d.rectangle([0, 0, W - 1, H - 1], outline=AC, width=8)
    elif style == "bubble":
        f, size = _fit_lines(d, st, lines[:2], int(W * 0.66), int(H * 0.44), 150)
        w = max(_lw(d, ln, f) for ln in lines[:2])
        hgt = size * 1.12 * len(lines[:2])
        x0, y0 = 40, 36
        d.rounded_rectangle([x0, y0, x0 + w + 115, y0 + hgt + 50], radius=44, fill="#FFFFFF", outline="#111111", width=8)
        tx = x0 + 120
        d.polygon([(tx, y0 + hgt + 46), (tx + 70, y0 + hgt + 46), (tx + 10, y0 + hgt + 130)], fill="#FFFFFF",
                  outline="#111111")
        d.line([(tx + 5, y0 + hgt + 44), (tx + 65, y0 + hgt + 44)], fill="#FFFFFF", width=10)
        _draw_lines(d, lines[:2], f, size, x0 + 40, y0 + 18, colors=("#111111", KY if KY.upper() not in ("#FFFFFF", "#FFF35A", "#FFE14D") else "#E8202A"), stroke=0)
        d.rectangle([0, 0, W - 1, H - 1], outline=AC, width=10)
    img.convert("RGB").save(out_path, quality=95)
    return out_path
