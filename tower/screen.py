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
from . import palette as P
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


class CursesPalette:
    """Lazy, bounded colour pairs; an initialized pair is never repurposed.

    Reusing pair numbers for new gradients changes already painted cells. When
    a small terminal exhausts its pair table, approximate with the nearest
    existing pair instead. Styles and quantised colours are cached across frames.
    """

    def __init__(self, curses, enabled: bool = True):
        self.curses = curses
        self.enabled = enabled and not P.colors_disabled() and curses.has_colors()
        self.background = -1
        self.count = self.limit = 0
        self.pairs: dict[tuple[int, int], int] = {}
        self.approximations: dict[tuple[int, int], int] = {}
        self.attributes: dict[tuple[str, str], int] = {}
        if not self.enabled:
            return
        try:
            curses.start_color()
            self.count = (1 << 24) if curses.COLORS >= (1 << 24) else (256 if curses.COLORS >= 256 else min(8, curses.COLORS))
            self.limit = max(0, min(curses.COLOR_PAIRS - 1, 1024))
            try:
                curses.use_default_colors()
            except curses.error:
                self.background = curses.COLOR_BLACK
            if self.count < 8 or not self.limit:
                self.enabled = False
                return
            # Reserve essential text and selection tones before gradient charts.
            for style in ("white", "sel", "cyan", "green", "yellow", "red", "magenta", "blue"):
                parsed = P.resolve(style)
                self._pair(self._index(parsed.foreground), self._index(parsed.background, background=True))
            if not self.pairs:
                self.enabled = False
        except curses.error:
            self.enabled = False

    def _index(self, color, background=False):
        if color is None:
            if background or self.background == -1:
                return self.background
            color = P.rgb(P.PALETTE["white"])
        if self.count >= (1 << 24):
            return (color[0] << 16) | (color[1] << 8) | color[2]
        return P.color_index(color, self.count)

    def _rgb(self, index, default):
        if index < 0:
            return P.rgb(P.PALETTE[default])
        if self.count >= (1 << 24):
            return ((index >> 16) & 255, (index >> 8) & 255, index & 255)
        return P.INDEXED[index]

    def _pair(self, foreground: int, background: int) -> int:
        key = (foreground, background)
        if key in self.pairs:
            return self.pairs[key]
        if key in self.approximations:
            return self.approximations[key]
        c = self.curses
        if len(self.pairs) < self.limit:
            number = len(self.pairs) + 1
            try:
                c.init_pair(number, foreground, background)
                result = c.color_pair(number)
                self.pairs[key] = result
                return result
            except (c.error, OverflowError, ValueError):
                # Some curses builds expose more pairs than init_pair supports.
                self.limit = len(self.pairs)
        if not self.pairs:
            return 0

        def distance(existing):
            fg, bg = existing
            a, b = self._rgb(foreground, "white"), self._rgb(fg, "white")
            x, y = self._rgb(background, "black"), self._rgb(bg, "black")
            return sum((v - w) ** 2 for v, w in zip(a, b)) + 2 * sum((v - w) ** 2 for v, w in zip(x, y))

        result = self.pairs[min(self.pairs, key=distance)]
        if len(self.approximations) >= 4096:
            self.approximations.clear()
        self.approximations[key] = result
        return result

    def attr(self, style: str, theme: str = "default") -> int:
        key = (style, theme)
        if key in self.attributes:
            return self.attributes[key]
        c = self.curses
        parsed = P.resolve(style, theme if self.enabled else "mono")
        result = 0
        flags = {"bold": c.A_BOLD, "dim": c.A_DIM, "rev": c.A_REVERSE, "under": c.A_UNDERLINE}
        for flag in parsed.flags:
            result |= flags[flag]
        if self.enabled and (parsed.foreground is not None or parsed.background is not None):
            result |= self._pair(self._index(parsed.foreground), self._index(parsed.background, background=True))
            if "sel" in style.split("+") and self.limit < 2:
                result |= c.A_REVERSE
        # Keep plugin-generated styles from growing memory indefinitely.
        if len(self.attributes) >= 4096:
            self.attributes.clear()
        self.attributes[key] = result
        return result


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
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.timeout(200)
        stdscr.keypad(True)
        if hasattr(curses, "set_escdelay") and "ESCDELAY" not in os.environ:
            curses.set_escdelay(200)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
            curses.mouseinterval(0)
        except curses.error:
            pass
        palette = CursesPalette(curses, cfg["color"])

        def paint(y, x0, segs, width, height):
            x = x0
            for text, style in segs:
                if x >= width or y >= height:
                    break
                text = L.cut(text, width - x, True) if L.vlen(text) > width - x else text
                try:
                    stdscr.addstr(y, x, text, palette.attr(style, app.theme))
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
            stdscr.timeout(100 if app.animations_enabled and app.completion.active else 200)
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
            stdscr.noutrefresh()
            curses.doupdate()
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
                    if bstate & curses.BUTTON1_DOUBLE_CLICKED and (app.tab in ("jobs", "history") or (app.tab == "log" and app.logs.browser)):
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
                files = views.files
                path = views.pager_path(store.snapshot(), app)
                if path and files.exists(path):
                    curses.endwin()
                    try:
                        subprocess.call(files.less_argv(path))
                    finally:
                        stdscr.touchwin()
                        stdscr.refresh()
                else:
                    app.say("no stdout file yet for this job")

    curses.wrapper(main)


def run_watch(app, views, sampler, store, actions, cfg, interval: float, color: bool, width_hint: int = 120):
    """The non-interactive animated screen (Ctrl-C exits)."""
    import shutil
    interactive = sys.stdout.isatty() and os.environ.get("TERM", "").lower() != "dumb"
    if interactive:
        sys.stdout.write("\033[?25l\033[2J")
    rung = 0
    previous: list[str] = []
    previous_size = None
    try:
        while True:
            size = shutil.get_terminal_size((width_hint, 40))
            width, height = max(1, size.columns), max(1, size.lines)
            app.width = width
            app.tick()
            snap = store.snapshot()
            rows, _ = views.compose(snap, app, width, height if interactive else None, actions)
            if interactive and len(rows) == height:
                rows[-1] = L.clip_row([(" Ctrl-C exit", "bold"), (f"  |  watch every {interval:g}s", "dim")], width)
            started = sum(1 for e in snap["events"] if e.get("kind") == "started" and not e.get("old"))
            bell = "\a" if app.bell and started > rung else ""
            rung = started
            frame = L.to_text(rows, width, color, theme=app.theme).split("\n")
            if interactive:
                if previous_size is not None and previous_size != (width, height):
                    sys.stdout.write("\033[2J")
                    previous = []
                # Update changed lines only, retaining a stable screen on SSH.
                for y, line in enumerate(frame):
                    if y >= len(previous) or line != previous[y]:
                        sys.stdout.write(f"\033[{y + 1};1H{line}\033[K")
                if len(previous) > len(frame) and len(frame) < height:
                    sys.stdout.write(f"\033[{len(frame) + 1};1H\033[J")
                sys.stdout.write(bell)
            else:
                sys.stdout.write("\n".join(frame) + "\n" + bell)
            previous = frame
            previous_size = (width, height)
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h\n" if interactive else "")
        sys.stdout.flush()


def once_text(app, views, store, actions, width: int, color: bool, tab: Optional[str] = None) -> str:
    if tab:
        app.tab = tab
    app.width = width
    app.tick()
    snap = store.snapshot()
    rows, _ = views.compose(snap, app, width, None, actions)
    return L.to_text(rows, width, color, theme=app.theme)


def once_json(store) -> str:
    snap = store.snapshot()
    return json.dumps(to_plain({k: v for k, v in snap.items() if k not in ("hist_cpu", "hist_gpu")}), indent=1, default=str)
