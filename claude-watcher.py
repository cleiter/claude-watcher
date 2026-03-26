#!/usr/bin/env python3
"""
claude-watcher: Monitor Claude Code instances across tmux panes.
Shows which Claudes are idle/waiting for input vs actively working.
"""

import argparse
import subprocess
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Monitor Claude Code instances across tmux panes.",
    )
    p.add_argument(
        "-n", "--interval", type=float, default=0.5, metavar="SEC",
        help="poll interval in seconds (default: 0.5)",
    )
    p.add_argument(
        "--bell", default="no", choices=["yes", "no"],
        help="terminal bell on state changes (default: no)",
    )
    p.add_argument(
        "--notify", default="yes", choices=["yes", "no", "all"],
        help="desktop notifications: yes=background windows only, all=always, no=off (default: yes)",
    )
    return p.parse_args()

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
    a specific answer (permission prompt with numbered options), not just idle.
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

    idle_since: dict[str, float] = {}
    # Seed with current state so the first poll doesn't fire notifications
    initial_panes = scan_panes()
    prev_idle: set[str] = {p.pane_id for p in initial_panes if p.state != "working"}
    prev_asking: set[str] = {p.pane_id for p in initial_panes if p.state == "asking"}

    CLR = "\033[K"  # clear to end of line

    # Alternate screen buffer + hide cursor
    sys.stdout.write("\033[?1049h\033[?25l")
    sys.stdout.flush()

    try:
        while True:
            now = time.time()
            out: list[str] = []
            out.append(f"{BOLD}  Claude Watcher{NC}")
            out.append("")

            panes = scan_panes()
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
            interval_str = f"{args.interval:g}"
            out.append(f"  {DIM}Poll {interval_str}s · Ctrl-C to quit{NC}")

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

            new_asking = {p.pane_id for p in asking} - prev_asking
            if notify_available:
                for p in asking:
                    if p.pane_id in new_asking and (args.notify == "all" or not p.window_active):
                        msg = p.last_message or "waiting for input"
                        subprocess.Popen(
                            ["notify-send", "-u", "critical",
                             f"Claude {p.window_label}", msg],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        )
            prev_asking = {p.pane_id for p in asking}

            time.sleep(args.interval)

    finally:
        # Restore cursor and main screen buffer
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
