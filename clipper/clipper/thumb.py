"""Long-video thumbnails in the shape popular JP clip channels use: huge outlined text, gradient key word 『』."""
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


STYLES = ("caption", "quotes", "face", "comment", "drama")
AUTO_STYLES = ("caption", "quotes", "face", "comment")   # drama (heavy mincho) only when asked: serious / horror
# Owner 2026-11-23: modelled on popular JP clip channels — text is the hero (heavy gothic, thick black
# outline + thin outer edge, gradient key words), stacked quotes with speaker icons, a big cut-out face.
# Readable and loud first; originality from the streamer's blue / Twitch purple accents and icons.


def _h(s):
    import hashlib
    return int(hashlib.md5(str(s).encode("utf-8")).hexdigest()[:8], 16)


def _pick(salt, seed, n_items, step=1):
    """Pick for seed "<stream>:<clip id>": a per-stream start plus the clip number, so the long videos
    of one stream never share a style/palette/font, and streams start at different places."""
    stream, _, cid = str(seed).rpartition(":")
    n = int(re.sub(r"\D", "", cid) or 0)
    return (_h(f"{salt}:{stream or seed}") + n * step) % n_items


def design(st, seed="", font=None, palette=None, style=None):
    th, fonts = st["thumbnail"], st.get("fonts") or {}
    pals = th.get("palettes") or {}
    auto = [k for k in th.get("auto_palettes") or sorted(pals) if k in pals] or ["red"]
    pk = palette if palette in pals else ("mono" if style == "drama" and "mono" in pals else auto[_pick("pal", seed, len(auto), 2)])
    cands = th.get("fonts") or ["mplus1p"]
    fk = font if font in fonts else (th.get("drama_font", "zenmincho") if style == "drama" else cands[_pick("font", seed, len(cands))])
    ffile = (fonts.get(fk) or [st["font_impact_file"]])[0]
    p = {"text": ["#FFFFFF", "#FFFFFF"], "key": ["#FF5A5A", "#C80000"], "stroke": "#000000", "outer": "#FFFFFF",
         "accent": "#E8202A", **(pals.get(pk) or {})}
    return {"font": os.path.join(fonts_dir(st), ffile), "font_key": fk, "palette": pk, **p}


def make_thumbnail(src, t, text, st, out_path, sticker=None, style=None, avatar=None, focus=None, seed="",
                   font=None, palette=None, quotes=None, partner=None):
    """style: caption / quotes / face / comment / drama (unset → rotates per stream + clip number).
    quotes: [{"text", "speaker"}] lines said in the clip (for quotes / comment)."""
    style = style if style in STYLES else AUTO_STYLES[_pick("style", seed, len(AUTO_STYLES))]
    if style == "face" and not (avatar and os.path.exists(avatar)):
        style = "caption"
    if style in ("quotes", "comment") and not quotes:
        style = "caption"
    dz = design(st, seed, font, palette, style)
    W, H = st["thumbnail"]["size"]
    from PIL import ImageEnhance
    img = _cover(lift_dark(grab_frame(src, t)), W, H)
    img = ImageEnhance.Color(img).enhance(1.25)
    img = ImageEnhance.Contrast(img).enhance(1.08).convert("RGBA")
    lines = _lines(text, 3 if style == "face" else 2, split_at=5 if style == "face" else 9)
    if style == "drama":
        img = _vignette(ImageEnhance.Brightness(img.convert("RGB")).enhance(0.55)).convert("RGBA")
        f, size = _fit(dz, lines, W - 120, int(H * 0.62), 230)
        _block(img, lines, f, size, dz, W // 2, int(H * 0.52), anchor="mm")
    elif style == "face":
        _shade(img, "left")
        _sticker(img, avatar, dz, right=True, height=H * 0.92, bottom=0.06, inset=0.70)
        f, size = _fit(dz, lines, int(W * 0.64), int(H * 0.80), 210)
        _block(img, lines, f, size, dz, 36, H - 30, anchor="ld")
    else:
        _shade(img, "bottom")
        plain = "".join(lines).replace("『", "").replace("』", "")
        hl = ["".join(lines)] if style in ("quotes", "comment") and len(plain) <= 13 else lines
        budget = 0.44 if style not in ("quotes", "comment") else (0.30 if len(hl) == 1 else 0.40)
        f, size = _fit(dz, hl, W - 48, int(H * budget), 210)
        _block(img, hl, f, size, dz, W // 2, H - 22, anchor="md")
        top = H - 22 - int(size * 1.08 * len(hl))
        if style == "quotes":
            _quotes(img, quotes[:2], dz, avatar, partner, bottom=top - 10)
        elif style == "comment":
            q = quotes[0]
            _comment(img, q["text"], dz, bottom=top - 16, speaker=q.get("speaker") or "配信者", avatar=avatar,
                     partner=partner)
    _tag(img, dz)
    img.convert("RGB").save(out_path, quality=95)
    return out_path


# ---------------------------------------------------------------------------------------------- parts
def _lines(text, max_lines, split_at=9):
    lines = [x for x in str(text).replace("\\n", "\n").split("\n") if x.strip()] or [str(text)]
    if len(lines) == 1 and len(lines[0].replace("『", "").replace("』", "")) > split_at and max_lines > 1:
        s = lines[0]
        k, e = s.find("『"), s.find("』")
        if 2 < k < len(s) - 2:
            cut = k
        elif 0 <= e < len(s) - 2:
            cut = e + 1
        else:
            cut = len(s) // 2
            while cut < len(s) - 1 and s[cut] in "』」）！？ー〜、。ゃゅょっャュョッ":
                cut += 1
        lines = [s[:cut], s[cut:]]
    return lines[:max_lines]


def _font(dz, size):
    return ImageFont.truetype(dz["font"], size)


def _w(f, line):
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    return sum(d.textlength(s, font=_af(f, s)) for s, _ in _split_ascii(_runs(line.replace("『", "").replace("』", ""))))


def _fit(dz, lines, max_w, max_h, start):
    size = start
    while size > 40:
        f = _font(dz, size)
        if max(_w(f, ln) for ln in lines) + size * 0.4 <= max_w and size * 1.08 * len(lines) <= max_h:
            return f, size
        size -= 4
    return _font(dz, size), size


def _grad(w, h, c1, c2):
    g = Image.new("RGBA", (w, h))
    a, b = Image.new("RGBA", (w, h), c1), Image.new("RGBA", (w, h), c2)
    mask = Image.linear_gradient("L").resize((w, h))
    return Image.composite(b, a, mask)


_FW = {c: chr(ord(c) + 0xFEE0) for c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!?%+&#"}


def _split_ascii(runs):
    """Split runs so ASCII letters/digits become their own pieces (drawn with the Latin face)."""
    import re as _re
    out = []
    for s, k in runs:
        for piece in _re.findall(r"[0-9A-Za-z%+#&]+|[^0-9A-Za-z%+#&]+", s):
            out.append((piece, k))
    return out


_AF = {}


def _af(f, s):
    """Font for a piece: ASCII letters/digits use Dela Gothic One (its Latin is compact and as heavy
    as the kana, owner 2026-11-27: 「1v1」 looked thin), scaled up a little; everything else uses f."""
    import re as _re
    if not _re.fullmatch(r"[0-9A-Za-z%+#&]+", s):
        return f
    key = (f.path, f.size)
    if key not in _AF:
        dela = os.path.join(os.path.dirname(f.path), "DelaGothicOne-Regular.ttf")
        _AF[key] = ImageFont.truetype(dela if os.path.exists(dela) else f.path, int(f.size * 1.12))
    return _AF[key]


def _full_width(t):
    """Half-width letters and digits are thin in Japanese display fonts; the full-width forms are as
    heavy as the kana around them (owner 2026-11-27: 「1v1」 looked thin and lost its punch)."""
    return "".join(_FW.get(c, c) for c in t)


def _text_layer(line, f, size, dz, fill=None):
    """One line: drop shadow, thin outer edge, thick black outline, gradient fill (key word in 『』
    gets the key gradient, the brackets themselves are dropped)."""
    from PIL import ImageFilter
    runs = _split_ascii([(s, k) for s, k in _runs(line) if s not in ("『", "』")])
    sw = max(5, int(size * 0.14))
    so = sw + max(3, int(size * 0.05)) if dz.get("outer") else sw
    pad = so + 12
    w = int(sum(ImageDraw.Draw(Image.new("L", (1, 1))).textlength(s, font=_af(f, s)) for s, _ in runs)) + pad * 2
    h = int(size * 1.25) + pad * 2
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow = Image.new("L", (w, h), 0)
    outer = Image.new("L", (w, h), 0)
    inner = Image.new("L", (w, h), 0)
    ds, do, di = ImageDraw.Draw(shadow), ImageDraw.Draw(outer), ImageDraw.Draw(inner)
    x = pad
    fills = []
    for s, key in runs:
        fo = _af(f, s)
        yo = pad - (int(f.size * 0.10) if fo is not f else 0)
        ds.text((x + 5, yo + 7), s, font=fo, fill=255, stroke_width=so, stroke_fill=255)
        do.text((x, yo), s, font=fo, fill=255, stroke_width=so, stroke_fill=255)
        di.text((x, yo), s, font=fo, fill=255, stroke_width=sw, stroke_fill=255)
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).text((x, yo), s, font=fo, fill=255)
        fills.append((m, dz["key"] if key else (fill or dz["text"])))
        x += ImageDraw.Draw(Image.new("L", (1, 1))).textlength(s, font=fo)
    layer.paste(Image.new("RGBA", (w, h), (0, 0, 0, 150)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(6)))
    if dz.get("outer"):
        layer.paste(Image.new("RGBA", (w, h), dz["outer"]), (0, 0), outer)
    layer.paste(Image.new("RGBA", (w, h), dz["stroke"]), (0, 0), inner)
    top, bot = pad + int(size * 0.15), pad + int(size * 1.05)
    for m, cols in fills:
        c1, c2 = (cols, cols) if isinstance(cols, str) else cols
        g = Image.new("RGBA", (w, h), c1)
        g.paste(_grad(w, max(2, bot - top), c1, c2), (0, top))
        g.paste(Image.new("RGBA", (w, h - bot), c2), (0, bot)) if h - bot > 0 else None
        layer.paste(g, (0, 0), m)
    return layer, pad


def _block(img, lines, f, size, dz, x, y, anchor="md", fill=None):
    """Stack lines. anchor: md = centre-bottom at (x, y); mm = centre-middle; ld = left-bottom."""
    layers = [_text_layer(ln, f, size, dz, fill) for ln in lines]
    lh = int(size * 1.08)
    total = lh * len(lines)
    y0 = y - total if anchor in ("md", "ld") else y - total // 2
    for k, (ly, pad) in enumerate(layers):
        lx = x - ly.width // 2 if anchor in ("md", "mm") else x - pad
        img.alpha_composite(ly, (int(lx), int(y0 + k * lh - pad - size * 0.12)))


def _shade(img, side):
    W, H = img.size
    g = Image.linear_gradient("L")
    if side == "bottom":
        m = g.resize((W, int(H * 0.55))).point(lambda v: int(v * 0.78))
        img.alpha_composite(Image.merge("RGBA", (*[Image.new("L", m.size, 0)] * 3, m)), (0, H - m.height))
    else:
        m = g.rotate(90, expand=True).resize((int(W * 0.7), H)).point(lambda v: int(v * 0.62))
        img.alpha_composite(Image.merge("RGBA", (*[Image.new("L", m.size, 0)] * 3, m)), (0, 0))


def _vignette(img):
    from PIL import ImageFilter
    W, H = img.size
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).ellipse([-W * 0.15, -H * 0.25, W * 1.15, H * 1.25], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(90))
    return Image.composite(img, Image.new("RGB", (W, H), (0, 0, 0)), m)


def _sticker(img, art_path, dz, right=True, height=None, bottom=0.10, inset=0.80):
    """The streamer's art as a cut-out sticker: white outline + soft shadow, big on one side."""
    from PIL import ImageFilter
    W, H = img.size
    art = Image.open(art_path).convert("RGBA")
    r = (height or H * 1.12) / art.height
    art = art.resize((int(art.width * r), int(art.height * r)), Image.LANCZOS)
    a = art.split()[3]
    edge = a.filter(ImageFilter.MaxFilter(17))
    x = W - int(art.width * inset) if right else -int(art.width * (1 - inset))
    y = H - art.height + int(H * bottom)
    sh = Image.new("RGBA", art.size, (0, 0, 0, 0))
    sh.putalpha(edge.filter(ImageFilter.GaussianBlur(10)).point(lambda v: int(v * 0.6)))
    img.alpha_composite(sh, (x + 8, y + 10))
    rim = Image.new("RGBA", art.size, dz.get("outer") or "#FFFFFF")
    rim.putalpha(edge)
    img.alpha_composite(rim, (x, y))
    img.alpha_composite(art, (x, y))


def _icon(kind, avatar, label, accent, size):
    """Square speaker icon: the streamer's face from her art, or a coloured tile with an initial."""
    if kind == "配信者" and avatar and os.path.exists(avatar):
        art = Image.open(avatar).convert("RGBA")
        w, h = art.size
        ic = art.crop((int(w * .15), int(h * .10), int(w * .80), int(h * .75))).resize((size, size), Image.LANCZOS)
        bg = Image.new("RGBA", (size, size), "#D9F3FF")
        bg.alpha_composite(ic)
        ic = bg
    else:
        ic = Image.new("RGBA", (size, size), "#FF8A1F" if kind == "相手" else "#8A8F98")
        d = ImageDraw.Draw(ic)
        ch = (label or "？")[:1]
        f = ImageFont.truetype(_ICON_FONT["path"], int(size * 0.62)) if _ICON_FONT["path"] else None
        if f:
            d.text((size / 2, size / 2), ch, font=f, fill="#FFFFFF", anchor="mm")
    frame = Image.new("RGBA", (size + 12, size + 12), "#FFFFFF")
    frame.alpha_composite(ic, (6, 6))
    ImageDraw.Draw(frame).rectangle([0, 0, size + 11, size + 11], outline=accent, width=4)
    return frame


_ICON_FONT = {"path": None}


def _quotes(img, quotes, dz, avatar, partner, bottom):
    """Up to two lines said in the clip, stacked above the headline, each with its speaker icon."""
    _ICON_FONT["path"] = dz["font"]
    W, H = img.size
    rows = []
    for q in quotes:
        txt = str(q.get("text", "")).strip()
        if txt:
            rows.append((txt, q.get("speaker") or "配信者"))
    if not rows:
        return
    size = 78
    f = _font(dz, size)
    while size > 44 and max(_w(f, t) for t, _ in rows) > W * 0.78:
        size -= 4
        f = _font(dz, size)
    lh = int(size * 1.35)
    y = bottom - lh * len(rows)
    fills = [["#FFFFFF", "#FFFFFF"], dz["key"]]
    for k, (txt, spk) in enumerate(rows):
        ic = _icon(spk, avatar, partner if spk == "相手" else ("リスナー" if spk == "読み上げ" else ""), dz["accent"], int(size * 1.05))
        img.alpha_composite(ic, (28, int(y + k * lh)))
        ly, pad = _text_layer(txt, f, size, {**dz, "key": fills[k % 2]}, fill=fills[k % 2])
        img.alpha_composite(ly, (28 + ic.width + 14 - pad, int(y + k * lh - pad - size * 0.05)))


def _comment(img, text, dz, bottom, speaker="配信者", avatar=None, partner=None):
    """A card holding one line said in the clip, with who said it: the streamer's face + her name,
    the partner's tile + name, or the listener icon + 'コメント' for a chat line read aloud."""
    W, H = img.size
    size = 64
    f = _font(dz, size)
    while size > 40 and _w(f, text) > W * 0.70:
        size -= 4
        f = _font(dz, size)
    tw = int(_w(f, text))
    bw, bh = tw + 200, int(size * 1.9)
    x, y = 30, bottom - bh
    card = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=26, fill="#FFFFFF", outline="#111111", width=5)
    r = int(bh * 0.36)
    cx, cy = 26 + r, bh // 2
    lf = _font(dz, 24)
    if speaker == "読み上げ":
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#4A90E2")
        d.ellipse([cx - r * 0.36, cy - r * 0.62, cx + r * 0.36, cy + r * 0.1], fill="#FFFFFF")
        d.pieslice([cx - r * 0.7, cy + r * 0.05, cx + r * 0.7, cy + r * 1.3], 180, 360, fill="#FFFFFF")
        name, col = "コメント", "#4A90E2"
    else:
        _ICON_FONT["path"] = dz["font"]
        ic = _icon(speaker, avatar, partner or "", dz["accent"], 2 * r - 12)
        m = Image.new("L", ic.size, 0)
        ImageDraw.Draw(m).ellipse([0, 0, ic.width - 1, ic.height - 1], fill=255)
        card.paste(ic, (cx - ic.width // 2, cy - ic.height // 2 - 6), m)
        name = "ろあろああ" if speaker == "配信者" else (partner or "")
        col = dz["accent"]
    if name:
        d.text((cx, bh - 6), name, font=lf, fill=col, anchor="md")
    d.text((cx + r + 22, bh // 2), text, font=f, fill="#111111", anchor="lm")
    img.alpha_composite(card, (x, y))


def _tag(img, dz):
    """Small channel tag top-left in the accent colour (the series' own mark)."""
    W, H = img.size
    f = _font(dz, 30)
    txt = "ろあろああ"
    d = ImageDraw.Draw(img)
    w = int(d.textlength(txt, font=f))
    d.rounded_rectangle([18, 16, 18 + w + 30, 16 + 46], radius=10, fill=dz["accent"])
    d.text((18 + 15, 16 + 23), txt, font=f, fill="#FFFFFF", anchor="lm")


def make_short_cover(src, t, text, st, out_path, avatar=None, seed="", palette=None, font=None, focus=None):
    """Vertical cover for a Short (1080x1920). Owner 2026-11-27: the first version was weak (small
    text, dark frame). Now: the payoff frame zoomed in and brightened so the situation reads at a
    glance, a huge two-line headline on a dark plate across the top (the second line, the payoff,
    in the key gradient), the streamer's art small in a corner as a reaction, the channel tag."""
    from PIL import ImageEnhance
    W, H = 1080, 1920
    dz = design(st, seed, font, palette, "caption")
    fr = lift_dark(grab_frame(src, t), target=120.0)
    fx, fy = focus or (0.5, 0.5)
    z = 1.35                                           # zoom into the action
    cw, ch = int(fr.width / z), int(fr.height / z)
    x0 = int(min(max(0, fr.width * fx - cw / 2), fr.width - cw))
    y0 = int(min(max(0, fr.height * fy - ch / 2), fr.height - ch))
    img = _cover(fr.crop((x0, y0, x0 + cw, y0 + ch)), W, H)
    img = ImageEnhance.Color(img).enhance(1.3)
    img = ImageEnhance.Contrast(img).enhance(1.12)
    img = ImageEnhance.Brightness(img).enhance(1.08).convert("RGBA")
    raw = [x for x in str(text).replace("\\n", "\n").split("\n") if x.strip()]
    if len(raw) == 1:
        raw = _lines(raw[0], 2, split_at=7)
    if len(raw) >= 2 and not any("『" in x for x in raw):
        raw = raw[:-1] + ["『" + raw[-1] + "』"]          # the payoff line gets the key colour
    lines = raw[:3]
    f, size = _fit(dz, lines, W - 60, int(H * 0.27), 270)
    plate_h = int(size * 1.08 * len(lines) + size * 0.75)
    plate = Image.new("RGBA", (W, plate_h + 40), (0, 0, 0, 0))
    ImageDraw.Draw(plate).rectangle([0, 0, W, plate_h], fill=(0, 0, 0, 175))
    g = Image.linear_gradient("L").resize((W, 40)).point(lambda v: int(175 * (255 - v) / 255))
    plate.paste(Image.new("RGBA", (W, 40), (0, 0, 0, 175)), (0, plate_h), g)
    img.alpha_composite(plate, (0, int(H * 0.05)))
    _block(img, lines, f, size, dz, W // 2, int(H * 0.05) + int(size * 0.35) + int(size * 1.08 * len(lines)), anchor="md")
    if avatar and os.path.exists(avatar):
        _sticker(img, avatar, dz, right=True, height=H * 0.26, bottom=0.02, inset=0.78)
    _tag(img, dz)
    img.convert("RGB").save(out_path, quality=92)
    return out_path
