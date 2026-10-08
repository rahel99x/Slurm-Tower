"""Always-visible terminal menus and a bounded, connection-safe update slider.

Menus retain the underlying modal and execute nothing while browsing. Every
item delegates to an existing command, opens an editable command prompt, or
performs a local presentation action. Hit rectangles come from the last paint.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import layout as L

MENUS = ("File", "Edit", "View", "Help")
BAR_STYLE = "text+bg:surface-raised"


@dataclass(frozen=True)
class Item:
    key: str
    label: str
    command: str = ""
    prompt: bool = False
    local: str = ""
    context: str = ""
    description: str = ""


def initialize(app):
    state = getattr(app, "toolbar_state", None)
    if not isinstance(state, dict):
        state = dict(menu=None, cursor=0, top=0, page=1, focus="", dragging=False,
                     panel=None, panel_scroll=0, hits=[], menu_hits=[], width=0,
                     bar_y=0, painted_menu=None, menu_token=None)
        app.toolbar_state = state
    return state


def command_names():
    return ["menu", "about"]


def run_command(app, args):
    if not args or args[0] not in command_names():
        return False
    if args[0] == "about" and len(args) == 1:
        _close(app)
        initialize(app).update(panel="about", panel_scroll=0)
    elif args[0] == "menu" and (len(args) == 1 or len(args) == 2 and args[1].title() in MENUS):
        _open(app, MENUS.index(args[1].title()) if len(args) == 2 else 0)
    else:
        app.fail("Use menu [File|Edit|View|Help] or about without arguments.")
    return True


def menu_items(app, menu):
    """Stable item identities; context changes are checked again on activation."""
    if isinstance(menu, int):
        menu = MENUS[menu % len(MENUS)]
    if menu == "File":
        return [
            Item("project", "Open project...", "project ", True, description="Discover a standard project and its run inventory."),
            Item("runs", "Project runs and attempts", "runs", context="project"),
            Item("outputs", "Run output artifacts", "outputs", context="binding"),
            Item("metrics", "Attach metrics stream...", "metrics ", True),
            Item("artifacts", "Attach output contract...", "artifacts ", True),
            Item("prepare", "Review batch script...", "preflight ", True),
            Item("passport", "Capture run passport...", "passport capture ", True),
            Item("export-text", "Export current page as text", "export text"),
            Item("export-csv", "Export current table as CSV", "export csv"),
            Item("export-json", "Export selected jobs as JSON", "export json"),
            Item("report", "Export complete terminal report", "export report"),
            Item("exports", "Export library", "exports"),
            Item("receipts", "Execution receipts...", "execution ", True),
            Item("profile", "Switch connection profile...", "profile ", True),
            Item("quit", "Quit Tower", local="quit"),
        ]
    if menu == "Edit":
        return [
            Item("copy", "Copy current selection", "copy"),
            Item("copy-all", "Copy entire log / current page", "copy all"),
            Item("select", "Start line selection", local="select"),
            Item("select-all", "Select entire log / current page", local="select-all"),
            Item("clear-selection", "Clear line selection", local="clear-selection"),
            Item("filter", "Filter this page...", "filter ", True),
            Item("clear-filter", "Clear this page's filter", "filter"),
            Item("filters", "Structured table filters", "filters", context="table"),
            Item("columns", "Choose table columns", "columns", context="table"),
            Item("sorts", "Cascading sort editor", "sorteditor", context="table"),
            Item("bookmark", "Bookmark current log line", "bookmark", context="log"),
            Item("pin", "Pin / unpin selected jobs", "pin", context="job"),
            Item("tag", "Tag selected jobs...", "tag ", True, context="job"),
            Item("note", "Annotate selected job...", "note ", True, context="job"),
            Item("save-location", "Save current location...", "location save ", True),
            Item("locations", "Saved locations", "location list"),
            Item("settings", "Terminal and sampler settings", "settings"),
            Item("keys", "Edit and test keybindings", "keybindings"),
        ]
    if menu == "View":
        from .views import TABS
        from .research import RESEARCH_VIEWS
        entries = [Item("tab-" + key, label + " page", "tab " + key) for key, label in TABS]
        entries += [Item("research-" + key, "Research: " + label, "workspace " + key)
                    for key, label in RESEARCH_VIEWS]
        entries += [
            Item("workspaces", "Search Research workspaces", "workspaces"),
            Item("jump", "Jump to job, run, file, or view", "jump"),
            Item("back", "Back to previous location", "back"),
            Item("forward", "Forward to next location", "forward"),
            Item("comfortable", "Comfortable panel density", "density comfortable"),
            Item("compact", "Compact panel density", "density compact"),
            Item("focused", "Focused panel density", "density focused"),
            Item("focus-main", "Focus job / main panel", "focus main"),
            Item("focus-details", "Focus Details panel", "focus details"),
            Item("maximize", "Maximize / restore focused panel", "maximize"),
            Item("layouts", "Saved workspace layouts", "layout list"),
            Item("freeze", "Resume inspection" if getattr(app, "table_tools_state", {}).get("freeze") else "Pause inspection (sampling continues)", "freeze"),
            Item("follow", "Pause / follow current log", local="follow", context="log"),
            Item("wrap", "Wrap / unwrap current log", "wrap", context="log"),
            Item("refresh", "Refresh all sources now", "refresh"),
            Item("rate", "Focus update-rate slider", local="rate"),
            Item("rate-reset", "Reset update rate to 1x", "rate reset"),
            Item("reader", "Plain ASCII reader mode", "theme reader"),
        ]
        from .controller import THEMES
        entries += [Item("theme-" + name, "Theme: " + name, "theme " + name) for name in THEMES if name != "reader"]
        return entries
    return [
        Item("help", "Page controls and searchable help", "help"),
        Item("commands", "Search all commands", "commands"),
        Item("doctor", "Terminal diagnostics", "terminaldoctor"),
        Item("terminal-test", "Test keys, mouse, and glyphs", "terminaltest"),
        Item("sources", "Source health and freshness", "tab sources"),
        Item("activity", "Activity and background tasks", "activity"),
        Item("inbox", "Completed-job review inbox", "inbox all"),
        Item("alerts", "Alert and quiet-hour controls", "alerts"),
        Item("about", "About Tower and update controls", local="about"),
    ]


def _blocked(app, item):
    pending_execution = getattr(app, "execution_state", {}).get("pending_action")
    if (getattr(app, "mode", "main") == "confirm" or pending_execution) and item.local not in ("quit", "about", "rate"):
        return "Close the pending job review first."
    tab = getattr(app, "tab", "")
    if item.context == "log" and (tab != "log" or getattr(getattr(app, "logs", None), "browser", True)):
        return "Open a log file first."
    if item.context == "table" and tab not in ("jobs", "history"):
        return "Open Jobs or History first."
    if item.context == "job" and not (getattr(app, "selected_id", None) or getattr(app, "marks", set())):
        return "Select or mark a job first."
    if item.context in ("project", "binding"):
        state = getattr(app, "project_state", {})
        if not state.get("binding" if item.context == "binding" else "root"):
            return "Choose a project run first." if item.context == "binding" else "Open a project first."
    return ""


def _close(app):
    initialize(app).update(menu=None, focus="", dragging=False, menu_hits=[], panel=None, painted_menu=None, menu_token=None)


def _open(app, menu=0):
    initialize(app).update(menu=menu % len(MENUS), cursor=0, top=0, focus="menu", dragging=False,
                           panel=None, menu_hits=[], painted_menu=None, menu_token=None)


def _rate(app, value=None, delta=None):
    from . import refresh_rate
    before = refresh_rate.multiplier(app)
    after = refresh_rate.adjust(app, delta) if delta is not None else refresh_rate.set_multiplier(app, value)
    if before != after:
        app.say(refresh_rate.cadence_summary(app))
    return after


def _activate(app, item):
    reason = _blocked(app, item)
    if reason:
        app.say(reason)
        return
    _close(app)
    action = item.local
    if action == "quit":
        app.quit = True
    elif action == "about":
        initialize(app).update(panel="about", panel_scroll=0)
    elif action == "rate":
        initialize(app)["focus"] = "rate"
        app.say("Update slider: Left/Right changes 1x; Home 1x; End 50x; Esc returns.")
    elif action == "clear-selection":
        app.sel_anchor = None
        app.logs.clear_selection()
        app.log_selection_expected = False
        app.say("Line selection cleared.")
    elif action in ("select", "select-all", "follow"):
        app.mode = "main"
        app.handle_action({"select": "visual", "select-all": "visual_all", "follow": "follow"}[action])
    elif item.prompt:
        from .command_ui import open_palette
        open_palette(app, item.command)
    else:
        app.mode = "main"
        app.run_command(item.command)


def render_bar(views, app, width, y=0):
    """One topmost row; x bounds are exact even in a one-cell terminal."""
    from . import refresh_rate
    state = initialize(app)
    width = max(0, int(width))
    state.update(width=width, bar_y=y, hits=[])
    if width == 0:
        return []
    value = str(refresh_rate.multiplier(app)) + "x"
    row = []
    x = 0

    def append(text, style=BAR_STYLE, kind=None, key=None):
        nonlocal x
        visible = L.truncate(text, max(0, width - x))
        if visible:
            row.append((visible, style))
            end = x + L.vlen(visible)
            if kind:
                state["hits"].append((y, x, end, kind, key))
            x = end

    if width < 8:
        append("x", "danger+bold+bg:surface-raised", "quit")
        if width >= len(value) + 1:
            append(" " * (width - x - len(value)))
            append(value, "accent+bold+bg:surface-raised", "rate")
        else:
            append(" " * (width - x))
        return row
    forms = [(" x ", [" File ", " Edit ", " View ", " Help "]),
             ("x", [" F ", " E ", " V ", " H "]), ("x", [" M "])]
    minimum_slider = len(value) + 1 + (10 if width >= 30 else 0)
    quit_label, labels = next((form for form in forms if len(form[0]) + sum(map(len, form[1])) <= width - minimum_slider), forms[-1])
    append(quit_label, "danger+bold+bg:surface-raised", "quit")
    for index, label in enumerate(labels):
        selected = state["menu"] == index if len(labels) == 4 else state["menu"] is not None
        append(label, "accent+bold+bg:surface-sunken" if selected else BAR_STYLE, "menu", index)
    space = width - x
    if space < len(value) + 14:
        append(" " * max(0, space - len(value) - 1))
        append(" " + value, "accent+bold+bg:surface-sunken" if state["focus"] == "rate" else "accent+bold+bg:surface-raised", "rate")
        return row
    caption = " Updates " if space >= 27 else " "
    suffix = " [+] " + value + " "
    track_size = min(18, max(3, space - len(caption) - 4 - len(suffix)))
    used = len(caption) + 4 + track_size + len(suffix)
    append(" " * max(0, space - used))
    append(caption, "muted+bg:surface-raised", "rate")
    append("[-] ", "accent+bold+bg:surface-raised", "minus")
    position = round((refresh_rate.multiplier(app) - 1) * (track_size - 1) / 49)
    for index in range(track_size):
        glyph = ("|" if index == position else "=" if index < position else "-") if views.g.ascii else ("▌" if index == position else "█" if index < position else "░")
        style = "accent+bold+bg:surface-sunken" if index <= position else "track+bg:surface-sunken"
        append(glyph, style, "track", (index, track_size))
    append(" ")
    append("[+]", "accent+bold+bg:surface-raised", "plus")
    append(" " + value + " ", "accent+bold+bg:surface-sunken" if state["focus"] == "rate" else "accent+bold+bg:surface-raised", "rate")
    return row


def handle_key(app, key):
    state = initialize(app)
    if key == "f10":
        _close(app) if state["menu"] is not None else _open(app)
        return True
    if state["panel"]:
        if key in ("esc", "q", "enter"):
            _close(app)
        elif key in ("up", "down", "pgup", "pgdn", "home", "end"):
            state["panel_scroll"] = max(0, {"up": state["panel_scroll"] - 1, "down": state["panel_scroll"] + 1,
                "pgup": state["panel_scroll"] - state["page"], "pgdn": state["panel_scroll"] + state["page"], "home": 0, "end": 1000}[key])
        return True
    if state["focus"] == "rate":
        state["dragging"] = False
        if key in ("left", "down", "-", "right", "up", "+", "home", "end"):
            if key in ("home", "end"):
                _rate(app, 1 if key == "home" else 50)
            else:
                _rate(app, delta=-1 if key in ("left", "down", "-") else 1)
            return True
        if key in ("esc", "enter", "tab", "btab"):
            state["focus"] = ""
            return True
        # A key intended for the underlying dialog remains available.
        state["focus"] = ""
        return False
    if state["menu"] is None:
        return False
    if key in ("esc", "q"):
        _close(app)
    elif key in ("left", "right", "tab", "btab"):
        _open(app, state["menu"] + (-1 if key in ("left", "btab") else 1))
    elif key in ("up", "down", "pgup", "pgdn", "home", "end"):
        count = len(menu_items(app, state["menu"]))
        current = state["cursor"]
        state["cursor"] = max(0, min(count - 1, {"up": current - 1, "down": current + 1,
            "pgup": current - state["page"], "pgdn": current + state["page"], "home": 0, "end": count - 1}[key]))
        state["menu_hits"] = []
    elif key in ("enter", "space"):
        entries = menu_items(app, state["menu"])
        _activate(app, entries[max(0, min(len(entries) - 1, state["cursor"]))])
    elif len(key) == 1 and key.lower() in "fevh":
        _open(app, "fevh".index(key.lower()))
    return True


def _track_value(state, x):
    track = [hit for hit in state["hits"] if hit[3] == "track"]
    if not track:
        return None
    start, end = track[0][1], track[-1][2] - 1
    return 1 + round(49 * (max(start, min(end, x)) - start) / max(1, end - start))


def handle_mouse(app, y, x, button="left", shift=False):
    state = initialize(app)
    if button == "release":
        was_dragging = state["dragging"]
        state["dragging"] = False
        return was_dragging
    if button in ("motion", "drag"):
        if state["dragging"]:
            value = _track_value(state, x)
            if value is not None:
                _rate(app, value)
            return True
        return False
    hit = next((hit for hit in state["hits"] if hit[0] == y and hit[1] <= x < hit[2]), None)
    if hit:
        kind, key = hit[3:]
        if button in ("wheel-up", "wheel-down"):
            if kind in ("track", "rate", "minus", "plus"):
                _close(app)
                state["focus"] = "rate"
                _rate(app, delta=1 if button == "wheel-up" else -1)
                return True
            return False
        if button != "left":
            return True
        if kind == "quit":
            _close(app)
            app.quit = True
        elif kind == "menu":
            _close(app) if state["menu"] == key else _open(app, key)
        else:
            _close(app)
            state["focus"] = "rate"
            if kind in ("minus", "plus"):
                _rate(app, delta=-1 if kind == "minus" else 1)
            elif kind == "track":
                _rate(app, _track_value(state, x))
                state["dragging"] = True
            else:
                app.say("Update slider: Left/Right changes 1x; Home 1x; End 50x; Esc returns.")
        return True
    if state["menu"] is not None:
        if button in ("wheel-up", "wheel-down"):
            handle_key(app, "up" if button == "wheel-up" else "down")
            return True
        if button == "left":
            token = (getattr(app, "mode", "main"), getattr(app, "tab", ""), state["menu"])
            target = next((hit for hit in state["menu_hits"] if hit[0] == y and hit[1] <= x < hit[2]), None)
            if target and state["menu_token"] == token:
                item = next((item for item in menu_items(app, state["menu"]) if item.key == target[3]), None)
                if item is not None:
                    _activate(app, item)
                    return True
            _close(app)
        return True
    if state["panel"]:
        if button == "left":
            _close(app)
        elif button in ("wheel-up", "wheel-down"):
            handle_key(app, "up" if button == "wheel-up" else "down")
        return True
    if state["focus"] == "rate":
        state["focus"], state["dragging"] = "", False
    return False


def _about_lines(app):
    from . import __version__, refresh_rate
    return [
        [(" Slurm Tower " + __version__, "accent+bold")],
        [(" Terminal workspace for Slurm, project runs, and research evidence.", "text")],
        [(" Menus: F10; Left/Right changes menu; Up/Down chooses; Enter opens.", "text")],
        [(" Slider: click or drag the track; +/- or wheel changes one step.", "text")],
        [(" Slider focus: arrows adjust; Home sets 1x; End sets 50x; Esc returns.", "text")],
        [(" " + refresh_rate.cadence_summary(app), "warning")],
        [(" Faster polling retains source minimum intervals and error backoff.", "dim")],
        [(" 50x requests a shorter source interval; it does not speed up jobs.", "dim")],
        [(" Menu browsing never submits, cancels, or changes a scheduler job.", "dim")],
        [(" Parameterized actions open an editable command before execution.", "dim")],
        [(" Project run conventions: docs/PROJECT_STANDARD.md in the repository.", "dim")],
        [(" Esc closes this panel and returns to your previous screen.", "accent")],
    ]


def overlay(views, snap, app, width, height):
    """Absolute dropdown coordinates, always below row zero, with exact hits."""
    state = initialize(app)
    if state["menu"] is None and not state["panel"]:
        return None
    state["menu_hits"] = []
    width, capacity = max(0, int(width)), max(0, int(height) - 1)
    if width == 0 or capacity == 0:
        return []
    ascii_ = views.g.ascii
    about = bool(state["panel"])
    entries = [] if about else menu_items(app, state["menu"])
    lines = _about_lines(app) if about else None
    title = "About Tower" if about else MENUS[state["menu"]]
    desired = max(36, max((L.vlen(item.label) + 5 for item in entries), default=68))
    box_width = min(width, desired)
    menu_hits = [hit for hit in state["hits"] if hit[3] == "menu" and hit[4] == state["menu"]]
    left = min(max(0, width - box_width), menu_hits[0][1] if menu_hits else 0)
    bordered = box_width >= 4 and capacity >= 3
    overhead = 3 if bordered and capacity >= 5 else 2 if bordered else 0
    page = max(1, capacity - overhead)
    state["page"] = page
    count = len(lines) if about else len(entries)
    cursor = min(count - 1, max(0, state["panel_scroll"] if about else state["cursor"]))
    top = min(max(0, count - page), state["top"])
    if cursor < top:
        top = cursor
    elif cursor >= top + page:
        top = cursor - page + 1
    state["top"] = top
    if about:
        state["panel_scroll"] = cursor
    else:
        state["cursor"] = cursor
    frame = []
    top_left, top_right, bottom_left, bottom_right, horizontal, vertical = views.g.box
    if bordered:
        caption = L.cut(" " + title + " ", box_width - 2, ascii_)
        frame.append([(top_left + caption + horizontal * (box_width - 2 - L.vlen(caption)) + top_right, "accent+bold+bg:surface")])
    item_width = max(1, box_width - (2 if bordered else 0))
    for index in range(top, min(count, top + page)):
        if about:
            content = L.fill_row(lines[index], item_width, "bg:surface")
        else:
            item = entries[index]
            disabled = _blocked(app, item)
            marker = (">" if ascii_ else "▸") if index == cursor else " "
            style = "muted+bg:surface" if disabled else "accent+bold+bg:surface-raised" if index == cursor else "text+bg:surface"
            content = L.fill_row([(marker + " " + L.cut(item.label, max(0, item_width - 2), ascii_), style)], item_width, "")
            state["menu_hits"].append((1 + len(frame), left + int(bordered), left + int(bordered) + item_width, item.key))
        frame.append([(vertical, "border+bg:surface")] + content + [(vertical, "border+bg:surface")] if bordered else content)
    if bordered and overhead == 3:
        reason = "" if about else _blocked(app, entries[cursor])
        footer = " " + reason if reason else f" {top + 1}-{min(count, top + page)}/{count}  Enter opens; Esc back"
        frame.append([(vertical, "border")] + L.fill_row([(L.cut(footer, item_width, ascii_), "muted+bg:surface")], item_width, "") + [(vertical, "border")])
    if bordered:
        frame.append([(bottom_left + horizontal * (box_width - 2) + bottom_right, "border+bg:surface")])
    state["painted_menu"] = state["menu"]
    state["menu_token"] = (getattr(app, "mode", "main"), getattr(app, "tab", ""), state["menu"])
    return [(1 + index, left, L.clip_row(row, box_width)) for index, row in enumerate(frame[:capacity])]
