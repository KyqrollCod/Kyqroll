---
name: persona-lp
description: Build a Japanese conversion LP with a strong persona concept (e.g. "広告オタク集団"): a mobile-first single column with PC side panels, a character mascot, a "habit → だから → benefit" promise loop, terminal/file-window motifs and fixed dual CTAs. Use when the user wants a punchy, characterful service LP, lead-gen page or 資料DL page, or references the LEAD OTAKU (wad-no-wad.com/otaku-x) style.
---

# persona-lp: a concept-driven LP pattern

Analyzed from LEAD OTAKU (wad-no-wad.com/otaku-x, 2026-11). Take the **structure and
techniques** only. Never copy their copy, characters, logo, illustrations or exact palette and
type pairing. Each LP gets its own persona, derived from the client's real strength.

## Why it works
1. **One persona carries the whole page.** A weakness ("オタク": obsessive, can't follow manuals)
   is reframed as the reason to hire. Every section restates the persona, so the page reads as one idea.
2. **Promise loop**: `PROMISE 0N` → "オタクは〜できない" (habit, in a bordered box) → ↓ → pill
   「だから」 → black-band headline with the benefit word in accent → a mini-visual → 4–6 lines of
   plain body text. Repeated 5 times, the rhythm makes long copy easy to skim.
3. **Motifs prove the persona instead of claiming it.** Each promise gets a fake app window
   (`hearing_sheet.md`, `copy_check.exe`, `daily_report.csv`, `trend_watch.log`, `funnel.log`) with
   checklists, before→after numbers, tags or a funnel. A typing terminal in the hero (`$ lead-otaku
   --analyze`). The visuals are the persona's own material: code, logs, data.
4. **Mascot crew**: one flat character drawn in several colors = the team roles
   (Director/Designer/Engineer/Editor), reused in each promise and in the side panel.
5. **Conversion plumbing**: a sticky header CTA, dual CTAs (download = gradient pill, phone =
   dark pill) repeated after the hero, after the promises and at the end, then voices with
   specific numbers, then the form.

## Layout system
- Mobile-first column `--col: 480px` centered on a 20px grid-paper background. On ≥1024px, fixed
  side panels: left = logo, hero line and mascot crew, right = an INDEX nav of numbered sections
  with the current one highlighted. The PC view is the phone LP framed, so one design serves both.
- Section rhythm: light grid sections alternate with dark (`--ink`) sections. Marquee bands
  ("Who are we? ◆") separate chapters. Cards and windows tilt a little (rotate ±1–4°).
- Breakpoints only at 481px and 1024px, plus `prefers-reduced-motion`.

## Type & color recipe (make your own values)
- Four roles: a bold italic display Latin (Inter 800–900 italic) for logos, numerals and labels.
  A Japanese sans (Noto Sans JP) for UI and body. A Japanese serif (Noto Serif JP) for the big hero
  question. A mono (JetBrains Mono) for the terminal and window motifs.
- Neutral ink and paper ramp + **one hot accent with a 2-stop gradient** (theirs: orange→red-orange)
  + one highlighter accent (theirs: lime) for marker-underlines + soft pastel `--bg` tints, one per
  promise card. Pick hues from the client's world, not theirs.
- Highlight technique: white text on black bands, the key word in the accent, and big gradient
  numerals for PROMISE 01–05 and counts (「5つの約束」).

## Motion
Small and purposeful: typing caret in the terminal, marquee bands, float/bob on mascots, fade-up on
scroll, a sheen on the CTA, a phone-icon ring. Everything is off under `prefers-reduced-motion`.

## Copy formula
- Hero: target callout 「＼ ○○に悩む全ての経営者様へ ／」 + provocative question
  「まだ○○を"△△"に任せてないの？」.
- Each promise: 「△△は〜できない」 → 「だから」 → 「御社だけ／被らない／安定した／売上につながる」 benefit.
- Mark sample numbers 「※数値はイメージです」. Voices need real company names and concrete numbers.
  Ask the client and never invent them.

## Relation to unslop
This style deliberately uses gradients, badges, tilts and loud copy as **brand character**. Don't
run unslop over it wholesale. Use unslop's spacing, type and number-format passes only, and keep
the persona devices that carry meaning.

## Build checklist
- [ ] Persona sentence: "We are ___ who can't help ___, so you get ___". Comes from real strengths.
- [ ] 3–5 promises, each with a habit, a benefit and a motif window made from the persona's material
- [ ] Mascot: generate with `codex-imagegen` (flat, thick outline, plain background, several color
      variants of one character), or skip it
- [ ] Dual CTA ×3 + sticky header CTA, phone CTA tap-to-call on mobile
- [ ] Side panels and INDEX on desktop, column readable at 390px
- [ ] Reduced motion respected, contrast ≥4.5:1 on accent buttons
- [ ] Image-only numbers labeled as samples. Voices and claims verified with the client
