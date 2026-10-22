#!/usr/bin/env bash
# Generate one image with Codex's built-in image generation and save it in this project.
# Usage: scripts/codex-imagegen.sh <output-path.png> "<image description>"
# The output path must be inside the current project (Codex's write sandbox is the workspace).
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: $0 <output-path.png> \"<image description>\"" >&2
  exit 1
fi
out="$1"; shift
prompt="$*"

"$(dirname "$0")/codex-check.sh" >/dev/null || { "$(dirname "$0")/codex-check.sh"; exit 2; }

root="$(pwd -P)"
mkdir -p "$(dirname "$out")"
abs="$(cd "$(dirname "$out")" && pwd -P)/$(basename "$out")"
case "$abs" in
  "$root"/*) ;;
  *) echo "NG: output must be inside $root (got $abs)" >&2; exit 1 ;;
esac
rm -f "$abs"

last="$(mktemp)"
trap 'rm -f "$last"' EXIT

codex exec --sandbox workspace-write --skip-git-repo-check -o "$last" "Generate exactly one image using your built-in image generation tool (\$imagegen).
Do not call external APIs, install packages, or edit any other file.
Save the final image as a PNG file at exactly this path: $abs
When done, reply with only the saved path, or with the reason if you could not.

Image request:
$prompt" >&2

# Verify: the file exists, is not empty, and really is an image.
if [ ! -s "$abs" ]; then
  echo "NG: no image was saved at $abs" >&2
  echo "Codex said: $(cat "$last")" >&2
  exit 4
fi
magic="$(head -c 4 "$abs" | od -An -tx1 | tr -d ' \n')"
case "$magic" in
  89504e47|ffd8ff*|52494646) ;;
  *) echo "NG: $abs is not a PNG/JPEG/WebP image (magic: $magic)" >&2; exit 5 ;;
esac
echo "$abs"
