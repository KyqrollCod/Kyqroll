---
name: coconala-lp-studio
description: Run the owner's Coconala LP business end to end — publish and edit listings, answer buyers, send the hearing sheet, build the LP, verify, deliver, log and report. Use when a session or scheduled task says "coconala-lp-studio", or when asked to check the Coconala inbox, handle an order, update listings, or write the daily/weekly business report.
---

# coconala-lp-studio

The spec is `docs/spec.md`. Read it at the start of every run, because it holds the price table,
the authorization scope (§4), the ToS guardrails (§5) and the report rules (§7). This skill is only
the procedure. If the two disagree, the spec wins, and you flag the mismatch in the report.

## 0. Preconditions (stop and report if any fails)
- You are running on the owner's PC with Claude in Chrome, and Chrome is already logged in to
  coconala.com. Never type, store or ask for the password. If logged out, stop and put
  「ココナラに再ログインしてください」 at the top of 要判断.
- Read the last entries of `docs/ops-log.md` and the newest file in `docs/reports/`, so you know
  open deals and promised deadlines. List the files you actually read in the report.
- Check the sending rules in `docs/spec.md` §5. The owner chose B: Claude sends replies from the
  start. Do NOT contact Coconala support about automation (owner's decision: don't draw attention
  in the early phase); `docs/coconala/inquiry-to-coconala.md` is on hold. Stop sending, and report it
  first, if Coconala shows any warning, restriction or policy notice. When the §5 re-judge trigger
  is met, put "A/B 再判定" at the top of 要判断 in that weekly report.

## 1. Inbox run (scheduled, several times a day)
1. Open the Coconala message, talk room, 見積り相談 and notification pages. Collect new items.
2. Classify each item: inquiry (target / non-target industry) · hearing answers · revision request ·
   other · needs decision (spec §4 list).
3. Draft the reply from `docs/coconala/replies.md`. Run its pre-send check. Send when allowed by §0.
4. Append one line per item to `docs/ops-log.md` (deal ID, type, gist, deadline, next action). No
   buyer names, contacts or message bodies.
5. If hearing answers are complete, start §2 for that deal in the same run when time allows.

## 2. Production (per deal)
Work in `deliveries/<deal-id>/` on the owner's PC. The folder is git-ignored, so buyer content
(answers, photos, their LP) never leaves that machine through the repo. Never save raw messages.
1. Persona sentence and section plan from the answers (`docs/coconala/hearing-sheet.md` checks).
   Use only facts the buyer gave. No invented numbers, testimonials or credentials.
2. Build `index.html` + `assets/`. Follow `.claude/skills/persona-lp/SKILL.md` for structure when the
   buyer wants a lively tone, or a calmer layout for 「きちんと／高級感」. Then run unslop's spacing,
   type and copy passes (`.claude/skills/unslop/SKILL.md`). Fonts from Google Fonts only. No
   external scripts.
3. Images: the buyer's photos first. Generated images only with the image option, via
   `.claude/skills/codex-imagegen/SKILL.md`, and only as LP material.
4. Copy rules: no efficacy guarantees, no 「必ず」「絶対」「No.1」 without the buyer's proof, prices
   with 税込/税別 as given. Japanese line breaks checked at 390px.
5. Screenshots with Playwright at 390×844 and 1280×800 (deviceScaleFactor 1 for checks). Look at
   them yourself before sending.
6. Independent check (team-brief rule): give a separate subagent the spec, the hearing answers
   summary and the built files, not your claims. Checklist: every required answer used and
   correct · CTA links go to the buyer's URL · no invented facts · no broken layout at both widths ·
   contrast ≥4.5:1 on buttons · no external-contact wording · `prefers-reduced-motion` respected.
   Fix what it finds, then send the first draft (screenshots) inside the deadline.
7. Revisions: apply, re-screenshot, re-check the changed parts. Count revisions against the 2 included.
8. Delivery: zip of the site folder, the publishing guide (`docs/coconala/publish-guide.md`,
   adapted with the buyer's site name and checked against the live Netlify screens), and
   screenshots. Use Coconala's 納品 flow.

## 3. Listings
- Source text: `docs/coconala/listings.md`. When you publish or edit a listing, copy the exact
  live text back into that file and log it.
- Thumbnails: build as HTML and screenshot to PNG (1220×1240 or the size Coconala asks for). Text
  must be readable on a phone.
- Portfolio: `samples/` LPs, each labeled as a sample with a fictional business. Never present a
  sample as a real client.

## 4. Reports
- Daily (only when something happened) and weekly (Monday). Use `docs/reports/TEMPLATE.md`, save as
  `docs/reports/YYYY-MM-DD.md`, and end the session with the same text.
- 要判断 first. Write each item as one decision with its impact and your recommendation.
- Weekly: numbers from the Coconala dashboard, and the position against spec §8 kill criteria.

## 5. Saving work
Commit reports, ops-log and listing text after each run, push to the working branch, and merge the
PR per CLAUDE.md. Never commit buyer messages, names, contacts or their photos.

## Stop conditions
- Same delivery bug fixed twice and still failing → stop, write a handoff in the report, switch agent.
- Anything in spec §4 "要判断" or "絶対にしない" → do not act, report.
- Coconala shows a warning, restriction or policy notice → stop all sending, report at the top.
