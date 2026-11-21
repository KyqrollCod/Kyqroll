"""Render a clip spec to a finished MP4 (short 9:16 or long 16:9)."""
import json
import os
import re
import tempfile

import math
import shutil
import subprocess

from .common import (ROOT, ff_escape, filter_script_args, fonts_dir, load_json, media_info, need, run,
                     source_path)
from .subs import auto_lines, build_ass
from .timeline import Mapper, cut_silences, drop_ranges, keep_ranges


def _asset(path, kind):
    if os.path.isabs(path) and os.path.exists(path):
        return path
    for base in (os.path.join(ROOT, "assets", kind), ROOT):
        p = os.path.join(base, path)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"素材が見つかりません: {path}（assets/{kind}/ に置く）")


def _fill(label_in, rect, W, H, src_w, src_h, label_out):
    """Crop a normalized rect from the source and scale it to fill WxH exactly."""
    x, y, w, h = (min(max(float(v), 0.0), 1.0) for v in rect)
    w, h = max(0.01, min(w, 1 - x)), max(0.01, min(h, 1 - y))
    cw, ch = max(2, int(src_w * w) // 2 * 2), max(2, int(src_h * h) // 2 * 2)
    cx, cy = int(src_w * x), int(src_h * y)
    return (f"[{label_in}]crop={cw}:{ch}:{cx}:{cy},scale={W}:{H}:force_original_aspect_ratio=increase:"
            f"flags=lanczos,crop={W}:{H}[{label_out}]")


def tree_expr(terms, op, k=8):
    """Join ffmpeg expression terms as a balanced tree of parenthesized groups.

    ffmpeg's expression parser has a nesting-depth limit (a flat chain of ~100 terms fails with
    "Cannot allocate memory" in ffmpeg 7.1+/9), and a long stream with many cuts easily has more.
    Groups of k keep the depth at log_k(n)."""
    terms = list(terms)
    if not terms:
        return ""
    while len(terms) > 1:
        terms = ["(" + op.join(terms[i:i + k]) + ")" for i in range(0, len(terms), k)]
    return terms[0]


def _zoom_expr(zooms):
    if not zooms:
        return None
    terms = tree_expr((f"{z['scale'] - 1:.3f}*between(t\\,{z['out_start']:.3f}\\,{z['out_end']:.3f})"
                       for z in zooms), "+")
    return f"(1+{terms})"


def _zoomed(label_in, W, H, zooms, label_out, focus=(0.5, 0.5)):
    """Punch-in zoom on output-time intervals; output stays WxH."""
    expr = _zoom_expr(zooms)
    if not expr:
        return f"[{label_in}]null[{label_out}]"
    fx, fy = focus
    return (f"[{label_in}]scale=w='trunc({W}*{expr}/2)*2':h='trunc({H}*{expr}/2)*2':eval=frame:flags=lanczos,"
            f"crop={W}:{H}:x='(iw-{W})*{fx}':y='(ih-{H})*{fy}'[{label_out}]")


def build_clip_lines(clip, words, gl, st, fmt):
    """Subtitle lines in source time: the spec's own (proofread) lines, else auto."""
    if clip.get("subs") is not None:
        return clip["subs"]
    sc = st[fmt]["subs"]
    return auto_lines(words, float(clip["start"]), float(clip["end"]), sc["max_chars_per_line"], gl)


def auto_se(clip, lines, zooms, mp, st, min_gap=1.6, limit_per_min=14):
    """Automatic cues in output time: emph line → pop, zoom → whoosh, keep (visual payoff) →
    impact, chat read aloud → ding. Spaced out so they punctuate instead of clutter."""
    from .audiogen import se_path
    cues = []
    for z in zooms:
        cues.append((max(0.0, z["out_start"] - 0.18), "whoosh", 0.55))
    for k in clip.get("keep") or []:
        cues.append((mp.to_out_clamped(float(k[0])), "impact", 0.7))
    for ln in lines:
        if ln.get("speaker") == "読み上げ":   # just before the reading, never over its first syllables
            cues.append((max(0.0, ln["start"] - 0.45), "ding", 0.32))
        elif ln.get("emph"):
            cues.append((ln["start"], "pop", 0.5))
    cues.sort()
    out, last = [], -9.0
    cap = max(3, int(mp.duration / 60 * limit_per_min))
    for t, name, vol in cues:
        if t - last >= min_gap and len(out) < cap:
            out.append((se_path(name), t, vol))
            last = t
    return out


def make_badge(label, color, size, st, path, bubble=False):
    """Round name badge (partner) or speech bubble (chat read aloud), as an RGBA PNG."""
    from PIL import Image, ImageDraw, ImageFont
    s = 4
    S = size * s
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    col = tuple(int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    if bubble:
        d.rounded_rectangle([6 * s, 30 * s, S - 6 * s, S - 60 * s], radius=40 * s, fill=col + (240,),
                            outline=(255, 255, 255, 255), width=8 * s)
        d.polygon([(S * 0.25, S - 64 * s), (S * 0.18, S - 14 * s), (S * 0.42, S - 64 * s)], fill=col + (240,))
    else:
        d.ellipse([6 * s, 6 * s, S - 6 * s, S - 6 * s], fill=col + (235,), outline=(255, 255, 255, 255), width=10 * s)
    font = ImageFont.truetype(os.path.join(fonts_dir(st), st["font_telop_file"]), 10)
    fs = 10
    for fs in range(int(S * 0.34), 10, -4):
        font = ImageFont.truetype(os.path.join(fonts_dir(st), st["font_telop_file"]), fs)
        if d.textlength(label, font=font) <= S * 0.78:
            break
    cy = (S - 30 * s) / 2 if bubble else S / 2
    d.text((S / 2, cy), label, font=font, fill=(255, 255, 255, 255), anchor="mm",
           stroke_width=max(2, fs // 12), stroke_fill=(20, 20, 30, 255))
    im.resize((size, size), Image.LANCZOS).save(path)
    return path


def source_silences(src, start, end, noise="-45dB", min_dur=1.0):
    """(start, duration) of audible silences in [start, end], in source time. Same threshold as
    the qc dead_air check, so what qc would flag is what gets cut."""
    p = subprocess.run([need("ffmpeg"), "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
                        "-i", src, "-vn", "-af", f"silencedetect=n={noise}:d={min_dur}", "-f", "null", "-"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    out = []
    for m in re.finditer(r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)", p.stderr):
        e, d = float(m.group(1)), float(m.group(2))
        out.append((start + e - d, d))
    return out


def render_clip(wd, clip, st, gl, out_path, words):
    fmt = clip.get("format", "short")
    cfg = st[fmt]
    W, H = cfg["size"]
    src = clip.get("source") or source_path(wd)
    info = media_info(src)
    fps = min(cfg["fps"], round(info["fps"])) or 30
    layout = clip.get("layout") or (cfg.get("layout") if fmt == "short" else "full")

    # Snap every range to the frame grid so the video frames kept by select, the audio samples
    # kept by aselect and the Mapper used for telops all agree exactly (no drift across cuts).
    ranges = []
    kept = keep_ranges(clip, words, st["timeline"])
    if clip.get("trim_silence", True) and not clip.get("segments") and info["has_audio"]:
        kept = cut_silences(kept, source_silences(src, float(clip["start"]), float(clip["end"])),
                            keep=[tuple(map(float, k)) for k in clip.get("keep") or []],
                            min_segment=st["timeline"]["min_segment"])
    if clip.get("drop"):
        kept = drop_ranges(kept, clip["drop"], st["timeline"]["min_segment"])
    for a, b in kept:
        a2, b2 = math.floor(a * fps + 1e-6) / fps, math.ceil(b * fps - 1e-6) / fps
        if b2 > a2:
            ranges.append([round(a2, 6), round(b2, 6)])
    if not ranges:
        raise ValueError(f"{clip.get('id')}: 残る区間がありません（start/end/segments を確認）")
    mp = Mapper(ranges)
    dur = mp.duration

    lines = []
    for ln in build_clip_lines(clip, words, gl, st, fmt):
        sp = mp.span(float(ln["start"]), float(ln["end"]))
        if sp:
            lines.append({**ln, "start": sp[0], "end": sp[1]})

    zooms = []
    for z in clip.get("zoom") or []:
        o = mp.to_out_clamped(float(z["at"]))
        zooms.append({"scale": float(z.get("scale", 1.18)), "out_start": o,
                      "out_end": min(dur, o + float(z.get("dur", 1.5)))})

    tmp = tempfile.mkdtemp(prefix="clip_")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    ass_path = os.path.splitext(out_path)[0] + ".ass"   # kept next to the MP4: qc reads it
    with open(ass_path, "w", encoding="utf-8-sig") as fh:
        fh.write(build_ass(fmt, st, clip, lines, dur, layout))

    # Seek straight to the clip window so a 3-hour VOD is never decoded end to end.
    off = max(0.0, math.floor((ranges[0][0] - 1.0) * fps) / fps)
    win_end = ranges[-1][1] + 1.0
    inputs = ["-ss", f"{off:.3f}", "-to", f"{win_end:.3f}", "-i", src]
    rel = [(a - off, b - off) for a, b in ranges]
    g = []
    # 1) One decode path: keep frames inside the ranges, then re-time them back to back.
    #    (Parallel trim branches make ffmpeg buffer the whole window in memory.)
    # Half-open [a, b): a closed range would keep one extra frame per cut on the frame grid.
    sel = tree_expr((f"gte(t\\,{a - 0.5 / fps:.6f})*lt(t\\,{b - 0.5 / fps:.6f})" for a, b in rel), "+")
    asel = tree_expr((f"gte(t\\,{a:.6f})*lt(t\\,{b:.6f})" for a, b in rel), "+")
    g.append(f"[0:v]fps={fps},select='{sel}',setpts=N/{fps}/TB[cv]")
    if info["has_audio"]:
        # 1 ms audio frames make the cut sample-accurate enough, and 8 ms fades at every seam
        # (a product of ramps around each boundary) avoid clicks.
        bounds = sorted({round(x, 3) for ab in rel for x in ab})
        ramp = tree_expr((f"min(1\\,abs(t-{b:.3f})/0.008)" for b in bounds), "*")
        g.append(f"[0:a]aresample=48000,asetnsamples=n=48:p=0,volume='{ramp}':eval=frame,aselect='{asel}',"
                 f"asetpts=N/SR/TB[ca]")
    else:
        g.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={dur:.3f}[ca]")

    bg = cfg.get("background", "#000000").lstrip("#")
    sw, sh = info["width"], info["height"]
    # 2) Layout.
    if fmt == "long":
        g.append(f"[cv]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,"
                 f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x{bg},setsar=1[base]")
        g.append(_zoomed("base", W, H, zooms, "comp", tuple(clip.get("zoom_focus", (0.5, 0.5)))))
    elif layout == "crop":
        cx = float(clip.get("crop_center_x", cfg["crop"]["center_x"]))
        cw = min(sw, int(sh * 9 / 16)) // 2 * 2
        ch = min(sh, int(cw * 16 / 9)) // 2 * 2
        x = int(max(0, min(sw - cw, sw * cx - cw / 2)))
        g.append(f"[cv]crop={cw}:{ch}:{x}:{(sh - ch) // 2},scale={W}:{H}:force_original_aspect_ratio=increase:"
                 f"flags=lanczos,crop={W}:{H},setsar=1[base]")
        g.append(_zoomed("base", W, H, zooms, "comp", tuple(clip.get("zoom_focus", (0.5, 0.4)))))
    elif layout == "split":
        sp = cfg["split"]
        face_h = sp["face_h"]
        g.append("[cv]split=2[cv1][cv2]")
        g.append(_fill("cv1", clip.get("face_rect", sp["face"]), W, face_h, sw, sh, "face"))
        g.append(_fill("cv2", clip.get("game_rect", sp["game"]), W, H - face_h, sw, sh, "game0"))
        g.append(_zoomed("game0", W, H - face_h, zooms, "game", tuple(clip.get("zoom_focus", (0.5, 0.5)))))
        g.append("[face][game]vstack=inputs=2,setsar=1[comp]")
    elif layout == "avatar":
        # Blurred game fills the canvas, the game itself sits in a band near the top, and the
        # streamer's stand-in art overlaps the lower half, bobbing while she talks.
        av = cfg["avatar"]
        g.append("[cv]split=2[cvb][cvg]")
        g.append(f"[cvb]scale={W}:{H}:force_original_aspect_ratio=increase:flags=bilinear,crop={W}:{H},"
                 f"boxblur={av['bg_blur']}:2,eq=brightness=-{av['bg_dim']},setsar=1[bgv]")
        vw, vh = W, int(W * sh / sw) // 2 * 2
        g.append(f"[cvg]scale={vw}:{vh}:flags=lanczos,setsar=1[gv0]")
        g.append(_zoomed("gv0", vw, vh, zooms, "gv", tuple(clip.get("zoom_focus", (0.5, 0.5)))))
        g.append(f"[bgv][gv]overlay=0:{av['game_y']}[comp0]")
        cur_av = "comp0"
        art = clip.get("avatar")
        if art:
            inputs += ["-loop", "1", "-i", _asset(art, "images")]
            idx_av = len([x for x in inputs if x == "-i"]) - 1
            ah = int(av["height"])
            talk = tree_expr((f"between(t\\,{ln['start']:.3f}\\,{ln['end']:.3f})" for ln in lines
                              if ln.get("speaker") == clip.get("avatar_speaker", "配信者")), "+") or "0"
            y0 = H - ah + int(av["bottom_overflow"])
            bob = float(av.get("talk_bob", 0))
            yexpr = f"{y0}-{bob}*abs(sin(2*PI*3.2*t))*min(1\\,{talk})" if bob else str(y0)
            g.append(f"[{idx_av}:v]scale=-1:{ah}:flags=lanczos,format=rgba[avi]")
            g.append(f"[comp0][avi]overlay=x={av['x']}:y='{yexpr}':eval=frame:shortest=1[comp1]")
            cur_av = "comp1"
        # Partner / chat-TTS badges while they speak (left side, clear of the YouTube UI).
        badges = []
        for who, label, colkey in ((clip.get("partner_speaker", "相手"), clip.get("partner_name"), "相手"),
                                   ("読み上げ", "コメント", "読み上げ")):
            spans = [ln for ln in lines if ln.get("speaker") == who]
            if not spans or not label:
                continue
            png = make_badge(label, cfg["speakers"].get(colkey, "#3EA8FF"), int(av["badge"]["size"]), st,
                             os.path.join(tmp, f"badge_{colkey}.png"), bubble=(who == "読み上げ"))
            badges.append((png, spans))
        for k, (png, spans) in enumerate(badges):
            inputs += ["-loop", "1", "-i", png]
            bi = len([x for x in inputs if x == "-i"]) - 1
            en = tree_expr((f"between(t\\,{ln['start']:.3f}\\,{ln['end']:.3f})" for ln in spans), "+")
            g.append(f"[{cur_av}][{bi}:v]overlay=x={av['badge']['x']}:y={av['badge']['y']}:"
                     f"enable='{en}':shortest=1[cb{k}]")
            cur_av = f"cb{k}"
        g.append(f"[{cur_av}]null[comp]")
    else:  # letterbox
        band = cfg["band"]
        max_h = cfg["hook"]["y"] - 20 - cfg["video_y"]      # never run into the bottom text area
        vw, vh = W, int(W * sh / sw) // 2 * 2
        if vh > max_h:                                      # tall/vertical source: fit by height
            vh = max_h // 2 * 2
            vw = int(vh * sw / sh) // 2 * 2
        g.append(f"[cv]scale={vw}:{vh}:flags=lanczos,setsar=1[vid0]")
        g.append(_zoomed("vid0", vw, vh, zooms, "vid", tuple(clip.get("zoom_focus", (0.5, 0.5)))))
        g.append(f"color=c=0x{bg}:s={W}x{H}:r={fps}:d={dur:.3f}[bg0]")
        if clip.get("band_text"):
            g.append(f"[bg0]drawbox=x=0:y={band['y']}:w={W}:h={band['h']}:color=0x{band['color'].lstrip('#')}:t=fill[bg1]")
        else:
            g.append("[bg0]null[bg1]")
        g.append(f"[bg1][vid]overlay={(W - vw) // 2}:{cfg['video_y']}:shortest=1[comp]")

    # 3) Image overlays (memes, stickers) on output time.
    cur = "comp"
    idx = len([x for x in inputs if x == "-i"])   # next input index (layouts may have added images)
    for k, ov in enumerate(clip.get("overlays") or []):
        inputs += ["-loop", "1", "-i", _asset(ov["file"], "images")]
        o = mp.to_out_clamped(float(ov["at"]))
        e = min(dur, o + float(ov.get("dur", 2.0)))
        ow = int(W * float(ov.get("w", 0.45)))
        x = int(W * float(ov.get("x", 0.5)) - ow / 2)
        y = int(H * float(ov.get("y", 0.45)))
        g.append(f"[{idx}:v]scale={ow}:-1,format=rgba[ov{k}]")
        g.append(f"[{cur}][ov{k}]overlay={x}:{y}-h/2:enable='between(t\\,{o:.3f}\\,{e:.3f})':shortest=1[o{k}]")
        cur, idx = f"o{k}", idx + 1

    # 4) Subtitles and text.
    g.append(f"[{cur}]ass=filename={ff_escape(ass_path)}:fontsdir={ff_escape(fonts_dir(st))},"
             f"format=yuv420p[outv]")

    # 5) Sound effects mixed on output time: hand-placed ones plus automatic cues.
    se_items = [(_asset(se["file"], "se"), mp.to_out_clamped(float(se["at"])),
                 float(se.get("volume", st["audio"]["se_volume"]))) for se in clip.get("se") or []]
    if clip.get("auto_se", cfg.get("auto_se", False)):
        se_items += auto_se(clip, lines, zooms, mp, st)
    se_labels = []
    for k, (path, o, vol) in enumerate(se_items):
        inputs += ["-i", path]
        g.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol},"
                 f"adelay={int(o * 1000)}:all=1[se{k}]")
        se_labels.append(f"[se{k}]")
        idx += 1
    g.append("[ca]aformat=channel_layouts=stereo[ca2]")
    # 6) BGM under everything, ducked by the voice (sidechain) so speech always wins.
    voice, beds = "ca2", []
    bgm = clip.get("bgm", cfg.get("bgm"))
    if bgm and str(bgm).lower() != "none":
        from .audiogen import bgm_path
        path = bgm if os.path.isabs(str(bgm)) else bgm_path(str(bgm))
        inputs += ["-stream_loop", "-1", "-i", path]
        g.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
                 f"volume={float(clip.get('bgm_db', cfg.get('bgm_db', -22)))}dB,atrim=duration={dur:.3f},"
                 f"afade=t=in:d=0.6,afade=t=out:st={max(0.0, dur - 1.2):.3f}:d=1.2[bgr]")
        g.append("[ca2]asplit=2[cav][cak]")
        g.append("[bgr][cak]sidechaincompress=threshold=0.008:ratio=12:attack=20:release=450:makeup=1[bgd]")
        voice, beds = "cav", ["[bgd]"]
        idx += 1
    if se_labels or beds:
        n = 1 + len(se_labels) + len(beds)
        g.append(f"[{voice}]{''.join(se_labels)}{''.join(beds)}amix=inputs={n}:normalize=0:duration=first[am]")
        aud = "am"
    else:
        aud = "ca2"
    g.append(f"[{aud}]atrim=duration={dur:.3f}[outa]")

    graph = os.path.join(tmp, "graph.txt")
    with open(graph, "w", encoding="utf-8") as fh:
        fh.write(";\n".join(g))

    enc = st["encode"]
    venc = ["-c:v", enc["encoder"]]
    if enc["encoder"] == "libx264":
        venc += ["-preset", os.environ.get("CLIPPER_PRESET", enc["preset"]), "-crf", str(enc["crf"]), "-profile:v", "high"]
    else:
        venc += ["-preset", "p6", "-cq", str(enc["crf"]), "-b:v", "0"]
    stage1 = os.path.join(tmp, "stage1.mp4")
    from .progress import current
    prog, prog_args = current(), []
    if prog:  # live percentage on the progress page
        pfile = os.path.join(tmp, "ffprogress.txt")
        prog_args = ["-progress", pfile, "-nostats"]
        prog.watch_ffmpeg(f"r:{clip.get('id')}", pfile, dur)
    run([need("ffmpeg"), "-y", "-hide_banner", *prog_args, *inputs, *filter_script_args(graph),
         "-map", "[outv]", "-map", "[outa]", "-r", str(fps), *venc, "-pix_fmt", "yuv420p",
         "-c:a", "pcm_s16le", "-t", f"{dur:.3f}", "-f", "mov", stage1])
    if prog:
        prog.stop_watch()

    # 6) Two-pass loudness normalization (EBU R128) + true-peak limiter, video stream copied.
    part = out_path + ".part.mp4"   # never write over a file a browser may be playing
    normalize_loudness(stage1, part, st)
    replace_when_free(part, out_path)

    report = {"id": clip.get("id"), "format": fmt, "layout": layout, "out": out_path,
              "duration": round(dur, 2), "segments": len(ranges),
              "removed_sec": round(float(clip["end"]) - float(clip["start"]) - dur, 2),
              "lines": len(lines), "fps": fps}
    report["ass"] = ass_path
    # Output-time positions of each line (the page links unsure lines to the exact moment) and
    # of the punchlines (the long-video teaser is cut from them).
    report["line_times"] = {}
    for ln in lines:
        report["line_times"].setdefault(ln["text"].replace("\n", ""), round(ln["start"], 2))
    report["emph_out"] = [[round(ln["start"], 2), round(ln["end"], 2)] for ln in lines if ln.get("emph")]
    shutil.rmtree(tmp, ignore_errors=True)   # stage1 is uncompressed audio: hundreds of MB
    return report


def normalize_loudness(src, dst, st):
    """Two-pass EBU R128 to the style target; video stream copied."""
    au, enc = st["audio"], st["encode"]
    target = f"I={au['lufs']}:TP={au['true_peak']}:LRA={au['lra']}"
    err = run([need("ffmpeg"), "-hide_banner", "-i", src, "-vn", "-af", f"loudnorm={target}:print_format=json",
               "-f", "null", "-"])
    m = json.loads(err[err.rfind("{"):err.rfind("}") + 1])
    try:
        ok = math.isfinite(float(m["input_i"])) and float(m["input_i"]) > -70
    except (TypeError, ValueError):
        ok = False
    ln = (f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
          f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true," if ok else "")
    # A limiter that keeps the true peak lowers the loudness, and AAC raises peaks again. One
    # setting cannot satisfy both, so: encode, measure the result, correct the gain, repeat.
    lim = 10 ** ((au["true_peak"] - 0.5) / 20)
    gain, target = 0.0, float(au["lufs"])
    for _ in range(3):
        run([need("ffmpeg"), "-y", "-hide_banner", "-i", src, "-c:v", "copy", "-af",
             # limit at 4x the sample rate: catches inter-sample peaks that AAC would turn into overs
             f"{ln}volume={gain:.2f}dB,aresample=192000,alimiter=limit={lim:.3f}:level=false:attack=2:release=60,"
             f"aresample=48000", "-c:a", "aac", "-b:a", enc["audio_bitrate"], "-movflags", "+faststart", dst])
        i_lufs, tp = measure_loudness(dst)
        if i_lufs is None or (abs(i_lufs - target) <= 0.5 and tp <= -1.1):
            break
        if tp > -1.1:
            lim *= 10 ** ((-1.2 - tp) / 20)          # peaks over: limit harder
        gain += max(-3.0, min(3.0, target - i_lufs))  # loudness off: correct the gain
    return dst


def measure_loudness(path):
    """(integrated LUFS, true peak dBTP) of a file's audio, as qc measures it."""
    err = run([need("ffmpeg"), "-hide_banner", "-nostats", "-i", path, "-vn", "-af", "ebur128=peak=true",
               "-f", "null", "-"])
    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    tp = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", err)
    try:
        return float(i[-1]), float(tp[-1])
    except (IndexError, ValueError):
        return None, None


def replace_when_free(src, dst, tries=30):
    """os.replace that waits out Windows file locks (a browser tab or the page server still
    streaming the previous version of the video)."""
    import time
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            time.sleep(1.0)
    raise PermissionError(f"{dst} が開かれたままで上書きできません。ブラウザの動画タブを閉じてから再実行してください")


def pick_teaser(report, max_total=8.0, max_each=2.8, count=3):
    """Up to `count` punchline moments, spread over the video, for a cold open before the intro."""
    spans = [s for s in report.get("emph_out") or [] if s[1] - s[0] >= 0.6]
    if not spans:
        return []
    dur = report["duration"]
    picked = []
    for k in range(count):            # one from each part of the video
        part = [s for s in spans if k * dur / count <= s[0] < (k + 1) * dur / count]
        if part:
            s = max(part, key=lambda x: x[1] - x[0])
            a = max(0.0, s[0] - 0.25)
            picked.append([a, min(dur, a + max_each, s[1] + 0.45)])
    out, total = [], 0.0
    for a, b in picked:
        if total + (b - a) > max_total:
            break
        out.append([round(a, 3), round(b, 3)])
        total += b - a
    return out


def add_opening(main_path, report, intro, out_path, st, teaser=True):
    """Long videos: [teaser of punchlines] + [channel intro] + [main]. The ASS used by qc is shifted
    by the opening length so the speech/telop check still lines up."""
    enc = st["encode"]
    spans = pick_teaser(report) if teaser else []
    inputs = ["-i", main_path]
    g, parts = [], []
    for k, (a, b) in enumerate(spans):
        g.append(f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS,fps=60,format=yuv420p,setsar=1[tv{k}]")
        g.append(f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS,afade=t=in:d=0.05,"
                 f"afade=t=out:st={max(0.0, b - a - 0.12):.3f}:d=0.12[ta{k}]")
        parts.append(f"[tv{k}][ta{k}]")
    opening = sum(b - a for a, b in spans)
    if intro and os.path.exists(intro):
        inputs += ["-i", intro]
        g.append("[1:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
                 "fps=60,format=yuv420p,setsar=1[iv]")
        g.append(f"[1:a]aresample=48000,aformat=channel_layouts=stereo,loudnorm=I={st['audio']['lufs']}:"
                 f"TP={st['audio']['true_peak']}[ia]")
        parts.append("[iv][ia]")
        opening += media_info(intro)["duration"]
    if not parts:
        return None
    g.append("[0:v]fps=60,format=yuv420p,setsar=1[mv]")
    g.append("[0:a]aformat=channel_layouts=stereo[ma]")
    parts.append("[mv][ma]")
    g.append(f"{''.join(parts)}concat=n={len(parts)}:v=1:a=1[v][a]")
    tmp_out = out_path + ".tmp.mp4"
    venc = ["-c:v", enc["encoder"]]
    if enc["encoder"] == "libx264":
        venc += ["-preset", os.environ.get("CLIPPER_PRESET", enc["preset"]), "-crf", str(enc["crf"])]
    run([need("ffmpeg"), "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(g), "-map", "[v]", "-map", "[a]",
         *venc, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", enc["audio_bitrate"], "-movflags", "+faststart", tmp_out])
    # The intro and teaser change the programme loudness: normalize the joined video as a whole.
    normalize_loudness(tmp_out, out_path + ".norm.mp4", st)
    os.remove(tmp_out)
    replace_when_free(out_path + ".norm.mp4", out_path)
    # Shift every subtitle event by the opening length (qc compares them with what it hears).
    ass = report["ass"]
    txt = open(ass, encoding="utf-8-sig").read()

    def sh(m):
        def ts(x):
            h, mi, s = x.split(":")
            return int(h) * 3600 + int(mi) * 60 + float(s)

        def fmt(v):
            h, rem = divmod(v, 3600)
            mi, s = divmod(rem, 60)
            return f"{int(h)}:{int(mi):02d}:{s:05.2f}"
        return f"Dialogue: {m.group(1)},{fmt(ts(m.group(2)) + opening)},{fmt(ts(m.group(3)) + opening)},"
    txt = re.sub(r"Dialogue: (\d+),([^,]+),([^,]+),", sh, txt)
    with open(ass, "w", encoding="utf-8-sig") as fh:
        fh.write(txt)
    report.update(opening=round(opening, 2), teaser=spans, duration=round(report["duration"] + opening, 2))
    report["line_times"] = {k: round(v + opening, 2) for k, v in report.get("line_times", {}).items()}
    return out_path


def load_words(wd):
    p = os.path.join(wd, "transcript.json")
    if not os.path.exists(p):
        return []
    return load_json(p).get("words", [])


def safe_name(s):
    return re.sub(r"[^\w\-]+", "_", s)[:40]
