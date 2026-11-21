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
from .timeline import Mapper, cut_silences, keep_ranges


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
    idx = 1
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

    # 5) Sound effects mixed on output time.
    aud = "ca"
    se_labels = []
    for k, se in enumerate(clip.get("se") or []):
        inputs += ["-i", _asset(se["file"], "se")]
        o = mp.to_out_clamped(float(se["at"]))
        vol = float(se.get("volume", st["audio"]["se_volume"]))
        g.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol},"
                 f"adelay={int(o * 1000)}:all=1[se{k}]")
        se_labels.append(f"[se{k}]")
        idx += 1
    g.append("[ca]aformat=channel_layouts=stereo[ca2]")
    if se_labels:
        g.append(f"[ca2]{''.join(se_labels)}amix=inputs={1 + len(se_labels)}:normalize=0:duration=first[am]")
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
    run([need("ffmpeg"), "-y", "-hide_banner", *inputs, *filter_script_args(graph),
         "-map", "[outv]", "-map", "[outa]", "-r", str(fps), *venc, "-pix_fmt", "yuv420p",
         "-c:a", "pcm_s16le", "-t", f"{dur:.3f}", "-f", "mov", stage1])

    # 6) Two-pass loudness normalization (EBU R128), video stream copied.
    au = st["audio"]
    target = f"I={au['lufs']}:TP={au['true_peak']}:LRA={au['lra']}"
    err = run([need("ffmpeg"), "-hide_banner", "-i", stage1, "-vn", "-af",
               f"loudnorm={target}:print_format=json", "-f", "null", "-"])
    m = json.loads(err[err.rfind("{"):err.rfind("}") + 1])
    try:
        measured = float(m["input_i"])
    except (TypeError, ValueError):
        measured = float("-inf")
    if math.isfinite(measured) and measured > -70:
        ln = (f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
              f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
              f"offset={m['target_offset']}:linear=true,")
    else:
        ln = ""   # silent clip: nothing to normalize (qc reports it)
    run([need("ffmpeg"), "-y", "-hide_banner", "-i", stage1, "-c:v", "copy", "-af", f"{ln}aresample=48000",
         "-c:a", "aac", "-b:a", enc["audio_bitrate"], "-movflags", "+faststart", out_path])

    report = {"id": clip.get("id"), "format": fmt, "layout": layout, "out": out_path,
              "duration": round(dur, 2), "segments": len(ranges),
              "removed_sec": round(float(clip["end"]) - float(clip["start"]) - dur, 2),
              "lines": len(lines), "fps": fps}
    report["ass"] = ass_path
    shutil.rmtree(tmp, ignore_errors=True)   # stage1 is uncompressed audio: hundreds of MB
    return report


def load_words(wd):
    p = os.path.join(wd, "transcript.json")
    if not os.path.exists(p):
        return []
    return load_json(p).get("words", [])


def safe_name(s):
    return re.sub(r"[^\w\-]+", "_", s)[:40]
