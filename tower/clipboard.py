"""Copying text out of a terminal session: the terminal's clipboard through OSC 52 (works over ssh in terminals that
allow it: iTerm2, Windows Terminal, kitty, alacritty, foot, wezterm, xterm with allowWindowOps, tmux with
set-clipboard on), a local clipboard tool when one is reachable, and always a file, so nothing is ever lost."""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from typing import List, Optional

TOOLS = [["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"], ["clip.exe"]]
OSC52_LIMIT = 100_000                                     # bytes of base64 most terminals accept in one sequence


def osc52(text: str, tty_path: str = "/dev/tty") -> bool:
    """Write the OSC 52 sequence to the controlling terminal (wrapped for tmux and screen)."""
    data = base64.b64encode(text.encode("utf-8")).decode("ascii")
    if len(data) > OSC52_LIMIT:
        data = base64.b64encode(text.encode("utf-8")[:OSC52_LIMIT * 3 // 4]).decode("ascii")
    seq = f"\033]52;c;{data}\a"
    if os.environ.get("TMUX"):
        seq = "\033Ptmux;" + seq.replace("\033", "\033\033") + "\033\\"
    elif os.environ.get("STY"):
        seq = "\033P" + seq + "\033\\"
    try:
        with open(tty_path, "wb") as f:
            f.write(seq.encode("ascii"))
            f.flush()
        return True
    except OSError:
        try:
            sys.__stdout__.write(seq)
            sys.__stdout__.flush()
            return True
        except Exception:
            return False


def local_tool(text: str) -> Optional[str]:
    """Pipe to the first clipboard tool that exists and can reach a display; the tool's name on success."""
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) or sys.platform in ("darwin", "win32", "cygwin")
    for cmd in TOOLS:
        if shutil.which(cmd[0]) is None:
            continue
        if cmd[0] in ("xclip", "xsel", "wl-copy") and not has_display:
            continue
        try:
            r = subprocess.run(cmd, input=text.encode("utf-8"), capture_output=True, timeout=5)
            if r.returncode == 0:
                return cmd[0]
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def to_file(text: str, state_dir: Optional[str], name: str = "clipboard.txt") -> Optional[str]:
    base = state_dir or os.path.join(os.getcwd(), "tower-exports")
    try:
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, name)
        with open(path, "w") as f:
            f.write(text)
        return path
    except OSError:
        return None


def copy(text: str, state_dir: Optional[str] = None, tty_path: str = "/dev/tty", use_osc52: bool = True, use_tools: bool = True) -> str:
    """Send ``text`` everywhere it can go; returns a one-line account of where it went."""
    where: List[str] = []
    if use_osc52 and osc52(text, tty_path):
        where.append("terminal clipboard (OSC 52)")
    if use_tools:
        tool = local_tool(text)
        if tool:
            where.append(tool)
    path = to_file(text, state_dir)
    if path:
        where.append(path)
    n = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    return f"copied {n} line{'s' if n != 1 else ''} to " + (", ".join(where) if where else "nowhere (no terminal, tool or writable directory)")
