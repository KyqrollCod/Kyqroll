# Kyqroll
## YouTube agent skills

Eleven project-local Claude Code skills live in `.claude/skills/yt-*`. They are vendored from
[Jakeschincariol/youtube-agent-skill](https://github.com/Jakeschincariol/youtube-agent-skill)
(MIT, see `.claude/skills/LICENSE.youtube-agent-skill`).

`/yt-script`, `/yt-package`, `/yt-edit`, `/yt-comment`, `/yt-plan`, `/yt-viral`, `/yt-retention`,
`/yt-shorts`, `/yt-seo`, `/yt-chapters`, `/yt-audit`

The bundled Python tools need only Python 3, with no dependencies. Every skill reads a voice
profile from `~/.claude/youtube/voice.md`. To create one, copy
`.claude/youtube/voice.template.md` there and fill it in.
