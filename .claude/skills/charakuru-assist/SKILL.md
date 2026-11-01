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

## Director mode: Claude → Codex → Charakuru → Tripo → result
The user wants Claude to drive Codex precisely and spend as few tokens and credits as possible.
Claude never edits the kit and never replaces the app's request text. It adds checks around it.

**Where Claude runs:** on the user's desktop, either a Claude Code session in the kit folder (or
in Kyqroll, with the kit path given), or this cloud session attached to the kit folder via
Remote Control (`list_computer_folders` → `request_computer_folder`). If neither is possible,
say so instead of guessing.

**Relay:** `scripts/charakuru-relay.sh <kit-dir> <request.txt> [addendum.txt]` runs `codex exec`
inside the kit with the app's request text unchanged (it carries the `agent-session.mjs begin …
REQUEST_ID` line) plus Claude's addendum. Each request is self-contained, because the kit keeps
state in `project.charakit`, so a fresh exec per checkpoint is correct. The script logs to
`charakuru-relay.log` and saves Codex's last reply to `charakuru-last-reply.txt` in the kit folder.

**Step 0, once, free:** `scripts/charakuru-relay.sh <kit-dir> --check`. Codex only reports
whether this non-interactive mode has image generation, browser control (Tripo) and Blender MCP.
If browser control or Blender is missing in exec mode, don't force it:
- Try `CHARAKURU_SANDBOX=danger-full-access` only with the user's explicit OK, since it lifts
  Codex's file and network sandbox.
- Or fall back to Claude writing the exact addendum and the user pasting request + addendum
  into the Codex app.

**Getting the request text:** the user presses the app's 次へ button and copies the request
text. Claude saves it to a temp file (or the user pastes it to Claude instead of Codex).
Never write or modify a request ID by hand. An expired request means re-copy it from the app.

**Gates (cost control):**
| Before | Claude checks | Cost avoided |
|---|---|---|
| Checkpoint 2 (8 images) | Source-art QA below, by viewing the image | wasted image generations |
| Checkpoint 3 (Tripo candidates) | Views all 8 images and the three-view: same hair length/ornaments, outfit colors and asymmetry on the correct side, no body in head images, no back hair in body images, T-pose, closed mouth | Tripo credits on bad inputs |
| Redo | Fix only the failing image with a precise addendum ("left view: ribbon on the character's right, as in source"). Max 2 redos per image, then escalate to the user | runaway regeneration |
| Candidate pick | Claude recommends (head: face shape and symmetry, wireframe density; body: clean hands, feet and clothing silhouette), but **the user decides**. The kit requires it | re-texturing a wrong pick |
| Motion check | Shoulders, elbows, knees bending, hair and skirt not clipping. Any fix requests name the exact part | full re-rig |

**Addendum template:**
```
対象: <checkpoint / image / part>
守ること: 元絵のデザイン(<具体的特徴>)を変えない。指定箇所以外は再生成しない。
直すこと: <箇所> を <どう> 。
止める条件: 判断が必要なら作業を止めて理由と画像を示す。追加のTripoクレジットを使う前に確認を取る。
報告: 変更したファイル、使った生成回数とTripo操作、未確認事項。
```

**After each relay:** read `charakuru-last-reply.txt`, view the produced images or screenshots,
compare them against the gate checklist, and tell the user in a few lines what was made, what
passed, and what needs their decision. Keep a running count of image generations and Tripo
runs in the log.

## Source illustration
- Must be art the user has rights to (PNG/JPEG/WebP ≤20MB, full body, settei-style works best).
  No sensitive content.
- **Source-art QA (Claude views it before anything is generated):**
  - the whole body is in frame, including hair tips, hands and shoes
  - front-facing, or nearly
  - no heavy occlusion by props or effects
  - the outfit's left/right differences are readable
  - clean lines and roughly ≥1000px tall
  - a plain or simple background
  List any fails with a fix suggestion and only start checkpoint 2 when the user accepts the art.
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
