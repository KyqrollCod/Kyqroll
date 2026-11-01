---
name: charakuru-assist
description: Help the user make a VRM avatar from one character illustration with Charakuru (きゃらくる), Nano's Tripo-sponsored kit where Codex does the work and the user approves at checkpoints. Covers setup, the 5 checkpoints, troubleshooting, preparing the source illustration (incl. generating an original one), and optional add-ons like HairDeck hair. Use when the user mentions きゃらくる/Charakuru, Tripo character modeling, or making a VRM/3D avatar from an illustration.
---

# charakuru-assist: Claude guides, Codex builds, the user decides

Charakuru (github.com/nanocle/Charakuru, v1.1.0 as of 2026-11) turns one full-body illustration
into a VRM 1.0 avatar. It is a local app plus 9 Codex skills. **Codex is the worker**: it draws
the 8 part images, operates Tripo in the browser, and drives Blender via Blender MCP. Claude
can't replace it (no image generation or browser use in the kit's flow). Claude's job is to set
up, explain, unblock and review.

## License: never redistribute
Source-available custom license, not open source. Personal modification is fine, and so is
commercial use while the user's annual revenue and total funding are both under ¥100M.
Never copy the kit or its bundled assets into this repo or anywhere public. Link to the
Releases page instead.

## Setup (on the user's desktop, explained step by step)
1. Download `charakuru-<version>-….zip` from github.com/nanocle/Charakuru/releases. Not the
   auto "Source code" zip, which has docs only. Unzip it into a writable folder.
2. Needs: Node.js 22+, a desktop Chrome-family browser, Codex with image generation and browser
   use, a Tripo account logged in in that browser, Blender 5.2 + VRM Add-on + Blender MCP. Tripo
   credits and the Codex quota are the user's own.
3. Open the folder in Codex and say: 「ルートAGENTS.mdを読んで、このキットでキャラクター制作を始めたい」.
   Codex checks the environment and starts the app at http://127.0.0.1:8766.
   Don't duplicate its preflight.
4. The app starts in English. Settings (bottom left) → Language → 日本語.

## The loop (5 checkpoints)
The user checks in the app → presses 次へ → copies the request text → pastes it into the Codex chat.
Codex works, then the app updates and stops at the next checkpoint. Checkpoints:
1. register the source art
2. review the 8 images (head incl. hair + body × 4 views; a single image can be redone)
3. pick head and body from 4 Tripo candidates each
4. adjust proportions on the three-view
5. check motion (walk + physics) → VRM を書き出す

Remind the user: copying alone does nothing, the text must be sent in the chat. Keep the app open.
Everything saves to one `project.charakit`. Restart from the same folder to resume. Back up the
whole folder (VRM/Blend files too).

## Troubleshooting
- Windows Codex `blocked by policy` on start: the old request text used `start`. Update the kit and
  re-copy the request from the app (new text uses `begin`), per the kit's tutorial.
- Face looks rough or motion is odd: that's the problem the kit exists to fix. Redo the specific
  image or candidate at its checkpoint rather than restarting.
- Bugs go to the kit's Issues (no PRs accepted). Never upload private models, credentials or source art.

## Source illustration
- Must be art the user has rights to (PNG/JPEG/WebP ≤20MB, full body, settei-style works best).
  No sensitive content.
- No art yet → make an original one with `codex-imagegen`: full-body character sheet, front view,
  T- or A-pose, plain background, flat lighting, no cropping. Look at the result and check that
  hands, feet and the hair silhouette are fully visible before feeding it in.

## Optional add-ons (experimental, offer, don't push)
- **HairDeck** (see CLAUDE.md): if the kit's hair sways poorly, generate hair cards from the same
  art (HF Space, export **VRM**), then ask Codex via Blender MCP to fit and replace the hair. The
  cards have no textures, so paint or recolor them. Not part of the kit's supported flow, and early
  quality is mixed.
- **Expressions tab**: after rigging, the kit can author expressions (8 eyes / 10 mouths / 5 brows).
- **unslop**: unrelated to the avatar itself; use it only for a web page that shows off the avatar.

## Report back
Which checkpoint the user is at, what's next, and any blocker with the exact message.
