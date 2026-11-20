"""Subtitle lines from word timestamps, and ASS documents for shorts and long videos."""
import re

from .common import apply_glossary, ass_color

PUNCT_BREAK = re.compile(r"[。！？!?…]$")
SOFT_BREAK = re.compile(r"[、,，]$")


def fits(text, max_chars, max_lines=2):
    """True when the text wraps into rows that all fit AND every row break is a natural one."""
    if len(text) <= max_chars:
        return True
    rows = wrap(text, max_chars, max_lines)
    if any(len(r) > max_chars for r in rows):
        return False
    pos, nat = 0, set(_breaks(text))
    for r in rows[:-1]:
        pos = text.index(r, pos) + len(r)
        nxt = len(text) - len(text[pos:].lstrip())
        if nxt not in nat and pos not in nat:
            return False
    return True


def auto_lines(words, start, end, max_chars, gl, gap_break=0.35, max_lines=2):
    """Group words into subtitle events (source time).

    Sentences end on punctuation or a pause. Each sentence is then packed greedily, word by
    word, into events that are guaranteed to wrap into max_lines rows of max_chars, and
    orphan scraps (1-2 chars, usually a word whose timestamp straddles a pause) are merged
    into the neighbouring event."""
    ws = [w for w in words if w["end"] > start and w["start"] < end and w["word"].strip()]
    sentences, cur = [], []
    for w in ws:
        if cur and w["start"] - cur[-1]["end"] > gap_break:
            sentences.append(cur)
            cur = []
        cur.append(w)
        if PUNCT_BREAK.search(w["word"].strip()):
            sentences.append(cur)
            cur = []
    if cur:
        sentences.append(cur)

    def text_of(ws_):
        return apply_glossary("".join(x["word"] for x in ws_).strip(), gl).strip(" 　、,")

    events = []
    for sent in sentences:
        chunk = []
        for w in sent:
            if chunk and not fits(text_of(chunk + [w]), max_chars, max_lines):
                # Split at the last word boundary that is also a natural break.
                full = text_of(chunk)
                nat = set(_breaks(full))
                k = len(chunk)
                for j in range(len(chunk) - 1, 0, -1):
                    if len(text_of(chunk[:j])) in nat:
                        k = j
                        break
                events.append(chunk[:k])
                chunk = chunk[k:]
            chunk.append(w)
        if chunk:
            events.append(chunk)

    # Orphan scraps: after sentence-final punctuation a scrap belongs to the NEXT sentence.
    merged, carry = [], []
    for i, ev in enumerate(events):
        ev = carry + ev
        carry = []
        t = text_of(ev)
        prev_t = text_of(merged[-1]) if merged else ""
        if len(t) <= 2 and i + 1 < len(events) and (not merged or PUNCT_BREAK.search(prev_t)) \
                and fits(text_of(ev + events[i + 1]), max_chars, max_lines):
            carry = ev
            continue
        if merged and len(t) <= 2 and fits(text_of(merged[-1] + ev), max_chars, max_lines):
            merged[-1] = merged[-1] + ev
        else:
            merged.append(ev)
    if carry:
        merged.append(carry)

    lines = []
    for ev in merged:
        t = text_of(ev)
        if not t:
            continue
        # A word that straddles a pause has a stretched start; trust the last word's timing.
        s0 = ev[0]["start"]
        if len(ev) > 1 and ev[1]["start"] - ev[0]["end"] > gap_break:
            s0 = ev[1]["start"] - 0.15
        lines.append({"start": round(max(start, s0), 2), "end": round(min(end, ev[-1]["end"]), 2), "text": t})
    # Minimum on-screen time, and hold until the next line when the gap is short.
    for i, ln in enumerate(lines):
        nxt = lines[i + 1]["start"] if i + 1 < len(lines) else end
        ln["end"] = round(min(nxt, ln["end"] + 0.25), 2)  # word end times run early
        if ln["end"] - ln["start"] < 0.7:
            ln["end"] = min(nxt, ln["start"] + 0.7)
        if nxt - ln["end"] < 0.5:
            ln["end"] = nxt
    return lines


HIRA = re.compile(r"[ぁ-ゖ]")
NO_LINE_START = set("ー〜～、。！？!?…）」』ゃゅょっャュョッぁぃぅぇぉ・")
PUNCT_END = set("、。！？!?…）」』・→ 　")


def _breaks(text):
    """Positions where a line may start: after punctuation, or where hiragana (a particle or
    an inflection) gives way to kanji/katakana/latin (the start of the next word)."""
    out = []
    for i in range(1, len(text)):
        prev, cur = text[i - 1], text[i]
        if cur in NO_LINE_START:
            continue
        if prev in PUNCT_END or (HIRA.match(prev) and not HIRA.match(cur)):
            out.append(i)
    return out


def wrap(text, max_chars, max_lines):
    """Explicit '\\n' wins. Otherwise balanced lines, breaking after punctuation or a particle
    so a word (国士無双) never splits across lines."""
    if "\n" in text:
        return text.split("\n")[:max_lines]
    if len(text) <= max_chars:
        return [text]
    n = max(2, min(max_lines, -(-len(text) // max_chars)))
    out, rest = [], text
    while rest and len(out) < n - 1:
        target = -(-len(rest) // (n - len(out)))
        best, best_d = None, 99
        rows_left = n - len(out) - 1
        for cut in _breaks(rest):
            fits_rest = len(rest) - cut <= max_chars * rows_left
            if 2 <= cut <= min(len(rest) - 1, max_chars) and fits_rest and abs(cut - target) < best_d:
                best, best_d = cut, abs(cut - target)
        cut = best if best is not None else min(max(target, len(rest) - max_chars * rows_left), max_chars)
        out.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    out.append(rest)
    return out


def _ts(t):
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text):
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝")


def _header(w, h):
    return (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 2\n"
            "ScaledBorderAndShadow: yes\nYCbCr Matrix: TV.709\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n")


def _style(name, font, size, fill, outline_col, outline, align=2):
    return (f"Style: {name},{font},{size},{ass_color(fill)},{ass_color(fill)},{ass_color(outline_col)},"
            f"&H80000000,0,0,0,0,100,100,0,0,1,{outline},0,{align},0,0,0,1\n")


def _event(layer, start, end, style, text):
    return f"Dialogue: {layer},{_ts(start)},{_ts(end)},{style},,0,0,0,,{text}\n"


def build_ass(fmt, st, clip, lines_out, duration, layout):
    """lines_out: [{start, end, text, speaker, emph}] in OUTPUT time."""
    cfg = st[fmt]
    W, H = cfg["size"]
    sc = cfg["subs"]
    tel, imp = st["font_telop"], st["font_impact"]
    doc = [_header(W, H)]
    doc.append(_style("SubOuter", tel, sc["font_size"], sc["outer_color"], sc["outer_color"], sc["outline_outer"]))
    doc.append(_style("SubInner", tel, sc["font_size"], cfg["speakers"].get("default", "#FFFFFF"),
                      sc["inner_color"], sc["outline_inner"]))
    if fmt == "short":
        b, hk = cfg["band"], cfg["hook"]
        doc.append(_style("Band", tel, b["font_size"], b["text_color"], b["outline_color"], b["outline"], 5))
        doc.append(_style("Hook", imp, hk["font_size"], hk["color"], hk["outline_color"], hk["outline"], 8))
        doc.append(_style("Label", tel, 46, "#FFFFFF", "#000000", 5, 5))
    else:
        lb = cfg["label"]
        doc.append(_style("Label", tel, lb["font_size"], lb["color"], lb["outline_color"], lb["outline"], 7))
    doc.append("\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")

    cx = W // 2
    if fmt == "short":
        b, hk = cfg["band"], cfg["hook"]
        if clip.get("band_text") and layout == "letterbox":
            doc.append(_event(5, 0, duration, "Band",
                              f"{{\\pos({cx},{b['y'] + b['h'] // 2})}}{_esc(clip['band_text'])}"))
        if clip.get("hook"):
            hook_lines = wrap(clip["hook"], hk["max_chars_per_line"], 2)
            doc.append(_event(5, 0, duration, "Hook",
                              f"{{\\pos({cx},{hk['y']})}}" + "\\N".join(_esc(x) for x in hook_lines)))
        if layout == "letterbox":
            for lb in cfg.get("name_labels") or []:
                col = ass_color(lb.get("color", "#FFFFFF"))
                doc.append(_event(4, 0, duration, "Label",
                                  f"{{\\pos({lb['x']},{lb['y']})\\1c{col}}}{_esc(lb['text'])}"))
    elif clip.get("label"):
        lb = cfg["label"]
        doc.append(_event(5, 0, duration, "Label", f"{{\\pos({lb['x']},{lb['y']})}}{_esc(clip['label'])}"))

    bottom = sc["bottom_y"]
    for ln in lines_out:
        rows = wrap(ln["text"], sc["max_chars_per_line"], sc["max_lines"])
        body = "\\N".join(_esc(r) for r in rows)
        fill = cfg["speakers"].get(ln.get("speaker") or "default", cfg["speakers"].get("default"))
        scale = sc["emph_scale"] if ln.get("emph") else 100
        fill = sc["emph_color"] if ln.get("emph") and not ln.get("speaker") else fill
        pop = f"\\fscx{int(scale * 0.82)}\\fscy{int(scale * 0.82)}\\t(0,90,\\fscx{scale}\\fscy{scale})"
        pos = f"\\an2\\pos({cx},{bottom})"
        doc.append(_event(1, ln["start"], ln["end"], "SubOuter", f"{{{pos}{pop}}}{body}"))
        doc.append(_event(2, ln["start"], ln["end"], "SubInner",
                          f"{{{pos}{pop}\\1c{ass_color(fill)}}}{body}"))
    return "".join(doc)
