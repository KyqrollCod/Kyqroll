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
    from PIL import ImageStat
    mean = ImageStat.Stat(img.convert("L")).mean[0]
    if mean >= target * 0.8:
        return img
    gain = min(max_gain, target / max(mean, 1.0))
    gamma = 1.0 / gain ** 0.6
    lut = [min(255, int(255 * (i / 255) ** gamma * gain ** 0.4 + 0.5)) for i in range(256)]
    return img.point(lut * 3)


def make_thumbnail(src, t, text, st, out_path, sticker=None):
    th = st["thumbnail"]
    W, H = th["size"]
    img = _cover(lift_dark(grab_frame(src, t)), W, H)
    d = ImageDraw.Draw(img)
    bh = th["band_h"]
    d.rectangle([0, 0, W, bh], fill=th["band_color"])
    font_path = os.path.join(fonts_dir(st), st["font_impact_file"])
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
