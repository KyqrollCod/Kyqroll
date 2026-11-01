#!/usr/bin/env bash
# Relay one Charakuru checkpoint request from Claude to Codex, run inside the kit folder.
# Usage:
#   scripts/charakuru-relay.sh <kit-dir> --check
#       Zero-cost preflight: Codex reads AGENTS.md and reports whether this non-interactive
#       mode has image generation, browser control and Blender MCP. Generates nothing.
#   scripts/charakuru-relay.sh <kit-dir> <request.txt> [addendum.txt]
#       Sends the app's request text (copied from the app, unchanged) plus Claude's addendum.
# Env: CHARAKURU_SANDBOX (default workspace-write) is passed to `codex exec --sandbox`.
# Every run appends a line to <kit-dir>/charakuru-relay.log, and Codex's last message is saved
# next to it as charakuru-last-reply.txt.
set -euo pipefail

kit="${1:?kit dir required}"; shift
[ -f "$kit/AGENTS.md" ] || { echo "NG: $kit has no AGENTS.md (unzip the Releases kit, not Source code)" >&2; exit 1; }
"$(dirname "$0")/codex-check.sh" >/dev/null || { "$(dirname "$0")/codex-check.sh"; exit 2; }

sandbox="${CHARAKURU_SANDBOX:-workspace-write}"
reply="$kit/charakuru-last-reply.txt"
log="$kit/charakuru-relay.log"

if [ "${1:-}" = "--check" ]; then
  prompt="Read the root AGENTS.md of this kit. Do NOT start any production step, do NOT generate images,
do NOT open Tripo, and do NOT spend any credits. Only report, as a short checklist:
1) Node.js version and whether the local app is running or can be started,
2) whether image generation is available to you in this session,
3) whether browser control (needed for Tripo) is available to you in this session,
4) whether Blender, the VRM add-on and Blender MCP are reachable,
5) anything else AGENTS.md requires that is missing.
Answer each item with yes/no plus the evidence."
  label="check"
else
  req="${1:?request.txt required}"; add="${2:-}"
  [ -s "$req" ] || { echo "NG: request file is empty: $req" >&2; exit 1; }
  prompt="$(cat "$req")"
  if [ -n "$add" ]; then
    prompt="$prompt

--- Additional instructions from the director (Claude). Follow them unless they conflict with the kit's rules; if they conflict, stop and say so. ---
$(cat "$add")"
  fi
  label="request:$(basename "$req")"
fi

echo "$(date '+%F %T') start $label sandbox=$sandbox" >> "$log"
set +e
( cd "$kit" && codex exec --sandbox "$sandbox" --skip-git-repo-check -o "$reply" "$prompt" ) >&2
rc=$?
set -e
echo "$(date '+%F %T') end   $label exit=$rc" >> "$log"
[ -s "$reply" ] && cat "$reply"
exit $rc
