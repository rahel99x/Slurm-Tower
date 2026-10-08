"""Painters: the curses screen (interactive, with mouse and resize), the ANSI animated screen (--watch) and one
frame of text (--once) or JSON (--json)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import deque
from typing import Optional

from . import layout as L
from . import palette as P
from .model import to_plain
from .views import stdout_path

KEYNAMES = {}
CB_MAP = {"green": "blue", "red": "yellow", "yellow": "magenta"}       # colour-blind safe: blue / orange(yellow) / magenta instead of green / red / yellow
# A readable palette on modern terminals; basic terminals retain their native eight colours.
PALETTE_256 = {"green": 114, "yellow": 221, "red": 203, "cyan": 81, "magenta": 183, "blue": 75, "white": 252}
INPUT_BATCH_LIMIT = 32
INPUT_BATCH_SECONDS = .008
POINTER_BATCH_LIMIT = 256
POINTER_BATCH_SECONDS = .012
MAINTENANCE_SECONDS = .2
_NAVIGATION_ACTIONS = frozenset(("up", "down", "page_up", "page_down", "home", "end"))
_INPUT_READERS = {}
_ESCAPE_KEYS = {"\x1b[1;5D": "ctrl-left", "\x1b[1;5C": "ctrl-right",
                "\x1b[1;3D": "alt-left", "\x1b[1;3C": "alt-right",
                "\x1bb": "alt-b", "\x1bf": "alt-f", "\x1bd": "alt-d",
                "\x1bu": "alt-u", "\x1br": "alt-r", "\x1b\x7f": "alt-backspace",
                "\x1b[A": "up", "\x1b[B": "down", "\x1b[C": "right", "\x1b[D": "left"}
_PASTE_START, _PASTE_END = "\x1b[200~", "\x1b[201~"
_SGR_MOUSE = re.compile(r"\x1b\[<(\d{1,5});(\d{1,5});(\d{1,5})([Mm])\Z", re.ASCII)
_ESCAPE_KEYS.update({"\x1b" + chr(code): "alt-" + chr(code) for code in range(ord("a"), ord("z") + 1)})
for _modifier, _number in (("alt", 3), ("ctrl", 5)):
    for _suffix, _key in (("A", "up"), ("B", "down"), ("C", "right"), ("D", "left"), ("H", "home"), ("F", "end")):
        _ESCAPE_KEYS[f"\x1b[1;{_number}{_suffix}"] = f"{_modifier}-{_key}"
    for _code, _key in ((3, "delete"), (5, "pgup"), (6, "pgdn")):
        _ESCAPE_KEYS[f"\x1b[{_code};{_number}~"] = f"{_modifier}-{_key}"
_ESCAPE_KEYS["\x1b[127;5u"] = "ctrl-backspace"
del _modifier, _number, _suffix, _key, _code


class _InputReader:
    """Decode fragmented pastes without executing payload keys or blocking frames."""
    def __init__(self, window):
        self.window = window
        self.escape = ""
        self.escape_time = 0.0
        self.pasting = False
        self.end = ""
        self.text = []
        self.queue = deque()
        self.discard_mouse = False

    def read(self, curses):
        if self.queue:
            return self.queue.popleft()
        deadline = time.monotonic() + INPUT_BATCH_SECONDS if self.escape or self.pasting or self.discard_mouse else None
        for _ in range(256):
            try:
                value = self.window.get_wch()
            except curses.error:
                if self.discard_mouse and time.monotonic() - self.escape_time >= .03:
                    self.discard_mouse = False
                if self.escape and time.monotonic() - self.escape_time >= .03:
                    pending, self.escape = self.escape, ""
                    if pending.startswith("\x1b[<"):
                        return None, None  # Incomplete reports never become commands.
                    self.queue.extend((key_name(ch, curses), None) for ch in pending[1:])
                    return "esc", None
                return None
            if self.discard_mouse:
                if value in ("M", "m"):
                    self.discard_mouse = False
                elif value == "\x1b":
                    self.discard_mouse = False
                    self.escape, self.escape_time = "\x1b", time.monotonic()
            elif self.pasting:
                # keypad is disabled so the end delimiter and pasted control
                # characters reach this parser in their original order.
                char = value if isinstance(value, str) else ""
                self.end += char
                while self.end and not _PASTE_END.startswith(self.end):
                    if len(self.text) < 4097:
                        self.text.append(self.end[0])
                    self.end = self.end[1:]
                if self.end == _PASTE_END:
                    self.pasting, self.end = False, ""
                    self.window.keypad(True)
                    text, self.text = "".join(self.text), []
                    return "paste", text
            elif self.escape:
                char = value if isinstance(value, str) else ""
                candidate = self.escape + char
                if candidate.startswith("\x1b[<"):
                    # Some tmux/screen terminfo entries advertise legacy X10
                    # input even though the terminal supports requested SGR.
                    # Decode fragmented reports without executing their bytes.
                    match = _SGR_MOUSE.fullmatch(candidate)
                    if match:
                        self.escape = ""
                        return "mouse", _sgr_mouse(match, curses)
                    if len(candidate) <= 23 and re.fullmatch(r"\x1b\[<[0-9;]*", candidate, re.ASCII):
                        self.escape = candidate
                    else:
                        self.escape = ""
                        self.discard_mouse = not candidate.endswith(("M", "m"))
                        return None, None
                elif candidate == _PASTE_START:
                    self.escape, self.pasting = "", True
                    self.text, self.end = [], ""
                    self.window.keypad(False)
                elif candidate in _ESCAPE_KEYS:
                    self.escape = ""
                    return _ESCAPE_KEYS[candidate], None
                elif any(seq.startswith(candidate) for seq in (*_ESCAPE_KEYS, _PASTE_START)):
                    self.escape = candidate
                else:
                    self.escape = ""
                    self.queue.extend((key_name(ch, curses), None) for ch in candidate[1:])
                    return "esc", None
            else:
                name = key_name(value, curses)
                if name == "esc":
                    self.escape, self.escape_time = "\x1b", time.monotonic()
                    deadline = self.escape_time + INPUT_BATCH_SECONDS
                    self.window.timeout(0)
                elif name == "mouse":
                    try:
                        return name, curses.getmouse()
                    except curses.error:
                        return None, None
                else:
                    return name, None
            if deadline is not None and time.monotonic() >= deadline:
                return None
        return None


def _sgr_mouse(match, curses):
    code, x, y = (int(match.group(index)) for index in (1, 2, 3))
    if code > 255 or x < 1 or y < 1:
        return None
    button = code & 3
    modifiers = sum(getattr(curses, flag, 0) for bit, flag in
                    ((4, "BUTTON_SHIFT"), (8, "BUTTON_ALT"), (16, "BUTTON_CTRL")) if code & bit)
    if code & 64:
        state = getattr(curses, "BUTTON4_PRESSED" if button == 0 else "BUTTON5_PRESSED", 0) if button < 2 else 0
    elif match.group(4) == "m" or button == 3 and not code & 32:
        state = getattr(curses, f"BUTTON{button + 1 if button < 3 else 1}_RELEASED", 0)
    else:
        state = getattr(curses, f"BUTTON{button + 1}_PRESSED", 0) if button < 3 else 0
        if code & 32:
            state |= getattr(curses, "REPORT_MOUSE_POSITION", 0)
    return 0, x - 1, y - 1, 0, state | modifiers


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


def key_name(ch, curses) -> Optional[str]:
    """A wide character or curses key code -> the controller's key name."""
    if isinstance(ch, str):
        if len(ch) != 1:
            return None
        if ord(ch) > 127:
            return ch if ch.isprintable() else None
        ch = ord(ch)
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
    if ch in (1, 2, 5, 7, 11, 16, 21, 23, 25, 26):
        return {1: "ctrl-a", 2: "ctrl-b", 5: "ctrl-e", 7: "ctrl-g", 11: "ctrl-k",
                16: "ctrl-p", 21: "ctrl-u", 23: "ctrl-w", 25: "ctrl-y", 26: "ctrl-z"}[ch]
    if 1 <= ch <= 26:
        return "ctrl-" + chr(ord("a") + ch - 1)
    if getattr(curses, "KEY_F0", 100000) < ch <= getattr(curses, "KEY_F0", 100000) + 24:
        return f"f{ch - curses.KEY_F0}"
    if hasattr(curses, "KEY_DC") and ch == curses.KEY_DC:
        return "delete"
    if 33 <= ch < 127:
        return chr(ch)
    if ch > 127:
        try:
            name = {b"kLFT3": "alt-left", b"kRIT3": "alt-right", b"kLFT5": "ctrl-left", b"kRIT5": "ctrl-right"}.get(curses.keyname(ch))
            if name is None:
                encoded = curses.keyname(ch).decode("ascii", "replace")
                for prefix, key in (("kUP", "up"), ("kDN", "down"), ("kHOM", "home"), ("kEND", "end"),
                                    ("kPRV", "pgup"), ("kNXT", "pgdn"), ("kDC", "delete")):
                    if encoded in (prefix + "3", prefix + "5"):
                        name = ("alt-" if encoded.endswith("3") else "ctrl-") + key
                        break
            if name:
                return name
        except (curses.error, ValueError):
            pass
    return None


def _read_input(stdscr, curses):
    reader = _INPUT_READERS.get(id(stdscr))
    if reader is None or reader.window is not stdscr:
        if len(_INPUT_READERS) >= 128:
            _INPUT_READERS.pop(next(iter(_INPUT_READERS)))
        reader = _INPUT_READERS[id(stdscr)] = _InputReader(stdscr)
    return reader.read(curses)


def _navigation_context(app):
    """A changed document needs a new frame before another navigation event."""
    logs = getattr(app, "logs", None)
    analysis = getattr(app, "analysis_state", {})
    table = getattr(app, "table_tools_state", {})
    page = getattr(app, "log_tools_state", {}).get("page") or {}
    toolbar = getattr(app, "toolbar_state", {}) or {}
    panels = getattr(app, "job_panel_state", {}) or {}
    return (app.mode, app.tab, analysis.get("modal"), analysis.get("chart_job"), analysis.get("metric"),
            table.get("modal"), table.get("tab"), table.get("node"), table.get("action_job"),
            page.get("path"), page.get("start"), page.get("end"), page.get("snapshot", {}).get("ident"),
            getattr(app, "research_job_id", None),
            getattr(app, "research_view", None), getattr(app, "analytics_job", None),
            getattr(app, "log_job", None), getattr(logs, "path", None),
            getattr(logs, "browser", None),
            toolbar.get("menu"), toolbar.get("focus"), toolbar.get("cursor"), toolbar.get("panel"),
            panels.get("mode"), panels.get("focus"))


def _batchable_input(app, event, curses):
    name, mouse = event
    # Passive movement has no document action, including over a modal. Keeping
    # it outside the navigation whitelist avoids one modal render per report.
    if (name == "mouse" and mouse is not None and
            mouse[4] & getattr(curses, "REPORT_MOUSE_POSITION", 0) and
            not mouse[4] & (getattr(curses, "BUTTON1_RELEASED", 0) |
                            getattr(curses, "BUTTON4_PRESSED", 0) |
                            getattr(curses, "BUTTON5_PRESSED", 0))):
        return True
    mode = app.mode
    traversal = (mode in ("session_inbox", "log_tools_page", "log_tools_results", "log_tools_marks",
                          "jump_picker", "locations_picker", "value_peek", "field_explanation")
                 or mode == "analysis" and getattr(app, "analysis_state", {}).get("modal") in ("chart", "chart_events", "timeline", "diff", "inspect")
                 or mode == "table_tools" and getattr(app, "table_tools_state", {}).get("modal") in ("headers", "marks", "node", "actions"))
    if mode != "main" and not traversal:
        return False
    if name is None:
        return True  # An unsupported key or mouse motion has no controller action.
    if name != "mouse":
        if traversal:
            arrows = ("up", "down", "home", "end", "pgup", "pgdn")
            horizontal = mode == "log_tools_page" or mode == "analysis" and getattr(app, "analysis_state", {}).get("modal") == "chart"
            return name in arrows or horizontal and name in ("left", "right")
        return app.keymap.get(name) in _NAVIGATION_ACTIONS
    if mouse is None:
        return True
    buttons = mouse[4]
    click_mask = 0
    for button in ("BUTTON1_CLICKED", "BUTTON1_PRESSED", "BUTTON1_DOUBLE_CLICKED",
                   "BUTTON3_CLICKED", "BUTTON3_PRESSED"):
        click_mask |= getattr(curses, button, 0)
    # Captured motion is never a click. Initial presses and releases must use
    # the current frame; a release cannot disappear into a hover burst.
    if buttons & getattr(curses, "BUTTON1_RELEASED", 0):
        return False
    if buttons & getattr(curses, "REPORT_MOUSE_POSITION", 0):
        return True
    # Clicks use the hit map of the freshly painted frame. Wheels and passive
    # position reports can share a redraw without changing event order.
    if buttons & click_mask:
        return False
    if buttons & getattr(curses, "BUTTON4_PRESSED", 0):
        return traversal or app.keymap.get("up") in _NAVIGATION_ACTIONS
    if buttons & getattr(curses, "BUTTON5_PRESSED", 0):
        return traversal or app.keymap.get("down") in _NAVIGATION_ACTIONS
    return True


def _apply_input(app, event, hits, curses):
    name, mouse = event
    if name is None or name == "resize":
        return
    if name == "paste":
        from .scrolling import note_input
        note_input(app, "paste")
        from .startup import dismiss
        dismiss(app)
        if app.mode == "terminal_probe":
            app.handle(f"paste ({len(mouse)} characters)")
        else:
            from .command_ui import paste
            paste(app, mouse)
        return
    if name != "mouse":
        from .scrolling import note_input
        note_input(app, "key")
        app.handle(name)
        return
    if mouse is None:
        return
    if not getattr(app, "cfg", {}).get("mouse", True) and app.mode != "terminal_probe":
        return
    _, mx, my, _, bstate = mouse
    shift = bool(bstate & getattr(curses, "BUTTON_SHIFT", 0))
    from .toolbar import handle_mouse as toolbar_mouse
    button = ("wheel-up" if bstate & getattr(curses, "BUTTON4_PRESSED", 0) else
              "wheel-down" if bstate & getattr(curses, "BUTTON5_PRESSED", 0) else
              "release" if bstate & getattr(curses, "BUTTON1_RELEASED", 0) else
              "drag" if bstate & getattr(curses, "REPORT_MOUSE_POSITION", 0) and bstate & getattr(curses, "BUTTON1_PRESSED", 0) else
              "motion" if bstate & getattr(curses, "REPORT_MOUSE_POSITION", 0) else
              "right" if bstate & (getattr(curses, "BUTTON3_CLICKED", 0) | getattr(curses, "BUTTON3_PRESSED", 0)) else
              "left" if bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED) else
              "press" if bstate & curses.BUTTON1_PRESSED else "motion")
    from .scrolling import note_input, handle_wheel
    note_input(app, "wheel" if button.startswith("wheel-") else button)
    from .startup import handle_mouse as startup_mouse
    startup_mouse(app, my, mx, button=button, shift=shift)
    # Hover is independent of toolbar capture. Every final pointer position is
    # published, even when a global control consumes the gesture.
    if isinstance(getattr(app, "interaction_state", None), dict):
        from .interaction import handle_mouse as interaction_mouse
        interaction_mouse(app, my, mx, button="motion", shift=shift)
    if isinstance(getattr(app, "toolbar_state", None), dict) and toolbar_mouse(app, my, mx, button=button, shift=shift):
        return
    if button in ("wheel-up", "wheel-down"):
        from .pane_drag import blur
        blur(app)
        # A wheel gesture belongs to content, even after clicking a button.
        # Keyboard focus must not turn its direction into button traversal.
        focus = getattr(app, "interaction_state", None)
        if isinstance(focus, dict):
            focus["active"], focus["focused"] = False, None
    if button in ("motion", "drag", "release"):
        from .job_selection import active as selection_active
        if (selection_active(app) or getattr(app, "pane_drag_state", {}).get("capture") or
                getattr(app, "history_browser_state", {}).get("drag")):
            app.click(my, mx, hits, button=button, shift=shift)
        elif app.mode == "terminal_probe":
            app.click(my, mx, hits, button=button, shift=shift)
        return
    if button in ("wheel-up", "wheel-down"):
        from .history_browser import handle_mouse as history_mouse
        from .recent_history import handle_mouse as recent_mouse
        if history_mouse(app, my, mx, button=button, shift=shift) or recent_mouse(app, my, mx, button=button, shift=shift):
            return
        if app.tab == "deps" and getattr(app, "history_browser_state", {}).get("views", {}).get("deps", {}).get("explicit"):
            app.move("up" if button == "wheel-up" else "down")
            return
        from .job_panels import contains as in_job_panel
        if in_job_panel(app, my, mx):
            app.click(my, mx, hits, button=button, shift=shift)
            return
    if app.mode == "terminal_probe":
        app.click(my, mx, hits, button=button, shift=shift)
        return
    if button.startswith("wheel-") and handle_wheel(app, my, mx, -1 if button == "wheel-up" else 1):
        return
    if bstate & (getattr(curses, "BUTTON3_CLICKED", 0) | getattr(curses, "BUTTON3_PRESSED", 0)):
        app.click(my, mx, hits, button="right")
    elif bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED | curses.BUTTON1_DOUBLE_CLICKED):
        origin = app.tab
        from .job_panels import contains as in_job_panel
        double_target = (not shift and app.mode == "main" and not in_job_panel(app, my, mx) and any(
            y == my and ((origin == "jobs" and kind in ("job", "recent"))
                         or (origin == "history" and kind == "fin")
                         or (origin == "log" and app.logs.browser and kind == "log_file"))
            for y, kind, _ in hits))
        # Actual applications distinguish a held press from a completed click.
        # Small compatibility controllers without drag state retain left-click.
        pressed = button == "press" and hasattr(app, "job_selection_state")
        app.click(my, mx, hits, button="press" if pressed else "left", shift=shift)
        if bstate & curses.BUTTON1_DOUBLE_CLICKED and double_target and app.tab == origin and app.mode == "main":
            app.handle("enter")
    elif bstate & getattr(curses, "BUTTON4_PRESSED", 0):
        for _ in range(3 if app.tab == "log" else 1):
            app.handle("up")
    elif bstate & getattr(curses, "BUTTON5_PRESSED", 0):
        for _ in range(3 if app.tab == "log" else 1):
            app.handle("down")


def _consume_input_batch(app, stdscr, curses, hits, first, *, effects=None):
    """Preserve every event while sharing a bounded redraw for queued scrolling.

    Return the first nonnavigation event for the next, freshly painted frame.
    Keeping this single captured event avoids pushing escape sequences or mouse
    reports back through curses, where their identity or order can change.
    """
    event = first
    context = _navigation_context(app)
    pointer = first[0] == "mouse"
    limit = POINTER_BATCH_LIMIT if pointer else INPUT_BATCH_LIMIT
    deadline = time.monotonic() + (POINTER_BATCH_SECONDS if pointer else INPUT_BATCH_SECONDS)
    count = 0
    motion = None

    def apply(value):
        if effects is not None:
            effects.record(app, value, curses)
        _apply_input(app, value, hits, curses)

    def is_motion(value):
        if value[0] != "mouse" or value[1] is None:
            return False
        buttons = value[1][4]
        release_wheel = (getattr(curses, "BUTTON1_RELEASED", 0) |
                         getattr(curses, "BUTTON4_PRESSED", 0) |
                         getattr(curses, "BUTTON5_PRESSED", 0))
        return bool(buttons & getattr(curses, "REPORT_MOUSE_POSITION", 0) and not buttons & release_wheel)

    while event is not None:
        batchable = _batchable_input(app, event, curses)
        if batchable and is_motion(event):
            # Keep the latest position only. Drag selection and slider position
            # are functions of the endpoint, not of the number of reports.
            motion = event
        else:
            if motion is not None:
                apply(motion)
                motion = None
                if app.quit or _navigation_context(app) != context:
                    return event
            apply(event)
        count += 1
        if (not batchable or app.quit or _navigation_context(app) != context or
                count >= limit or time.monotonic() >= deadline):
            if motion is not None:
                apply(motion)
            return None
        stdscr.timeout(0)
        event = _read_input(stdscr, curses)
        if event is not None and not _batchable_input(app, event, curses):
            if motion is not None:
                apply(motion)
            return event
    if motion is not None:
        apply(motion)
    return None


class _InputEffects:
    """Separate cosmetic position updates from document-changing gestures."""

    def __init__(self):
        self.document = False

    def record(self, app, event, curses):
        name, mouse = event
        if name is None:
            return
        state = mouse[4] if name == "mouse" and mouse is not None else 0
        deliberate = (getattr(curses, "BUTTON1_PRESSED", 0) |
                      getattr(curses, "BUTTON1_CLICKED", 0) |
                      getattr(curses, "BUTTON1_DOUBLE_CLICKED", 0) |
                      getattr(curses, "BUTTON1_RELEASED", 0) |
                      getattr(curses, "BUTTON3_PRESSED", 0) |
                      getattr(curses, "BUTTON3_CLICKED", 0) |
                      getattr(curses, "BUTTON4_PRESSED", 0) |
                      getattr(curses, "BUTTON5_PRESSED", 0))
        hover = name == "mouse" and bool(state & getattr(curses, "REPORT_MOUSE_POSITION", 0)) and not state & deliberate
        toolbar = getattr(app, "toolbar_state", {}) or {}
        selection = getattr(app, "job_selection_state", {}) or {}
        # Some terminal drivers omit the held-button bit on position reports.
        # A captured gesture must still rebuild its slider or selected rows.
        capture = (toolbar.get("dragging") or selection.get("capture") or
                   getattr(app, "pane_drag_state", {}).get("capture") or
                   getattr(app, "history_browser_state", {}).get("drag"))
        if not hover or capture or app.mode == "terminal_probe":
            self.document = True


class _DifferentialPainter:
    """Paint changed physical rows and retain every overlay's original order."""

    def __init__(self, window, paint):
        self.window, self.paint = window, paint
        self.previous = None
        self.geometry = None

    def invalidate(self):
        self.previous = None

    def draw(self, rows, overlays, width, height, *, bar=None):
        layers = [[(0, tuple(rows[y]) if y < len(rows) else ())] for y in range(max(0, height))]
        for y, x, row in overlays:
            if 0 <= y < height and x < width:
                layers[y].append((x, tuple(row)))
        if height > 0 and bar is not None:
            # The complete toolbar masks any modal placed on row zero.
            layers[0] = [(0, tuple(bar))]
        current = tuple(tuple(layer) for layer in layers)
        reset = self.previous is None or self.geometry != (width, height)
        if reset:
            self.window.erase()
        changed = []
        for y, layer in enumerate(current):
            if not reset and layer == self.previous[y]:
                continue
            changed.append(y)
            # Filling the base clears a previous menu/longer line without
            # erasing untouched rows or relying on terminal erase attributes.
            _, base = layer[0]
            self.paint(y, 0, L.fill_row(base, width, ""), width, height)
            for x, row in layer[1:]:
                self.paint(y, x, row, width, height)
        self.previous, self.geometry = current, (width, height)
        return tuple(changed)


def _toolbar_feedback_token(app):
    state = getattr(app, "toolbar_state", {}) or {}
    return tuple(state.get(key) for key in ("menu", "cursor", "top", "panel", "panel_scroll", "focus"))


class _FrameCache:
    """Retain a published document while cosmetic pointer feedback changes.

    Maintenance and animation deadlines are independent of pointer traffic.
    Every deliberate input still requests a complete, current document frame.
    """

    def __init__(self):
        self.dirty = True
        self.snapshot = None
        self.rows, self.hits = [], []
        self.welcome, self.content, self.toolbar = [], [], []
        self.bar = []
        self.geometry = None
        self.next_maintenance = self.next_animation = 0.0
        self.toolbar_token = None

    def due(self, app, width, height, now=None):
        now = time.monotonic() if now is None else now
        return (self.dirty or self.geometry != (width, height) or
                now >= self.next_maintenance or now >= self.next_animation)

    def rebuild(self, app, views, store, actions, width, height):
        from . import startup, toolbar
        from .scrolling import begin_frame, finish_frame, timeout_ms
        from .interaction import publish
        app.tick()
        snap = store.snapshot()
        app.width = width
        begin_frame(app)
        options = {"feedback": False} if getattr(views, "feedback_options", False) else {}
        rows, hits = views.compose(snap, app, width, height, actions, **options)
        finish_frame(app)
        welcome = startup.overlay(views, snap, app, width, height) or []
        overlays = views.overlay(snap, app, width, height, **options) or []
        self.rows = getattr(app, "frame_rows", rows)
        self.hits, self.welcome = hits, welcome
        if options:
            self.content = getattr(app, "content_overlay_rows", []) or []
            self.toolbar = getattr(app, "toolbar_overlay_rows", []) or []
        else:
            self.content, self.toolbar = overlays, []
        self.bar = toolbar.render_bar(views, app, width) if height > 0 else []
        app.last_hits = hits
        publish(app, self.rows, hits, width, height, overlays=welcome + overlays)
        self.snapshot, self.geometry = snap, (width, height)
        self.toolbar_token = _toolbar_feedback_token(app)
        now = time.monotonic()
        self.next_maintenance = now + MAINTENANCE_SECONDS
        idle = 100 if app.animations_enabled and app.completion.active else 200
        if startup.active(app):
            idle = min(idle, int(startup.FRAME_INTERVAL * 1000))
        interval = timeout_ms(app, idle)
        self.next_animation = now + interval / 1000 if interval < 200 else float("inf")
        self.dirty = False

    def feedback(self, app, views):
        from .interaction import publish, decorate, decorate_overlays
        from . import toolbar
        width, height = self.geometry
        token = _toolbar_feedback_token(app)
        if token != self.toolbar_token:
            # A menu cursor, switch, or pointer dismissal only changes this
            # overlay. The underlying chart/report remains the same document.
            self.toolbar = toolbar.overlay(views, self.snapshot, app, width, height) or []
            self.bar = toolbar.render_bar(views, app, width) if height > 0 else []
            publish(app, self.rows, self.hits, width, height,
                    overlays=self.welcome + self.content + self.toolbar)
            self.toolbar_token = _toolbar_feedback_token(app)
        rows = decorate(app, self.rows)
        overlays = self.welcome + decorate_overlays(app, self.content + self.toolbar)
        bar = decorate(app, [self.bar])[0] if height > 0 else None
        return rows, overlays, bar

    def wait_ms(self, now=None):
        now = time.monotonic() if now is None else now
        return max(1, min(200, round(1000 * (min(self.next_maintenance, self.next_animation) - now))))


def _mouse_reporting(enabled):
    """Request SGR passive movement and drag reports; always restore terminal.

    Older terminals that do not support any-event mode retain button-event
    mode. Both are disabled explicitly on exit, including exceptional exits.
    """
    if not sys.stdout.isatty():
        return
    sys.stdout.write("\033[?1002h\033[?1003h\033[?1006h" if enabled else
                     "\033[?1003l\033[?1002l\033[?1000l\033[?1006l")
    sys.stdout.flush()


def run_curses(app, views, sampler, store, actions, cfg):
    import curses
    import locale
    locale.setlocale(locale.LC_ALL, "")

    def main(stdscr):
        try:
            curses.raw()  # Word-edit undo/redo must receive Ctrl-Z/Ctrl-S intact.
        except curses.error:
            pass
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.timeout(200)
        stdscr.keypad(True)
        if hasattr(curses, "set_escdelay") and "ESCDELAY" not in os.environ:
            curses.set_escdelay(25)
        mouse_enabled = cfg.get("mouse", True) or app.mode == "terminal_probe"
        try:
            curses.mousemask((curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION) if mouse_enabled else 0)
            curses.mouseinterval(0)
        except curses.error:
            pass
        _mouse_reporting(mouse_enabled)
        palette = CursesPalette(curses, cfg["color"])
        settings_generation = getattr(app, "terminal_settings_generation", 0)
        painted_theme = app.theme

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
        pending_input = None
        cache = _FrameCache()
        painter = _DifferentialPainter(stdscr, paint)
        app.views_ref = views
        from . import startup
        startup.begin(app)
        while not app.quit:
            if painted_theme != app.theme:
                painted_theme = app.theme
                cache.dirty = True
                painter.invalidate()
            current_settings = getattr(app, "terminal_settings_generation", 0)
            if settings_generation != current_settings:
                palette = CursesPalette(curses, cfg["color"])
                settings_generation = current_settings
                cache.dirty = True
                painter.invalidate()
            current_mouse = cfg.get("mouse", True) or app.mode == "terminal_probe"
            if current_mouse != mouse_enabled:
                try:
                    curses.mousemask((curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION) if current_mouse else 0)
                except curses.error:
                    pass
                mouse_enabled = current_mouse
                _mouse_reporting(mouse_enabled)
            height, width = stdscr.getmaxyx()
            if cache.due(app, width, height):
                cache.rebuild(app, views, store, actions, width, height)
            rows, overlays, bar = cache.feedback(app, views)
            hits, snap = cache.hits, cache.snapshot
            stdscr.timeout(cache.wait_ms())
            reader = _INPUT_READERS.get(id(stdscr))
            if reader and (reader.escape or reader.pasting):
                stdscr.timeout(5)
            painter.draw(rows, overlays, width, height, bar=bar)
            started = sum(1 for e in snap["events"] if e.get("kind") == "started" and not e.get("old"))
            if app.bell and started > rung:
                curses.beep()
            rung = started
            stdscr.noutrefresh()
            curses.doupdate()
            event = pending_input if pending_input is not None else _read_input(stdscr, curses)
            pending_input = None
            if event is None:
                continue
            effects = _InputEffects()
            before = (app.mode, app.tab, getattr(app, "selected_id", None))
            pending_input = _consume_input_batch(app, stdscr, curses, hits, event, effects=effects)
            cache.dirty = (effects.document or pending_input is not None
                           or before != (app.mode, app.tab, getattr(app, "selected_id", None))
                           or not getattr(views, "feedback_options", False))
            if getattr(app, "want_less", False):
                app.want_less = False
                files = views.files
                path = views.pager_path(store.snapshot(), app)
                if path and files.exists(path):
                    curses.endwin()
                    _mouse_reporting(False)
                    try:
                        subprocess.call(files.less_argv(path))
                    finally:
                        _mouse_reporting(mouse_enabled)
                        stdscr.touchwin()
                        stdscr.refresh()
                        painter.invalidate()
                        cache.dirty = True
                else:
                    app.say("no stdout file yet for this job")

    bracketed = sys.stdout.isatty()
    if bracketed:
        sys.stdout.write("\033[?2004h")
        sys.stdout.flush()
    try:
        curses.wrapper(main)
    finally:
        _INPUT_READERS.clear()
        _mouse_reporting(False)
        if bracketed:
            sys.stdout.write("\033[?2004l")
            sys.stdout.flush()


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
