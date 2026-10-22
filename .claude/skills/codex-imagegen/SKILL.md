---
name: codex-imagegen
description: Generate images (illustrations, thumbnails, article eyecatches, icons, mockups, diagrams-as-pictures) by delegating to Codex's built-in image generation from Claude Code, then save and visually check them. Use whenever the user asks for an image to be created, drawn or generated, since Claude cannot output raster images itself.
---

# codex-imagegen: Claude plans and checks, Codex draws

Claude writes the image brief and checks the result. Codex (`$imagegen`, gpt-image-2)
generates the image. No computer use and no copy-paste between apps. The user already
accepts that this uses Codex quota (image turns cost roughly 3–5× a text turn).

## Steps
1. **Preflight (first time in a session):** run `scripts/codex-check.sh`.
   - Codex missing → tell the user the one install command.
   - Not logged in → tell the user to run `codex login` once in a terminal.
   - Don't try to work around a failed check.
2. **Decide the path:** default `assets/<yyyymmdd>-<short-slug>.png`, inside the project. Ask only
   if the user named a destination.
3. **Write the brief.** Fill in what's known and infer the rest from context:
   - purpose and where it's used (X post, article header, slide…)
   - aspect ratio/size (X image 16:9, square 1:1, story 9:16)
   - subject, composition, style, colors
   - any text in the image: exact wording; keep Japanese text short or leave it out and
     add it later
   - what to avoid
4. **Generate:** `scripts/codex-imagegen.sh <path> "<brief>"`. The script runs `codex exec` with a
   workspace-write sandbox, then checks the file exists and really is an image.
5. **Look at it:** Read the saved image. Check it against the brief: subject, text spelled
   correctly, composition, no artifacts.
6. **Fix:** if it misses, rewrite the brief with the specific fix and regenerate to a new file
   (`-v2`). Stop after 2 retries and show the best version with what's still off (see team-brief).
7. **Report:** saved path(s), the brief used, and anything not as requested.

## Batches
For more than ~5 images, state the count and confirm once before starting (quota). Generate
one sample first, check it, then the rest with the same style block.

## Fallbacks
- Script fails but Codex works interactively → `/codex:rescue --fresh` with the same brief
  and the path (plugin `codex@openai-codex`, enabled in `.claude/settings.json`).
- Codex unavailable → Canva `generate-image` / Figma `generate_image` / Adobe Firefly
  connectors (the user must authorize them in claude.ai first).

## Notes
- Built-in `$imagegen` works without an API key. If the user sets `OPENAI_API_KEY`, Codex may
  bill per token instead.
- Never claim an image was generated without the script's success output and a visual check.
