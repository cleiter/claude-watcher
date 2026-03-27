# Changelog

## 2026-03-27

- Add system tray indicator with colored badge showing instance status
  (red with count for asking, yellow for working, green for idle)
- Right-click tray menu lists each Claude instance with state and directory
- `--tray` flag: `auto` (default), `yes`, or `no`

## 2026-03-26

- Initial release: tmux-based monitor for Claude Code instances
- Real-time dashboard showing asking/working/idle states with color coding
- Desktop notifications via `notify-send` for background windows needing input
- Terminal bell support (`--bell`) on state changes
- Display order: asking (red) → working (yellow) → idle (green)
- Context usage percentage and idle/wait duration tracking
- Sub-second poll interval support (default 2s)
- Detection of permission prompts, numbered choice menus, and spinner activity
