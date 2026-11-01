---
name: mesh-avatar
description: Make a Live2D-like 2D avatar (blink, lip sync, head turn, breathing, hair sway, expressions) from one illustration with Mesh Avatar Studio, then drive it with webcam and mic for OBS, Zoom or Meet. Use when the user wants a moving 2D avatar, VTuber or AITuber-style streaming, or a Live2D alternative, or mentions Mesh Avatar Studio or .mavatar.
---

# mesh-avatar: Live2D-style avatar from one illustration

Mesh Avatar Studio (github.com/shinshin86/mesh-avatar-studio, MIT; sample character Miko has her
own terms) builds a 2D mesh rig from one image. It is the practical **Live2D alternative**: there's
no hand-cut PSD and no Cubism editor. A coding agent places the rig and the user fine-tunes by
dragging points in a local editor.

## Who does what
- **Claude Code (Opus 5.5 is the repo's recommended pairing) does the build itself.** It follows the
  repo's `docs/agent-guide.md`: vision calibration → rig draft from zoomed grids → layers → pose
  checks → handover. Unlike Charakuru, Claude is the main builder here, not just a relay.
- **Codex adds drawn variants** (closed eyes, mouth shapes per vowel, expression eyes and mouths).
  Claude can't generate images. Copy the editor's 描き分け画像 request into Codex, or use
  `npm run create -- <image>` for a fully Codex one-shot (`--random` / `--prompt` if there's no art).
  Images and masks are sent to OpenAI. `--no-variants` keeps everything local.
- **The user**: provides or approves the art, drags points that look off, and judges the motion.

## Setup on the user's PC (Windows OK)
1. Needs Node.js 22.17+ and Git. For agent builds it also needs uv + Python 3.10+ and Playwright Chromium.
2. Run `npx create-mesh-avatar-studio`, `cd mesh-avatar-studio`, then `npm run dev`, and open the
   printed http://127.0.0.1:5173/. `npm run doctor` reports anything missing.
3. Windows: prefer `git clone` over ZIP (if using the ZIP, unblock it first). Let the user's own
   account create `projects/`, or the editor may not be able to read folders the agent creates.
4. Open that folder in Claude Code and say:
   「docs/agent-guide.ja.md に沿って、この画像からアバターを作って: <path>」.

## Running the build (Claude)
- Tell the user which model is running. Run the vision check (`tools/vision-check.py`) and
  report the score. If it fails, stop: the coordinates will be off.
- Best input: a transparent PNG, front-facing bust-up, head and shoulders visible. Warn about tilted
  faces, hands or hair over the face, and hats or glasses (they stay fixed unless added as overlays).
- Never commit, upload or copy the user's image out of `projects/` (variant generation with the
  user's OK is the one exception).
- Look at every check image the guide produces before moving on. Don't skip checks.

## Use
- Stream: 配信 tab → register the neutral pose → copy the OBS URL into a Browser source, 1080×1080,
  transparent background. Calls: OBS virtual camera → Zoom or Meet.
- Expressions on keys 1–8, lighting presets on Shift+1–8, toggleable overlays such as glasses.
- Share or move an avatar as a `.mavatar` file. The no-install Player:
  shinshin86.github.io/mesh-avatar-studio/ja/play/.
- Experimental: full-body weight shift and skirt sway (body tracking jitters more than the face).
  A Rust native runtime is also in progress.

## Choosing vs other tools
| Need | Pick |
|---|---|
| 2D Live2D-like streaming avatar, fast | **Mesh Avatar Studio** |
| 3D VRM avatar (VRChat, 3D apps) | Charakuru (`charakuru-assist`) |
| Unscripted big motions, cinematic shots | video generation (mesh rigs are weak outside their range, per the author) |
| True Live2D (.moc3) | still manual Cubism work. This tool doesn't export Live2D |

Original art for any of these: make it with `codex-imagegen` (front-facing bust-up, plain or
transparent background, mouth closed).
