# 🤖 claude-watcher

You're running 5 Claude instances across tmux windows and sessions. One of them
asked a permission question 47 minutes ago. Another one finished its
task and has been sitting at the prompt since lunch. You have no idea.

**claude-watcher** gives you a single dashboard for all your Claude
Code instances. No more "wait, how long has that been idle?"

## 📸 Screenshot

```
  Claude Watcher  11:58:20

  ⏳  3:infra   ~/w/p/infrastructure                  wait 1m48s  6%
      Do you want to make this edit to migration-plan.md?

  💤  1:webapp  ~/w/p/webapp                           idle 11m4s  11%
      All four commits created:

  💤  1:webapp  ~/w/p/webapp.assets                    idle 11m4s  34%
      Go for it! Restart the app and test.

  ✓   1:webapp  ~/w/p/webapp-frontend                  ✻ Flummoxing… (37s · ↑ 152 tokens)

  ── 4 total · 1 asking · 2 idle · 1 working ──

  Poll 3s · Ctrl-C to quit
```

## ✨ Features

- Scans all tmux panes for running Claude Code instances
- Three states:
  - 🔴 **Asking** — Claude needs your input (permission prompts, choices)
  - 🟡 **Idle** — Claude finished and is waiting
  - 🟢 **Working** — Claude is actively doing its thing
- 🔔 Desktop notifications (via `notify-send`) when Claude asks for input
- Shows tmux window name, working directory, context usage, and idle
  duration
- Flicker-free rendering using alternate screen buffer

## Usage

```
python3 claude-watcher.py [options]
```

Run it in a dedicated tmux pane:

```
python3 ~/claude-watcher/claude-watcher.py
```

Press `Ctrl-C` to quit.

### Options

| Flag | Description |
|------|-------------|
| `-n`, `--interval SEC` | Poll interval in seconds (default: 3) |
| `--bell yes\|no` | Terminal bell on state changes (default: no) |
| `--notify yes\|no` | Desktop notifications via notify-send (default: yes) |

## Requirements

- Python 3.10+
- tmux
- `notify-send` (optional, for desktop notifications)

## License

MIT
