#!/usr/bin/env python3
"""
claude-watcher: Monitor Claude Code instances across tmux panes.
Shows which Claudes are idle/waiting for input vs actively working.
"""

import argparse
import os
import select
import subprocess
import re
import shutil
import sys
import tempfile
import termios
import threading
import time
import tty
from dataclasses import dataclass
from pathlib import Path

try:
    import gi
    gi.require_version('AyatanaAppIndicator3', '0.1')
    gi.require_version('Gtk', '3.0')
    from gi.repository import AyatanaAppIndicator3 as AppIndicator, Gtk, GLib
    HAS_APPINDICATOR = True
except (ImportError, ValueError):
    HAS_APPINDICATOR = False


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Monitor Claude Code instances across tmux panes.",
    )
    p.add_argument(
        "-n", "--interval", type=float, default=2, metavar="SEC",
        help="poll interval in seconds (default: 2)",
    )
    p.add_argument(
        "--bell", default="no", choices=["yes", "no"],
        help="terminal bell on state changes (default: no)",
    )
    p.add_argument(
        "--notify", default="yes", choices=["yes", "no", "all"],
        help="desktop notifications: yes=background windows only, all=always, no=off (default: yes)",
    )
    p.add_argument(
        "--tray", default="auto", choices=["yes", "no", "auto"],
        help="system tray indicator: yes=require, auto=if available, no=off (default: auto)",
    )
    return p.parse_args()

MIN_INTERVAL = 0.1

# ANSI colors
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
NC = "\033[0m"


@dataclass
class ClaudePane:
    pane_id: str
    window_label: str
    window_active: bool
    directory: str
    context_pct: str
    state: str  # "asking", "idle", or "working"
    last_message: str
    work_status: str


class TrayIndicator:
    """System tray icon showing Claude instance status."""

    def __init__(self):
        self._icon_dir = tempfile.mkdtemp(prefix="claude-watcher-")
        self._generate_icons()
        self._indicator = AppIndicator.Indicator.new(
            "claude-watcher",
            "claude-gray",
            AppIndicator.IndicatorCategory.APPLICATION_STATUS,
        )
        self._indicator.set_icon_theme_path(self._icon_dir)
        self._indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

        menu = Gtk.Menu()
        item = Gtk.MenuItem(label="No Claude instances")
        item.set_sensitive(False)
        menu.append(item)
        menu.show_all()
        self._indicator.set_menu(menu)

        self._thread = threading.Thread(target=Gtk.main, daemon=True)
        self._thread.start()

    _CLAUDE_PATH = (
        "M4.709 15.955l4.72-2.647.08-.23-.08-.128H9.2l-.79-.048-2.698-.073"
        "-2.339-.097-2.266-.122-.571-.121L0 11.784l.055-.352.48-.321.686.06"
        " 1.52.103 2.278.158 1.652.097 2.449.255h.389l.055-.157-.134-.098"
        "-.103-.097-2.358-1.596-2.552-1.688-1.336-.972-.724-.491-.364-.462"
        "-.158-1.008.656-.722.881.06.225.061.893.686 1.908 1.476 2.491"
        " 1.833.365.304.145-.103.019-.073-.164-.274-1.355-2.446-1.446-2.49"
        "-.644-1.032-.17-.619a2.97 2.97 0 01-.104-.729L6.283.134 6.696"
        " 0l.996.134.42.364.62 1.414 1.002 2.229 1.555 3.03.456.898.243"
        ".832.091.255h.158V9.01l.128-1.706.237-2.095.23-2.695.08-.76.376"
        "-.91.747-.492.584.28.48.685-.067.444-.286 1.851-.559 2.903-.364"
        " 1.942h.212l.243-.242.985-1.306 1.652-2.064.73-.82.85-.904.547"
        "-.431h1.033l.76 1.129-.34 1.166-1.064 1.347-.881 1.142-1.264"
        " 1.7-.79 1.36.073.11.188-.02 2.856-.606 1.543-.28 1.841-.315"
        ".833.388.091.395-.328.807-1.969.486-2.309.462-3.439.813-.042.03"
        ".049.061 1.549.146.662.036h1.622l3.02.225.79.522.474.638-.079"
        ".485-1.215.62-1.64-.389-3.829-.91-1.312-.329h-.182v.11l1.093"
        " 1.068 2.006 1.81 2.509 2.33.127.578-.322.455-.34-.049-2.205"
        "-1.657-.851-.747-1.926-1.62h-.128v.17l.444.649 2.345 3.521.122"
        " 1.08-.17.353-.608.213-.668-.122-1.374-1.925-1.415-2.167-1.143"
        "-1.943-.14.08-.674 7.254-.316.37-.729.28-.607-.461-.322-.747.322"
        "-1.476.389-1.924.315-1.53.286-1.9.17-.632-.012-.042-.14.018"
        "-1.434 1.967-2.18 2.945-1.726 1.845-.414.164-.717-.37.067-.662"
        ".401-.589 2.388-3.036 1.44-1.882.93-1.086-.006-.158h-.055L4.132"
        " 18.56l-1.13.146-.487-.456.061-.746.231-.243 1.908-1.312-.006.006z"
    )

    def _svg_claude(self, color: str, text: str = "") -> str:
        """Generate a Claude logo icon in SVG."""
        text_el = ""
        if text:
            text_el = (f'<circle cx="17" cy="17" r="7.5" fill="white"/>'
                       f'<circle cx="17" cy="17" r="7" fill="{color}"/>'
                       f'<text x="17" y="23" text-anchor="middle" '
                       f'font-size="16" font-weight="bold" fill="white" '
                       f'font-family="sans-serif">{text}</text>')
        return ('<?xml version="1.0"?>\n'
                '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22"'
                ' viewBox="0 0 24 24">\n'
                f'<path d="{self._CLAUDE_PATH}" fill="{color}"'
                f' fill-rule="nonzero"/>\n'
                f'{text_el}\n</svg>')

    def _generate_icons(self):
        icons = {
            "claude-gray": ("#6b7280", ""),
            "claude-green": ("#22c55e", ""),
            "claude-yellow": ("#eab308", ""),
            "claude-red": ("#ef4444", ""),
        }
        for i in range(1, 10):
            icons[f"claude-red-{i}"] = ("#ef4444", str(i))
        for name, (color, text) in icons.items():
            with open(os.path.join(self._icon_dir, f"{name}.svg"), "w") as f:
                f.write(self._svg_claude(color, text))

    def update(self, panes: list[ClaudePane]):
        """Schedule a tray update on the GTK thread."""
        GLib.idle_add(self._do_update, list(panes))

    def _do_update(self, panes: list[ClaudePane]):
        asking = [p for p in panes if p.state == "asking"]
        working = [p for p in panes if p.state == "working"]
        idle = [p for p in panes if p.state == "idle"]

        if asking:
            n = len(asking)
            icon = f"claude-red-{n}" if n <= 9 else "claude-red"
            self._indicator.set_icon_full(icon, f"{n} asking")
        elif working:
            self._indicator.set_icon_full("claude-yellow", "working")
        elif idle:
            self._indicator.set_icon_full("claude-green", "idle")
        else:
            self._indicator.set_icon_full("claude-gray", "no instances")

        menu = Gtk.Menu()
        if not panes:
            item = Gtk.MenuItem(label="No Claude instances")
            item.set_sensitive(False)
            menu.append(item)
        else:
            state_icons = {"asking": "⏳", "working": "⚡", "idle": "💤"}
            for p in asking + working + idle:
                label = f"{state_icons[p.state]}  {p.window_label}   {p.directory}"
                item = Gtk.MenuItem(label=label)
                item.set_sensitive(False)
                menu.append(item)
            menu.append(Gtk.SeparatorMenuItem())
            parts = []
            if asking:
                parts.append(f"{len(asking)} asking")
            if working:
                parts.append(f"{len(working)} working")
            if idle:
                parts.append(f"{len(idle)} idle")
            summary = Gtk.MenuItem(label=f"{len(panes)} total: {', '.join(parts)}")
            summary.set_sensitive(False)
            menu.append(summary)
        menu.show_all()
        self._indicator.set_menu(menu)
        return False  # one-shot, don't repeat

    def cleanup(self):
        GLib.idle_add(Gtk.main_quit)
        shutil.rmtree(self._icon_dir, ignore_errors=True)


def tmux_list_panes() -> list[tuple[str, str, str, str, str, bool]]:
    """Return list of (pane_id, pid, command, cwd, window_label, window_active) for all tmux panes."""
    sep = "|||"
    try:
        out = subprocess.run(
            ["tmux", "list-panes", "-a", "-F",
             f"#{{session_name}}:#{{window_index}}.#{{pane_index}}{sep}"
             f"#{{pane_pid}}{sep}#{{pane_current_command}}{sep}"
             f"#{{pane_current_path}}{sep}#{{window_index}}:#{{window_name}}{sep}"
             f"#{{window_active}}"],
            capture_output=True, text=True, timeout=5,
        )
        results = []
        for line in out.stdout.strip().splitlines():
            parts = line.split(sep, 5)
            if len(parts) == 6:
                results.append((parts[0], parts[1], parts[2], parts[3], parts[4], parts[5] == "1"))
        return results
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def tmux_capture_pane(pane_id: str) -> str:
    """Capture the visible content of a tmux pane."""
    try:
        out = subprocess.run(
            ["tmux", "capture-pane", "-t", pane_id, "-p"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout
    except subprocess.TimeoutExpired:
        return ""


def has_permission_prompt(last_lines: str) -> bool:
    """Detect if a permission/choice prompt is showing (numbered options)."""
    lines = last_lines.splitlines()

    # Look for the ❯ cursor on a numbered option line (original check)
    for i, line in enumerate(lines):
        if "❯" in line and re.search(r'\d+\.', line):
            return True
        if "❯" in line:
            for j in range(i + 1, min(i + 5, len(lines))):
                if re.match(r'^\s+\d+\.', lines[j]):
                    return True

    # General case: detect consecutive numbered options (1. ... / 2. ...)
    # regardless of cursor character, but not if an idle ❯ prompt follows
    for i, line in enumerate(lines):
        if re.match(r'^\s*[❯›>]?\s*1\.\s', line):
            for j in range(i + 1, min(i + 5, len(lines))):
                if re.match(r'^\s+2\.\s', lines[j]):
                    # A bare ❯ below means these are just numbered text, not a prompt
                    if not any("❯" in lines[k] and not re.search(r'\d+\.', lines[k])
                               for k in range(j + 1, len(lines))):
                        return True

    # Footer line present in Claude Code choice prompts
    for line in lines:
        if "Esc to cancel" in line and "Tab to amend" in line:
            return True

    return False


def is_working(last_lines: str) -> bool:
    """Detect if Claude is actively working (not idle)."""
    for line in last_lines.splitlines():
        # Spinner characters followed by a verb ending in … (ellipsis U+2026)
        # e.g. "✽ Effecting…", "✢ Synthesizing…", "· Perambulating…", "✻ Processing…"
        if re.match(r'^[✽✢·*✻☵✿⚡✤✣✦✧⏳]\s+\w+.*…', line):
            return True
        # Indented working status from agents/tools
        if re.match(r'^\s+(Running|Waiting)…', line):
            return True
        # Claude tool activity lines: "Reading N file…", "Checking…", etc.
        if re.match(r'^\s*(Reading|Writing|Checking|Searching|Loading|Generating|Thinking)\s.*…', line):
            return True
    return False


def extract_info(content: str) -> tuple[str, str, str]:
    """Extract directory, context %, and last Claude message from pane content."""
    lines = content.splitlines()

    # Directory from status line
    directory = ""
    for line in reversed(lines):
        m = re.search(r'(~/\S+)', line)
        if m:
            directory = m.group(1)
            break

    # Context percentage
    context_pct = ""
    for line in reversed(lines):
        m = re.search(r'🌕\s*(\d+%)', line)
        if m:
            context_pct = m.group(1)
            break

    # Context: find the most relevant thing Claude is asking/saying
    last_msg, is_asking = extract_context(lines)

    return directory, context_pct, last_msg, is_asking


def extract_context(lines: list[str]) -> tuple[str, bool]:
    """Find what Claude is asking — permission prompts, questions, or last message.

    Returns (message, is_asking) where is_asking=True means Claude needs
    a specific answer (permission prompt with numbered options, or a
    free-form question ending with ?), not just idle.
    """
    # Find the last ❯ prompt line
    prompt_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if "❯" in lines[i]:
            prompt_idx = i
            break

    if prompt_idx is not None:
        prompt_line = lines[prompt_idx]
        # Permission/choice prompt: ❯ followed by an option like "1. Yes"
        has_options = bool(re.search(r'❯\s+\d+\.', prompt_line))

        # Also check lines below ❯ for numbered options (2., 3., etc.)
        if not has_options:
            for i in range(prompt_idx + 1, min(prompt_idx + 5, len(lines))):
                if re.match(r'^\s+\d+\.', lines[i]):
                    has_options = True
                    break

        if has_options:
            # Find the question text above the options
            for i in range(prompt_idx - 1, max(prompt_idx - 10, -1), -1):
                stripped = lines[i].strip()
                if not stripped or re.match(r'^[─╌━═]+', stripped):
                    continue
                if stripped.endswith("?"):
                    return stripped[:122], True
                break
            return "waiting for selection", True

        # No numbered options — check for free-form questions / errors
        text_lines = []
        for i in range(prompt_idx - 1, max(prompt_idx - 15, -1), -1):
            stripped = lines[i].strip()
            if not stripped:
                if text_lines:
                    break
                continue
            # Skip timing lines like "* Churned for 1m 25s" / "✻ Cogitated for 3m"
            if re.match(r'^[*✱✽✢·✻☵✿⚡✤✣✦✧⏳]\s+\w+\s+for\s+\d', stripped):
                continue
            # Skip prompt-area separators, stop at content separators
            if re.match(r'^[─╌━═]+', stripped):
                if text_lines:
                    break
                continue
            # Skip user input lines (previous ❯ prompts with typed text)
            if '❯' in stripped:
                if text_lines:
                    break
                continue
            # Include ● lines (Claude's message) but stop after
            if stripped.startswith('● '):
                text_lines.append(stripped[2:])
                break
            text_lines.append(stripped)

        if text_lines:
            text_block = ' '.join(reversed(text_lines))
            # Match ? at sentence boundaries (space/end), not inside quotes
            matches = list(re.finditer(r'\?(?:\s|$)', text_block))
            if matches:
                q_idx = matches[-1].start()
                period_idx = text_block.rfind('. ', 0, q_idx)
                sent_start = period_idx + 2 if period_idx >= 0 else 0
                question = text_block[sent_start:q_idx + 1].strip()
                return question[:122], True

            # Check for API errors
            for tl in text_lines:
                if 'API Error:' in tl:
                    m = re.search(r'API Error:\s*(\d+)', tl)
                    error_desc = "API error"
                    if m:
                        type_m = re.search(r'"error":\{"type":"(\w+)"', tl)
                        error_desc = f"API error {m.group(1)}"
                        if type_m:
                            etype = type_m.group(1)
                            etype = etype.replace('_error', '').replace('_', ' ')
                            error_desc += f" ({etype})"
                    return error_desc, True

    # Fallback: detect numbered choices without ❯ cursor
    for i, line in enumerate(lines):
        if re.match(r'^\s*[❯›>]?\s*1\.\s', line):
            for j in range(i + 1, min(i + 5, len(lines))):
                if re.match(r'^\s+2\.\s', lines[j]):
                    # A bare ❯ below means these are just numbered text, not a prompt
                    if any("❯" in lines[k] and not re.search(r'\d+\.', lines[k])
                           for k in range(j + 1, len(lines))):
                        break
                    # Found numbered options — look for question above
                    for k in range(i - 1, max(i - 10, -1), -1):
                        stripped = lines[k].strip()
                        if not stripped or re.match(r'^[─╌━═]+', stripped):
                            continue
                        if stripped.endswith("?"):
                            return stripped[:122], True
                        break
                    return "waiting for selection", True

    # Fallback: "Esc to cancel" footer means a prompt is active
    for line in lines:
        if "Esc to cancel" in line and "Tab to amend" in line:
            return "waiting for selection", True

    # Fallback: last ● message (Claude's regular output) — just idle
    for line in reversed(lines):
        if line.startswith("● "):
            return line[2:122], False

    return "", False


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m{seconds % 60}s"
    else:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h{m}m"


def scan_panes() -> list[ClaudePane]:
    """Scan all tmux panes and return Claude instances with their state."""
    panes = []
    for pane_id, pid, cmd, cwd, window_label, window_active in tmux_list_panes():
        if cmd != "claude":
            continue

        content = tmux_capture_pane(pane_id)
        if not content:
            continue

        last_lines = "\n".join(content.rstrip().splitlines()[-15:])
        directory, context_pct, last_msg, is_asking = extract_info(content)

        # Fallback: use tmux's pane cwd when status line isn't visible
        if not directory and cwd:
            directory = cwd.replace(str(Path.home()), "~")

        has_prompt = "❯" in last_lines
        permission = has_permission_prompt(last_lines)

        working_now = is_working(last_lines)

        if working_now:
            state = "working"
        elif permission:
            state = "asking"
        elif has_prompt:
            state = "asking" if is_asking else "idle"
        else:
            state = "working"

        # Extract work status line for working panes
        work_status = ""
        if state == "working":
            for line in reversed(last_lines.splitlines()):
                if re.match(r'^[✽✢·*✻☵✿⚡✤✣✦✧⏳]\s+.*', line):
                    work_status = line[:50]
                    break
            if not work_status:
                work_status = "working…"

        panes.append(ClaudePane(
            pane_id=pane_id,
            window_label=window_label,
            window_active=window_active,
            directory=directory or "?",
            context_pct=context_pct,
            state=state,
            last_message=last_msg,
            work_status=work_status,
        ))

    return panes


def main():
    args = parse_args()
    notify_available = args.notify != "no" and shutil.which("notify-send") is not None

    tray = None
    if args.tray != "no":
        if HAS_APPINDICATOR:
            tray = TrayIndicator()
        elif args.tray == "yes":
            print("Error: AppIndicator not available. "
                  "Install gir1.2-ayatanaappindicator3-0.1",
                  file=sys.stderr)
            sys.exit(1)

    interval = max(args.interval, MIN_INTERVAL)
    idle_since: dict[str, float] = {}
    # Seed with current state so the first poll doesn't fire notifications
    initial_panes = scan_panes()
    prev_idle: set[str] = {p.pane_id for p in initial_panes if p.state != "working"}
    prev_asking: set[str] = {p.pane_id for p in initial_panes if p.state == "asking"}
    notif_ids: dict[str, str] = {}  # pane_id -> desktop notification ID

    CLR = "\033[K"  # clear to end of line

    # Alternate screen buffer + hide cursor + cbreak for keypress detection
    old_term = termios.tcgetattr(sys.stdin)
    sys.stdout.write("\033[?1049h\033[?25l")
    sys.stdout.flush()
    tty.setcbreak(sys.stdin.fileno())

    try:
        while True:
            now = time.time()
            out: list[str] = []
            out.append(f"{BOLD}  Claude Watcher{NC}")
            out.append("")

            panes = scan_panes()

            if tray:
                tray.update(panes)

            asking = [p for p in panes if p.state == "asking"]
            idle = [p for p in panes if p.state == "idle"]
            working = [p for p in panes if p.state == "working"]
            not_working = asking + idle

            for p in asking:
                if p.pane_id not in idle_since:
                    idle_since[p.pane_id] = now
                dur = format_duration(int(now - idle_since[p.pane_id]))
                out.append(f"  {BOLD}{RED}⏳  {p.window_label}{NC}"
                           f"  {p.directory:<35s}"
                           f"  {RED}wait {dur}{NC}"
                           f"  {p.context_pct}")
                if p.last_message:
                    out.append(f"      {DIM}{p.last_message}{NC}")
                out.append("")

            for p in working:
                idle_since.pop(p.pane_id, None)
                out.append(f"  {YELLOW}✓   {p.window_label}{NC}"
                           f"  {p.directory:<35s}"
                           f"  {DIM}{p.work_status}{NC}")
                out.append("")

            for p in idle:
                if p.pane_id not in idle_since:
                    idle_since[p.pane_id] = now
                dur = format_duration(int(now - idle_since[p.pane_id]))
                out.append(f"  {BOLD}{GREEN}💤  {p.window_label}{NC}"
                           f"  {p.directory:<35s}"
                           f"  {GREEN}idle {dur}{NC}"
                           f"  {p.context_pct}")
                if p.last_message:
                    out.append(f"      {DIM}{p.last_message}{NC}")
                out.append("")

            if not panes:
                out.append(f"  {DIM}No Claude instances found in tmux{NC}")
            else:
                parts = [f"{len(panes)} total"]
                if asking:
                    parts.append(f"{NC}{RED}{len(asking)} asking{NC}{DIM}")
                if working:
                    parts.append(f"{NC}{YELLOW}{len(working)} working{NC}{DIM}")
                if idle:
                    parts.append(f"{NC}{GREEN}{len(idle)} idle{NC}{DIM}")
                out.append(f"  {DIM}── {' · '.join(parts)} ──{NC}")

            out.append("")
            interval_str = f"{interval:g}"
            out.append(f"  {DIM}Poll {interval_str}s · [ ] adjust · Ctrl-C to quit{NC}")

            # Single write: cursor home, each line clears its tail, then wipe below
            buf = "\033[H" + "\n".join(line + CLR for line in out) + "\033[J"
            sys.stdout.write(buf)
            sys.stdout.flush()

            # Housekeeping
            current_ids = {p.pane_id for p in panes}
            for pid in list(idle_since):
                if pid not in current_ids:
                    del idle_since[pid]

            current_idle = {p.pane_id for p in not_working}
            if args.bell == "yes" and (current_idle - prev_idle):
                sys.stdout.write("\a")
                sys.stdout.flush()
            prev_idle = current_idle

            current_asking = {p.pane_id for p in asking}
            new_asking = current_asking - prev_asking
            resolved_asking = prev_asking - current_asking
            if notify_available:
                for p in asking:
                    if p.pane_id in new_asking and (args.notify == "all" or not p.window_active):
                        msg = p.last_message or "waiting for input"
                        try:
                            result = subprocess.run(
                                ["notify-send", "-u", "critical", "--print-id",
                                 f"Claude {p.window_label}", msg],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=2,
                            )
                            nid = result.stdout.decode().strip()
                            if nid:
                                notif_ids[p.pane_id] = nid
                        except (subprocess.TimeoutExpired, OSError):
                            pass
                for pane_id in resolved_asking:
                    nid = notif_ids.pop(pane_id, None)
                    if nid:
                        subprocess.Popen(
                            ["gdbus", "call", "--session",
                             "--dest", "org.freedesktop.Notifications",
                             "--object-path", "/org/freedesktop/Notifications",
                             "--method", "org.freedesktop.Notifications.CloseNotification",
                             nid],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        )
            prev_asking = current_asking

            # Sleep while listening for [ ] keypresses
            deadline = time.time() + interval
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                ready, _, _ = select.select([sys.stdin], [], [], min(remaining, 0.1))
                if ready:
                    ch = sys.stdin.read(1)
                    if ch == '[':
                        if interval <= 1:
                            interval = round(interval - 0.1, 1)
                        elif interval <= 5:
                            interval = round(interval - 0.5, 1)
                        else:
                            interval = round(interval - 1, 1)
                        interval = max(interval, MIN_INTERVAL)
                        break  # redraw immediately
                    elif ch == ']':
                        if interval < 1:
                            interval = round(interval + 0.1, 1)
                        elif interval < 5:
                            interval = round(interval + 0.5, 1)
                        else:
                            interval = round(interval + 1, 1)
                        break

    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_term)
        if tray:
            tray.cleanup()
        # Restore cursor and main screen buffer
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
