"""Painters: the curses screen (interactive, with mouse and resize), the ANSI animated screen (--watch) and one
frame of text (--once) or JSON (--json)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Optional

from . import layout as L
from .model import to_plain
from .views import stdout_path

KEYNAMES = {}
CB_MAP = {"green": "blue", "red": "yellow", "yellow": "magenta"}       # colour-blind safe: blue / orange(yellow) / magenta instead of green / red / yellow
# A readable palette on modern terminals; basic terminals retain their native eight colours.
PALETTE_256 = {"green": 114, "yellow": 221, "red": 203, "cyan": 81, "magenta": 183, "blue": 75, "white": 252}


def style_attr(style: str, theme: str, base: dict, colors: dict, bold: int) -> int:
    """A '+'-joined style -> a curses attribute under the theme.  mono and reader use no colour (red / yellow become
    bold); high adds bold to every colour; cb remaps green / red / yellow to blue / yellow / magenta."""
    a = 0
    plain = theme in ("mono", "reader")
    for s in style.split("+"):
        if theme == "cb" and s in CB_MAP:
            s = CB_MAP[s]
        if s in base and (s != "sel" or plain or "sel" not in colors):
            a |= base[s]
        elif not plain and s in colors:
            a |= colors[s] | (bold if theme == "high" else 0)
        elif plain and s in ("red", "yellow", "magenta"):
            a |= bold
    return a


def key_name(ch: int, curses) -> Optional[str]:
    """A curses key code -> the name the controller and the config use."""
    if ch == -1:
        return None
    if ch == curses.KEY_RESIZE:
        return "resize"
    if ch == curses.KEY_MOUSE:
        return "mouse"
    table = {curses.KEY_UP: "up", curses.KEY_DOWN: "down", curses.KEY_LEFT: "left", curses.KEY_RIGHT: "right", curses.KEY_NPAGE: "pgdn", curses.KEY_PPAGE: "pgup",
             curses.KEY_HOME: "home", curses.KEY_END: "end", curses.KEY_BTAB: "btab", curses.KEY_ENTER: "enter", curses.KEY_BACKSPACE: "backspace",
             9: "tab", 10: "enter", 13: "enter", 27: "esc", 32: "space", 127: "backspace", 8: "backspace"}
    if ch in table:
        return table[ch]
    if 33 <= ch < 127:
        return chr(ch)
    return None


def run_curses(app, views, sampler, store, actions, cfg):
    import curses
    import locale
    locale.setlocale(locale.LC_ALL, "")

    def main(stdscr):
        curses.curs_set(0)
        stdscr.timeout(200)
        stdscr.keypad(True)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
            curses.mouseinterval(0)
        except curses.error:
            pass
        base = dict(bold=curses.A_BOLD, dim=curses.A_DIM, rev=curses.A_REVERSE, under=curses.A_UNDERLINE, sel=curses.A_REVERSE | curses.A_BOLD)
        colors, default_colors = {}, {}
        if cfg["color"] and curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
                bg = -1
            except curses.error:
                bg = curses.COLOR_BLACK
            for i, (name, c) in enumerate([("green", curses.COLOR_GREEN), ("yellow", curses.COLOR_YELLOW), ("red", curses.COLOR_RED), ("cyan", curses.COLOR_CYAN),
                                           ("magenta", curses.COLOR_MAGENTA), ("blue", curses.COLOR_BLUE), ("white", curses.COLOR_WHITE)], start=1):
                curses.init_pair(i, c, bg)
                colors[name] = curses.color_pair(i)
                if curses.COLORS >= 256 and curses.COLOR_PAIRS >= 16:
                    curses.init_pair(i + 8, PALETTE_256[name], bg)
                    default_colors[name] = curses.color_pair(i + 8)
            try:
                curses.init_pair(8, curses.COLOR_WHITE, curses.COLOR_BLUE)
                colors["sel"] = curses.color_pair(8) | curses.A_BOLD
            except curses.error:
                pass

        default_colors = {**colors, **default_colors}

        def attr(style):
            palette = default_colors if app.theme == "default" else colors
            return style_attr(style, app.theme, base, palette, curses.A_BOLD)

        def paint(y, x0, segs, width, height):
            x = x0
            for text, style in segs:
                if x >= width or y >= height:
                    break
                text = L.cut(text, width - x, True) if L.vlen(text) > width - x else text
                try:
                    stdscr.addstr(y, x, text, attr(style))
                except curses.error:
                    pass
                x += L.vlen(text)

        hits = []
        rung = 0
        app.views_ref = views
        while not app.quit:
            app.tick()
            snap = store.snapshot()
            height, width = stdscr.getmaxyx()
            app.width = width
            rows, hits = views.compose(snap, app, width, height, actions)
            app.last_hits = hits
            stdscr.erase()
            for y, segs in enumerate(rows[:height]):
                paint(y, 0, segs, width, height)
            ov = views.overlay(snap, app, width, height)
            if ov:
                for y, x0, segs in ov:
                    paint(y, x0, segs, width, height)
            started = sum(1 for e in snap["events"] if e.get("kind") == "started" and not e.get("old"))
            if app.bell and started > rung:
                curses.beep()
            rung = started
            stdscr.refresh()
            ch = stdscr.getch()
            name = key_name(ch, curses)
            if name is None or name == "resize":
                continue
            if name == "mouse":
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                shift = bool(bstate & getattr(curses, "BUTTON_SHIFT", 0))
                if bstate & (getattr(curses, "BUTTON3_CLICKED", 0) | getattr(curses, "BUTTON3_PRESSED", 0)):
                    app.click(my, mx, hits, button="right")
                elif bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED | curses.BUTTON1_DOUBLE_CLICKED):
                    app.click(my, mx, hits, button="left", shift=shift)
                    if bstate & curses.BUTTON1_DOUBLE_CLICKED and app.tab in ("jobs", "history"):
                        app.handle("enter")
                elif bstate & getattr(curses, "BUTTON4_PRESSED", 0):
                    for _ in range(3 if app.tab == "log" else 1):
                        app.handle("up")
                elif bstate & getattr(curses, "BUTTON5_PRESSED", 0):
                    for _ in range(3 if app.tab == "log" else 1):
                        app.handle("down")
                continue
            app.handle(name)
            if getattr(app, "want_less", False):
                app.want_less = False
                j = app.selected_job()
                files = views.files
                path = stdout_path(j, snap["details"].get(j.id, {}), files) if j else ""
                if path and files.exists(path):
                    curses.endwin()
                    try:
                        subprocess.call(files.less_argv(path))
                    finally:
                        stdscr.refresh()
                else:
                    app.say("no stdout file yet for this job")

    curses.wrapper(main)


def run_watch(app, views, sampler, store, actions, cfg, interval: float, color: bool, width_hint: int = 120):
    """The non-interactive animated screen (Ctrl-C exits)."""
    import shutil
    sys.stdout.write("\033[?25l\033[2J")
    rung = 0
    try:
        while True:
            app.tick()
            snap = store.snapshot()
            width = max(80, shutil.get_terminal_size((width_hint, 40)).columns)
            rows, _ = views.compose(snap, app, width, None, actions)
            started = sum(1 for e in snap["events"] if e.get("kind") == "started" and not e.get("old"))
            bell = "\a" if app.bell and started > rung else ""
            rung = started
            sys.stdout.write("\033[H\033[J" + L.to_text(rows, width, color) + "\n" + bell)
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h\n")
        sys.stdout.flush()


def once_text(app, views, store, actions, width: int, color: bool, tab: Optional[str] = None) -> str:
    if tab:
        app.tab = tab
    app.tick()
    snap = store.snapshot()
    rows, _ = views.compose(snap, app, width, None, actions)
    return L.to_text(rows, width, color)


def once_json(store) -> str:
    snap = store.snapshot()
    return json.dumps(to_plain({k: v for k, v in snap.items() if k not in ("hist_cpu", "hist_gpu")}), indent=1, default=str)
