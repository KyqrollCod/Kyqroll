---
name: clip
description: >-
  Turn a livestream archive (YouTube or Twitch URL, or a local recording) into finished
  YouTube Shorts and horizontal clip videos with telops, dead air removed, loudness
  normalized, titles and thumbnails, and an automated quality gate. Use for "切り抜き",
  "ショートを作って", "配信から見どころ", "clip this stream", or a pasted VOD URL.
---

# clip

Tool: `clipper/` (Python + ffmpeg). Style lives in `clipper/config/style.yaml`, the term
dictionary in `clipper/config/glossary.yaml`. Run every command from `clipper/`.

## Where it runs

YouTube refuses downloads from cloud servers, so `fetch` and `transcribe` run on the user's
own PC (home connection, their logged-in browser, their GPU). The same design tokodake uses
for YouTube with its desktop import app. Use, in order:

1. Claude Code on the user's PC, or this session attached to the PC through Remote Control
   (`list_computer_folders` → `request_computer_folder`).
2. If neither is available, the user runs `python -m clipper fetch URL --cookies-from-browser chrome`
   and `python -m clipper transcribe WORK` on the PC and uploads the work folder (Google Drive),
   then everything else continues here.

Never try to get around YouTube's bot check from a server.

## Pipeline

```
python -m clipper fetch URL --cookies-from-browser chrome   # → work/<id>/source.mp4, chat.json
python -m clipper transcribe work/<id>                      # → transcript.json (large-v3, GPU auto)
python -m clipper analyze work/<id>                         # → candidates.md / candidates.json
python -m clipper draft work/<id> --pick 1-8 --formats short,long   # → clips.yaml (auto telops)
#   ↓ Claude edits clips.yaml (the editorial pass below)
python -m clipper render work/<id>                          # → work/<id>/out/*.mp4, *_thumb.jpg
python -m clipper qc work/<id> --asr                        # → out/qc.json, out/*_sheet.png
```

## The editorial pass (the part that makes it good)

Read `candidates.md` and the transcript around each candidate before choosing anything.

**Choosing.** A Short is a moment that *survives without the video around it*:
it opens on a complete thought, has a turn (claim → twist / setup → payoff), and ends on a
line or a reaction, not a trail-off. Drop candidates that need the previous minute. Collabs,
rare events (役満, clutch plays, screams) and a clear payoff rank first. Shorts outperform
long videos by ~3x on the reference channel, so make Shorts for every strong moment and a
horizontal video for the best 1–2 of the stream.

**Window.** Adjust `start`/`end` so the first spoken line works as a hook (state the
situation in ≤3 s) and the end lands on the payoff plus 0.5–1.5 s of reaction. Shorts:
20–60 s is the sweet spot, 179 s hard max. Horizontal: one story per video, 6–10 minutes
(the reference channel uses a fixed ~8:00), or 20–30 min for a 【伝説回】compilation.
Use `segments: [[a,b], ...]` to drop tangents inside a window.

**Text on screen (Shorts).**
- `band_text` (top band): the theme or collab, ≤8 chars. 「ちいかわ×麻雀」「雀魂×役満」
- `hook` (big bottom text): the situation + promise, ≤18 chars, ends with ！？ or www when
  it fits. Put `\n` where the line should break. 「一点読みで\n国士無双ロン!?」
- `layout`: `letterbox` (default, game in the middle), `split` (face cam on top, game below,
  set `face_rect` from a `calibrate` frame), `crop` (full-screen vertical crop of one area).
- `zoom`: a punch-in (`scale` 1.15–1.25, `dur` 1–1.5 s) on the payoff moment.
- `se`: sound effect on the payoff, only files in `clipper/assets/se/` (licensed ones only).
- `overlays`: reaction images, only from `clipper/assets/images/` (licensed ones only).

**Telops (`subs`).** Proofread every line against the audio context and `glossary.yaml`:
fix names, game terms and misheard words, remove fillers that add nothing (えー、あのー),
keep the speaker's own tone (語尾 stays). Mark the punchline `emph: true`. Set `speaker` for
collab clips and add each speaker's color under `short.speakers` / `long.speakers`.
Never invent words the streamer did not say. Add new misrecognitions to `glossary.yaml`
(`replace`) so the next run is right automatically.

**Titles.** Write two per clip in `title`, then pick one:
- Reference-channel style: 【ゲーム】 + situation → twist + concrete number/name + www/！！
  「純正九蓮宝燈テンパイ！→ 国士無双ロンされて絶望www」
- Search style (clip channels): 【配信者名】 + what happened + 【切り抜き】 + game.
Shorts titles add 3–4 fixed hashtags (`#麻雀 #役満 #雀魂 #shorts`). Check every title with
`.claude/skills/yt-package/title.py` (concrete number/name, no vague adjectives).

**Thumbnail (horizontal).** `thumbnail_text`: ≤10 chars, the key word in 『』 (rendered red):
「バケモノ役満『ドラ一色』」. `thumbnail_at`: the frame of the payoff screen.

## Quality gate (all must hold before delivery)

1. `qc --asr` passes for every clip: resolution, codec, fps, duration, loudness −14 LUFS ±1,
   true peak ≤ −1 dBTP, no black frames, no dead air > 1.2 s, telop rows within the limit,
   Shorts text out of the YouTube UI area, and ≥ 90 % of telops match the re-transcribed audio.
2. Read every `out/*_sheet.png` (contact sheet) and each thumbnail yourself: faces or the key
   game element not cut off, telops readable and not covering the payoff, zoom framing right.
3. Any failure → fix `clips.yaml` (or style) and re-render that clip. Do not deliver a FAIL.

## Delivery

For each clip: the MP4 path, the chosen title, a 2-line description (first line = what the
viewer gets, then the source stream URL and the streamer credit their guidelines require),
hashtags, and the thumbnail path. Credit and permission follow the streamer's clip
guidelines; only clip streams with permission.
