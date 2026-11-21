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
python -m clipper transcribe work/<id> --prompt "配信者名、ゲーム名、用語"  # → transcript.json
python -m clipper analyze work/<id>                         # → candidates.md / candidates.json
python -m clipper draft work/<id> --pick 1-8 --formats short,long   # → clips.yaml (auto telops)
#   ↓ Claude edits clips.yaml (the editorial pass below)
python -m clipper align work/<id>                           # script: → timed subs
python -m clipper render work/<id>                          # → work/<id>/out/*.mp4, *_thumb.jpg
python -m clipper qc work/<id> --asr large-v3               # → out/qc.json, out/*_sheet.png
```

Set `$env:CLIPPER_PRESET="veryfast"` for drafts (a 7-min long renders in ~2 min).

**One command per iteration.** Write `clips.src.yaml` and run
`python -m clipper build <folder> [--only c01s]`. It copies it to clips.yaml, aligns, labels
speakers, runs a preflight (unmatched lines, row length), and stops there on any problem
before the render. Only then does it render and run `qc --asr large-v3`. Fix what it reports and
run it again; don't chain the steps by hand.

**Where files live.** On the user's PC, `config/local.yaml` (not in git) sets `work_root`
(E:/claude/切り抜き制作). fetch makes one folder per video, `<配信日>_<配信者>_<id>`, which holds the
source, transcript, chat, clips.src.yaml and out/ (MP4, thumbnails, sheets, delivery.md).
Later edits happen in the same folder.

**Pages.** `build`, `render` and `qc` write `progress.html` while running and regenerate the
pages when done (`python -m clipper site` does it by hand):
- `<root>/index.html`: a card per video
- `<video>/index.html`: players, titles, descriptions and hashtags with copy buttons, the QC
  result, and the speaker legend
- `out/delivery.md`
Keep titles and descriptions in clips.src.yaml (`package:` holds the credit, hashtags and
speaker names; each clip has `title` and `description`). Do not edit delivery.md by hand. The
owner watches background runs through these pages, so always start long runs via build, render
or qc and point them to http://localhost:8765/.

**Speakers.** `align` labels every telop line 読み上げ / 男性 / 女性 and colors it from
`style.yaml` speakers. 読み上げ means the line is a chat message (the TTS bot reads chat
verbatim). Otherwise pitch decides when clear (<165 Hz / >230 Hz), and the voice embedding
(clipper/models/wespeaker_en_voxceleb_resnet34.onnx, from the sherpa-onnx
speaker-recongition-models release) decides the rest. Embeddings alone could not separate the
voices under game audio. Check that the printed examples read like a dialogue. Force a line with
`@男性:テキスト` in the script.

**Timing.** Telops start at the speech onset found by Silero VAD on the audio, never during
the silence before it, because Whisper's word starts run early.

**Transcribe.** Batched large-v3 on a GPU: 3 h of audio in ~2 min (RTX 4070 Ti). Pass `--prompt`
as a comma list of the streamer's name, the game and its terms. Never a sentence: Whisper
echoes a sentence prompt back as speech. Repetition loops and prompt echoes are dropped
automatically (the log says how many words). Twitch chat comes through the public GQL endpoint
when TwitchDownloaderCLI is absent. It is often a sparse sample, so treat it as a weak signal.
Transcription is reproducible for the same prompt, but a different prompt yields a different
transcript, with other token splits and timings. Once `script:` lines are aligned and QC passes,
do not re-transcribe with a new prompt. Fix names in the script instead.

**When scores are flat** (no chat, a reaction-heavy game), the candidate list is a weak guide.
Read `transcript.txt` end to end (a 3-hour stream is about 20k chars) and pick moments yourself.
Check frames with `calibrate` or an ffmpeg tile before fixing a window.

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
Use `segments: [[a,b], ...]` to drop tangents inside a window. Silence trimming keeps only
speech, so a silent visual payoff (a game-over screen, a monster reveal) needs
`keep: [[a,b]]` or it is cut. Audible dead air over 1 s is also cut from the audio itself,
because Whisper can stretch one token across a pause.

**Text on screen (Shorts).**
- `band_text` (top band): the theme or collab, ≤8 chars. 「ちいかわ×麻雀」「雀魂×役満」
- `hook` (big bottom text): the situation + promise, ≤18 chars, ends with ！？ or www when
  it fits. Put `\n` where the line should break. 「一点読みで\n国士無双ロン!?」
- `layout`: `letterbox` (default, game in the middle), `split` (face cam on top, game below,
  set `face_rect` from a `calibrate` frame), `crop` (full-screen vertical crop of one area).
- `zoom`: a punch-in (`scale` 1.15–1.25, `dur` 1–1.5 s) on the payoff moment.
- `se`: sound effect on the payoff, only files in `clipper/assets/se/` (licensed ones only).
- `overlays`: reaction images, only from `clipper/assets/images/` (licensed ones only).

**Telops (`script` → `align`).** Whisper's Japanese word timestamps split tokens mid-word
(「いいねーう」「ちやっちまえ」), so auto `subs` need fixing line by line. Instead, write the
corrected lines in order under `script:` and run `align`, which times each line to the characters
it matches and reports lines it could not find. Prefix `*` = emph. Put `\n` where a Short line
should break (≤11 chars a row). A line in （…） is a translation of game/English audio. It is
timed by its neighbours and left out of the ASR sync check. Keep the authored file as
`clips.src.yaml` and copy it over `clips.yaml` before `align`, because `align` rewrites `clips.yaml`.
Drop any line the qc re-transcription does not hear rather than keep a guess.
Proofread every line against the audio context and `glossary.yaml`:
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
「バケモノ役満『ドラ一色』」. `thumbnail_at`: the frame of the payoff screen, ideally with both
characters in view. Dark frames are brightened automatically. When the game draws its own HUD
top-left, leave the long-form `label` empty.

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
