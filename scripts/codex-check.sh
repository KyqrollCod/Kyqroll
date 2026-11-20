#!/usr/bin/env bash
# Preflight for Codex image generation: is the Codex CLI installed and logged in?
# Exit 0 = ready. Anything else prints what is missing.
set -u

if ! command -v codex >/dev/null 2>&1; then
  echo "NG: codex CLI not found. Install with: npm install -g @openai/codex"
  exit 2
fi
echo "OK: codex $(codex --version 2>/dev/null | head -n1)"

if codex login status >/dev/null 2>&1; then
  echo "OK: codex is logged in"
else
  echo "NG: codex is not logged in. Run in a terminal: codex login"
  exit 3
fi
