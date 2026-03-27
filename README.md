# 🤖 claude-watcher

You're running 5 Claude instances across tmux windows and sessions. One of them
asked a permission question 47 minutes ago. Another one finished its
task and has been sitting at the prompt since lunch. You have no idea.

**claude-watcher** gives you a single dashboard for all your Claude
Code instances. No more "wait, how long has that been idle?"

It also puts a **system tray indicator** in your panel — a colored badge
that shows at a glance if any Claude needs your attention, even when
you're in a different app.

![System tray indicator showing 2 instances needing input](screenshots/tray-indicator.png)

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
- 🔵 **System tray indicator** (Linux) — colored badge in your panel:
  - Red with count when instances need input
  - Yellow when working
  - Green when all idle
  - Right-click menu lists each instance with state and directory
  - Works on GNOME, KDE, XFCE, MATE, Budgie, and other desktops with
    AppIndicator/SNI support
- Shows tmux window name, working directory, context usage, and idle
  duration
- Flicker-free rendering using alternate screen buffer

## Usage

```
python3 claude-watcher.py [options]
```

Press `Ctrl-C` to quit.

### Options

| Flag | Description |
|------|-------------|
| `-n`, `--interval SEC` | Poll interval in seconds (default: 2, same as `watch`) |
| `--bell yes\|no` | Terminal bell on state changes (default: no) |
| `--notify yes\|no\|all` | Desktop notifications: yes=background only, all=always, no=off (default: yes) |
| `--tray yes\|no\|auto` | System tray indicator: auto=if available, yes=require, no=off (default: auto) |

## Requirements

- Python 3.10+
- tmux
- `notify-send` (optional, for desktop notifications)
- `gir1.2-ayatanaappindicator3-0.1` (optional, for system tray indicator)

## License

MIT
