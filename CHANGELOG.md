# Changelog

## 2026-03-27

- Add system tray indicator with colored badge showing instance status
  (red with count for asking, yellow for working, green for idle)
- Right-click tray menu lists each Claude instance with state and directory
- `--tray` flag: `auto` (default), `yes`, or `no`
- Dynamic poll rate adjustment with `[` / `]` keys
  (0.1s steps up to 1s, 0.5s steps up to 5s, 1s steps after)
- Fix false "asking" detection when user's own typed question contains `?`
- Detect free-form questions (sentences ending with `?`) as "asking" state,
  not just numbered option prompts
- Detect API errors (529 overloaded, 429 rate limit, etc.) as "asking" state
- Add unit tests for state detection functions

## 2026-03-26

- Initial release: tmux-based monitor for Claude Code instances
- Real-time dashboard showing asking/working/idle states with color coding
- Desktop notifications via `notify-send` for background windows needing input
- Terminal bell support (`--bell`) on state changes
- Display order: asking (red) → working (yellow) → idle (green)
- Context usage percentage and idle/wait duration tracking
- Sub-second poll interval support (default 2s)
- Detection of permission prompts, numbered choice menus, and spinner activity
