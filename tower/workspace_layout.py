"""Adaptive, independently scrollable workspace panels without terminal I/O.

The compact default delegates to the established tab renderer unchanged. A
custom workspace asks it for a bounded larger source canvas, partitions semantic
section headings, and fits that source into independent panels. All hit rows are
remapped from source rows; IDs never depend on visible line text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Callable, Optional

from . import layout as L

DENSITIES = ("comfortable", "compact", "focused")
PANELS = ("main", "details")
MAX_SOURCE_ROWS = 256
MAX_REFLOW_ROWS = 2048
MAX_LAYOUTS = 16
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,47}\Z")


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int


@dataclass
class LayoutState:
    density: str = "compact"
    focus: str = "main"
    maximized: bool = False
    ratio: int = 60
    named: dict = field(default_factory=dict)
    scroll: dict = field(default_factory=dict)
    sizes: dict = field(default_factory=dict)
    available: tuple = ("main",)
    selected: dict = field(default_factory=dict)
    overlay_top: int = 0
    overlay_count: int = 0
    overlay_page: int = 1
    interactive_panels: dict = field(default_factory=dict)


def initialize(app) -> LayoutState:
    state = getattr(app, "layout_state", None)
    if not isinstance(state, LayoutState):
        state = LayoutState()
        cfg = getattr(app, "cfg", {})
        settings = cfg.get("workspace", {}) if hasattr(cfg, "get") else {}
        if isinstance(settings, dict):
            if settings.get("density") in DENSITIES:
                state.density = settings["density"]
            if isinstance(settings.get("split"), int) and not isinstance(settings["split"], bool):
                state.ratio = max(20, min(80, settings["split"]))
        app.layout_state = state
    return state


def _settings(state: LayoutState) -> dict:
    return dict(density=state.density, focus=state.focus, maximized=state.maximized, split=state.ratio)


def _apply(state: LayoutState, data: dict) -> None:
    if data.get("density") in DENSITIES:
        state.density = data["density"]
    if data.get("focus") in PANELS:
        state.focus = data["focus"]
    if isinstance(data.get("maximized"), bool):
        state.maximized = data["maximized"]
    if isinstance(data.get("split"), int) and not isinstance(data["split"], bool):
        state.ratio = max(20, min(80, data["split"]))


def restore(app, data) -> None:
    state = initialize(app)
    if not isinstance(data, dict) or data.get("version", 1) != 1:
        return
    _apply(state, data)
    named = data.get("named", {})
    if isinstance(named, dict):
        for name, value in list(named.items())[:MAX_LAYOUTS]:
            if isinstance(name, str) and _NAME.fullmatch(name) and isinstance(value, dict):
                clean = LayoutState()
                _apply(clean, value)
                state.named[name] = _settings(clean)
    offsets = data.get("scroll", {})
    if isinstance(offsets, dict):
        state.scroll = {key: max(0, min(MAX_SOURCE_ROWS, value))
                        for key, value in list(offsets.items())[:100]
                        if isinstance(key, str) and len(key) <= 100
                        and isinstance(value, int) and not isinstance(value, bool)}


def save(app) -> dict:
    state = initialize(app)
    return dict(version=1, **_settings(state), named=dict(state.named), scroll=dict(state.scroll))


def command_names() -> list[str]:
    return ["density", "focus", "maximize", "layout", "panel-scroll"]


def _say(app, message: str, failure: bool = False) -> None:
    method = getattr(app, "fail" if failure else "say", None)
    if callable(method):
        method(message)


def _persist(app) -> None:
    method = getattr(app, "save", None)
    if callable(method):
        method()


def _key(app, panel: Optional[str] = None) -> str:
    state = initialize(app)
    return str(getattr(app, "tab", "jobs")) + ":" + (panel or state.focus)


def _scroll(app, action: str) -> None:
    state = initialize(app)
    key = _key(app)
    count, page = state.sizes.get(key, (0, 1))
    page = max(1, page)
    top = state.scroll.get(key, 0)
    if action == "home":
        top = 0
    elif action == "end":
        top = max(0, count - page)
    else:
        top += {"up": -1, "down": 1, "pgup": -page, "pgdn": page,
                "page-up": -page, "page-down": page}.get(action, 0)
    state.scroll[key] = max(0, min(max(0, count - page), top))


def handle_key(app, key: str) -> bool:
    if getattr(app, "mode", "main") == "layout":
        state = initialize(app)
        if key in ("esc", "q", "enter"):
            app.mode = "main"
        elif key in ("up", "down", "pgup", "pgdn", "home", "end"):
            page = max(1, state.overlay_page)
            limit = max(0, state.overlay_count - page)
            if key == "home":
                state.overlay_top = 0
            elif key == "end":
                state.overlay_top = limit
            else:
                state.overlay_top = max(0, min(limit, state.overlay_top + {"up": -1, "down": 1, "pgup": -page, "pgdn": page}[key]))
        return True
    if getattr(app, "mode", "main") != "main":
        return False
    state = initialize(app)
    if key in ("ctrl-w", "ctrl_w", "f6"):
        panels = state.available if len(state.available) > 1 else PANELS
        state.focus = panels[(panels.index(state.focus) + 1) % len(panels)] if state.focus in panels else panels[0]
        _say(app, f"Focus: {state.focus}; arrows scroll Details, z maximizes")
        return True
    if key == "z" and getattr(app, "tab", "") != "log":
        state.maximized = not state.maximized
        _persist(app)
        _say(app, f"{state.focus.title()} {'maximized' if state.maximized else 'restored'}")
        return True
    if key == "esc" and state.maximized:
        state.maximized = False
        _persist(app)
        return True
    if (getattr(app, "tab", "") not in ("log", "research") and state.focus == "details" and
            "details" in state.available and key in ("up", "down", "pgup", "pgdn", "home", "end")):
        _scroll(app, key)
        return True
    if state.focus == "main" and enabled(app) and getattr(app, "tab", "") not in ("log", "research") and _key(app) in state.sizes:
        if not state.interactive_panels.get(_key(app), False) and key in ("up", "down", "pgup", "pgdn", "home", "end"):
            _scroll(app, key)
            return True
    return False


def run_command(app, args: list[str]) -> bool:
    if not args or args[0] not in command_names():
        return False
    state = initialize(app)
    command, rest = args[0], args[1:]
    if command == "density":
        if len(rest) == 1 and rest[0] in DENSITIES:
            state.density = rest[0]
            _say(app, "Density: " + state.density)
        else:
            _say(app, "density <comfortable|compact|focused>", True)
            return True
    elif command == "focus":
        if len(rest) > 1 or (rest and rest[0] not in (*PANELS, "next")):
            _say(app, "focus [main|details|next]", True)
            return True
        target = rest[0] if rest else "next"
        if target == "next":
            panels = state.available if len(state.available) > 1 else PANELS
            target = panels[(panels.index(state.focus) + 1) % len(panels)] if state.focus in panels else panels[0]
        state.focus = target
        _say(app, "Focus: " + target)
    elif command == "maximize":
        if len(rest) > 1 or (rest and rest[0] not in ("on", "off")):
            _say(app, "maximize [on|off]", True)
            return True
        state.maximized = not state.maximized if not rest else rest[0] == "on"
        _say(app, f"{state.focus.title()} {'maximized' if state.maximized else 'restored'}")
    elif command == "panel-scroll":
        if len(rest) != 1 or rest[0] not in ("up", "down", "page-up", "page-down", "home", "end"):
            _say(app, "panel-scroll <up|down|page-up|page-down|home|end>", True)
            return True
        _scroll(app, rest[0])
    elif command == "layout":
        if rest == ["list"] or not rest:
            app.mode = "layout"
            state.overlay_top = 0
            return True
        if len(rest) != 2 or rest[0] not in ("save", "load", "delete", "split"):
            _say(app, "layout <save|load|delete> <name> | layout split <20..80> | layout list", True)
            return True
        action, name = rest
        if action == "split":
            try:
                value = int(name)
            except ValueError:
                value = 0
            if not 20 <= value <= 80:
                _say(app, "layout split <20..80> (percentage for Main)", True)
                return True
            state.ratio = value
            if state.density == "compact":
                state.density = "comfortable"
        elif not _NAME.fullmatch(name):
            _say(app, "Layout names use 1-48 letters, numbers, dots, dashes, or underscores", True)
            return True
        elif action == "save":
            if name not in state.named and len(state.named) >= MAX_LAYOUTS:
                _say(app, f"At most {MAX_LAYOUTS} saved layouts; delete one first", True)
                return True
            state.named[name] = _settings(state)
        elif name not in state.named:
            _say(app, "No saved layout named " + name, True)
            return True
        elif action == "load":
            _apply(state, state.named[name])
        else:
            del state.named[name]
        _say(app, f"Layout {action}: {name}")
    _persist(app)
    return True


def enabled(app) -> bool:
    state = initialize(app)
    return state.density != "compact" or state.focus != "main" or state.maximized


def geometry(app, width: int, height: int, *, has_details: bool = True) -> dict[str, Rect]:
    """Fit independent panels, always respecting even a one-cell terminal."""
    state = initialize(app)
    width, height = max(0, int(width)), max(0, int(height))
    if not width or not height:
        return {}
    if not has_details:
        return {"main": Rect(0, 0, width, height)}
    if state.maximized or state.density == "focused" or height < 8 or width < 48:
        return {state.focus: Rect(0, 0, width, height)}
    if width >= 110:
        main_width = max(24, min(width - 25, (width - 1) * state.ratio // 100))
        return {"main": Rect(0, 0, main_width, height),
                "details": Rect(main_width + 1, 0, width - main_width - 1, height)}
    main_height = max(3, min(height - 3, (height - 1) * state.ratio // 100))
    return {"main": Rect(0, 0, width, main_height),
            "details": Rect(0, main_height + 1, width, height - main_height - 1)}


def _section_title(row: L.Row) -> Optional[str]:
    text = L.row_text(row).lstrip()
    if not text.startswith(("──", "--")):
        return None
    title = text.lstrip("─- ").rstrip("─- ").strip()
    return title.lower() if title else None


def partition(body, hits, tab: str = "jobs") -> dict:
    """Separate supporting sections while retaining their source hit records."""
    groups = {name: {"rows": [], "hits": []} for name in PANELS}
    panel = "main"
    source_map = {}
    for y, row in enumerate(body[:MAX_SOURCE_ROWS]):
        title = _section_title(row)
        if title:
            if title.startswith(("selected", "details", "resources", "evidence", "advice", "events", "recent events")):
                panel = "details"
            elif title.startswith(("jobs", "recent", "history", "nodes", "dependencies", "sources")):
                panel = "main"
            elif panel == "main" and y > 2 and not groups["details"]["rows"] and tab not in ("log", "research"):
                panel = "details"
        source_map[y] = (panel, len(groups[panel]["rows"]))
        groups[panel]["rows"].append(list(row))
    for y, kind, key in hits:
        if y in source_map:
            panel, index = source_map[y]
            groups[panel]["hits"].append((index, kind, key))
    return groups


def _style_row(row, width: int) -> L.Row:
    # Existing reverse-video rows become the same deliberate selected-row style
    # in each workspace. Cell colours remain meaningful on all other rows.
    out = [(text, style.replace("rev", "sel") if "rev" in style.split("+") else style)
           for text, style in row]
    selected = any("sel" in style.split("+") for _, style in out)
    return L.fill_row(out, width, "text+bg:surface" + ("+sel" if selected else ""))


def _join_characters(characters) -> L.Row:
    segments = []
    text, style = [], None
    for character, character_style in characters:
        if style is not None and character_style != style:
            segments.append(("".join(text), style))
            text = []
        text.append(character)
        style = character_style
    if text:
        segments.append(("".join(text), style or ""))
    return segments


def _wrap_row(row: L.Row, width: int) -> list[L.Row]:
    """Wrap metadata at spaces while preserving its exact semantic cell styles."""
    if width <= 0:
        return [[]]
    if L.vlen(L.row_text(row)) <= width:
        return [list(row)]
    lines, current, used, last_space = [], [], 0, -1
    for text, style in row:
        for character in text[:131072]:
            cell_width = 1 if ord(character) < 0x1100 else L.vlen(character)
            if cell_width > width:
                character, cell_width = "?", 1
            if character == "\n":
                lines.append(_join_characters(current))
                current, used, last_space = [], 0, -1
                continue
            if used + cell_width > width:
                if last_space >= 0:
                    lines.append(_join_characters(current[:last_space]))
                    current = current[last_space + 1:]
                else:
                    lines.append(_join_characters(current))
                    current = []
                used = sum(L.vlen(char) for char, _ in current)
                last_space = max((n for n, (char, _) in enumerate(current) if char.isspace()), default=-1)
            current.append((character, style))
            used += cell_width
            if character.isspace():
                last_space = len(current) - 1
            if len(lines) >= MAX_REFLOW_ROWS:
                return lines
    if current or not lines:
        lines.append(_join_characters(current))
    return lines


def _reflow(rows, hits, width: int):
    interactive = {y for y, _, _ in hits}
    mapped, result = {}, []
    for y, row in enumerate(rows):
        mapped[y] = len(result)
        if y in interactive or _section_title(row) is not None or any("┌" in text or "└" in text or "│" in text for text, _ in row):
            result.append(L.clip_row(row, width))
        else:
            result.extend(_wrap_row(row, width))
        if len(result) >= MAX_REFLOW_ROWS:
            result = result[:MAX_REFLOW_ROWS]
            break
    return result, [(mapped[y], kind, value) for y, kind, value in hits if y in mapped and mapped[y] < len(result)]


def _preserve_titles(fitted, original) -> None:
    originals = {}
    for row in original["rows"]:
        title = _section_title(row)
        if title:
            originals.setdefault(tuple(title.split()[:2]), (title, row))
    for index, row in enumerate(fitted["rows"]):
        title = _section_title(row)
        if not title:
            continue
        key = tuple(title.split()[:2])
        complete = originals.get(key)
        if complete and title != complete[0] and ("…" in title or "~" in title):
            # A narrow separator must not erase meaningful totals or states.
            fitted["rows"][index] = [(" " + complete[0], "heading+bold")]


def _preserve_metadata(fitted, original) -> None:
    """Prefer a longer source paragraph when a narrow view clipped it early."""
    originals = {}
    interactive = {y for y, _, _ in original["hits"]}
    for index, row in enumerate(original["rows"]):
        text = L.row_text(row).strip()
        if index not in interactive and text and _section_title(row) is None:
            originals.setdefault(text.split()[0], []).append(row)
    occurrences = {}
    interactive = {y for y, _, _ in fitted["hits"]}
    for index, row in enumerate(fitted["rows"]):
        text = L.row_text(row).strip()
        if index in interactive or not text or _section_title(row) is not None:
            continue
        prefix = text.split()[0]
        occurrence = occurrences.get(prefix, 0)
        occurrences[prefix] = occurrence + 1
        source = originals.get(prefix, [])
        if ("…" in text or "~" in text) and occurrence < len(source) and L.vlen(L.row_text(source[occurrence])) > L.vlen(text):
            fitted["rows"][index] = list(source[occurrence])


def transform_body(app, body, hits, width: int, height: int, *, ascii_: bool = False, groups=None):
    state = initialize(app)
    width, height = max(0, width), max(0, height)
    groups = partition(body, hits, getattr(app, "tab", "jobs")) if groups is None else groups
    has_details = bool(groups["details"]["rows"])
    state.available = PANELS if has_details else ("main",)
    if state.focus not in state.available:
        state.focus = "main"
    rects = geometry(app, width, height, has_details=has_details)
    canvas = [[(" " * width, "text+bg:canvas")] for _ in range(height)]
    # Keep columns as style segments, rather than individual character cells.
    rendered, output_hits = {}, []
    g = L.Glyphs(ascii_)
    for panel, rect in rects.items():
        source, source_hits = groups[panel]["rows"], groups[panel]["hits"]
        key = _key(app, panel)
        padding = 1 if state.density == "comfortable" and rect.width >= 8 and rect.height >= 5 else 0
        source, source_hits = _reflow(source, source_hits, max(0, rect.width - padding * 2))
        # Column headers are buttons, not selectable data rows. Header-only
        # tables must keep their normal panel-scrolling controls.
        drill_buttons = {"sort_header", "node_row", "node_cell", "partition_row", "user_drill"}
        data_hits = [(y, kind, value) for y, kind, value in source_hits if kind not in drill_buttons]
        state.interactive_panels[key] = bool(data_hits)
        page = max(0, rect.height - 1 - padding * 2)
        sticky = []
        sticky_hits = []
        if panel == "main" and source_hits and page >= 2:
            headers = [y for y, kind, _ in source_hits if kind == "sort_header"]
            first = min(y for y, _, _ in data_hits) if data_hits else min(headers) + 1 if headers else 0
            # Keep the page's primary summary and table column names visible
            # while large resource charts and individual rows scroll beneath.
            indices = sorted({index for index in (0, first - 2, first - 1) if 0 <= index < first})
            indices = indices[:max(0, min(3, page - 1))]
            sticky = [source[index] for index in indices]
            sticky_map = {index: position for position, index in enumerate(indices)}
            sticky_hits = [(sticky_map[y], kind, value) for y, kind, value in source_hits
                           if kind == "sort_header" and y in sticky_map]
            removed = set(indices)
            remap, remaining = {}, []
            for index, row in enumerate(source):
                if index not in removed:
                    remap[index] = len(remaining)
                    remaining.append(row)
            source = remaining
            source_hits = [(remap[y], kind, value) for y, kind, value in source_hits if y in remap]
            page -= len(sticky)
        state.sizes[key] = (len(source), page)
        top = state.scroll.get(key, 0)
        # A changing selected row stays visible; explicit panel scrolling remains
        # respected while the actual job identity has not changed.
        selected = getattr(app, "selected_id", None)
        if panel == "details" and selected != state.selected.get(key):
            top = 0
            state.selected[key] = selected
        active_hit = next(((y, kind, value) for y, kind, value in source_hits if kind not in drill_buttons and value == selected), None)
        if active_hit is None or getattr(app, "tab", "jobs") not in ("jobs", "history"):
            active_hit = next(((y, kind, value) for y, kind, value in source_hits
                               if kind not in drill_buttons and any("rev" in style.split("+") or "sel" in style.split("+") for _, style in source[y])), None)
        selected_key = active_hit[1:] if active_hit else selected
        if panel == "main" and selected_key and state.selected.get(key) != selected_key:
            row = active_hit[0] if active_hit else None
            if row is not None:
                if row < top:
                    top = row
                elif row >= top + max(1, page):
                    top = row - max(1, page) + 1
            state.selected[key] = selected_key
        visible, mapped_hits, top = L.scroll_window(source, source_hits, max(0, rect.width - padding * 2), page, top)
        state.scroll[key] = top
        title = panel.title() + ("  [z restore]" if state.maximized else "")
        rows = [L.panel_title(g, title, rect.width, state.focus == panel, (top, min(len(source), top + page), len(source)))]
        if padding:
            rows.append(L.fill_row([], rect.width))
        rows.extend(_style_row([(" " * padding, "")] + row, rect.width) for row in sticky)
        for row in visible:
            rows.append(_style_row([(" " * padding, "")] + row, rect.width))
        rows.extend(L.fill_row([], rect.width) for _ in range(max(0, rect.height - len(rows))))
        rendered[panel] = rows
        def add_hit(y, kind, value):
            if kind == "sort_header":
                tab, column, left, right = value
                usable_width = max(0, rect.width - padding * 2)
                right = min(right, usable_width)
                if left >= right:
                    return
                value = (tab, column, rect.x + padding + left, rect.x + padding + right)
            elif kind == "node_cell":
                name, left, right = value
                right = min(right, max(0, rect.width - padding * 2))
                if left >= right:
                    return
                value = (name, rect.x + padding + left, rect.x + padding + right)
            output_hits.append((y, kind, value))
        for y, kind, value in sticky_hits:
            add_hit(rect.y + 1 + padding + y, kind, value)
        for y, kind, value in mapped_hits:
            add_hit(rect.y + 1 + padding + len(sticky) + y, kind, value)
    for y in range(height):
        spans = []
        for panel, rect in rects.items():
            if rect.y <= y < rect.y + rect.height:
                spans.append((rect.x, rect.width, rendered[panel][y - rect.y]))
        row, x = [], 0
        for start, span_width, segments in sorted(spans):
            if start > x:
                row.append((" " * (start - x), "bg:canvas"))
            row.extend(segments)
            x = start + span_width
        if x < width:
            row.append((" " * (width - x), "bg:canvas"))
        canvas[y] = L.clip_row(row, width)
    # A scalar row-only hit cannot describe two selectable items in side-by-side
    # columns. Keep interactive table hits in Main; Details is scrollable text.
    return canvas, output_hits


def render_body(views, snap, app, width: int, height: Optional[int], actions,
                default_renderer: Callable[[int, Optional[int]], tuple]):
    """Render callback ``(width, height)`` with bounded independent panel scroll."""
    if width <= 0 or (height is not None and height <= 0):
        return [], []
    if getattr(app, "tab", "") == "research" and height is not None:
        # Research already virtualizes metric cards and long analysis views.
        # A larger source canvas would rasterize charts outside the viewport.
        body, hits = default_renderer(width, height)
        return [_style_row(row, width) for row in body], hits
    if height is None or not enabled(app) or getattr(app, "tab", "") == "log":
        return default_renderer(width, height)
    # Native tab renderers already limit their work to their requested height.
    # A larger bounded source keeps lower sections reachable rather than clipped.
    source_height = max(height, MAX_SOURCE_ROWS)
    body, hits = default_renderer(width, source_height)
    groups = partition(body, hits, getattr(app, "tab", "jobs"))
    originals = {panel: {"rows": list(group["rows"]), "hits": list(group["hits"])} for panel, group in groups.items()}
    rects = geometry(app, width, height, has_details=bool(groups["details"]["rows"]))
    # Refit columns and plots to their actual panel widths instead of cutting
    # away the right half of a table that was composed for a whole terminal.
    by_width = {width: groups}
    for panel, rect in rects.items():
        padding = 1 if initialize(app).density == "comfortable" and rect.width >= 8 and rect.height >= 5 else 0
        usable_width = max(0, rect.width - padding * 2)
        if usable_width not in by_width:
            fitted_body, fitted_hits = default_renderer(usable_width, source_height)
            by_width[usable_width] = partition(fitted_body, fitted_hits, getattr(app, "tab", "jobs"))
        groups[panel] = by_width[usable_width][panel]
        _preserve_titles(groups[panel], originals[panel])
        _preserve_metadata(groups[panel], originals[panel])
    return transform_body(app, body, hits, width, height, ascii_=getattr(views.g, "ascii", False), groups=groups)


def overlay(views, snap, app, width: int, height: int):
    if getattr(app, "mode", "main") != "layout":
        return None
    state = initialize(app)
    lines = [[(f" Density: {state.density}   Focus: {state.focus}   Split: {state.ratio}% Main", "bold")],
             [(" :density comfortable|compact|focused", "secondary")],
             [(" :focus main|details   :maximize   :layout split 20..80", "secondary")],
             [(" Ctrl-W: change panel; arrows: scroll Details; z: maximize", "dim")],
             [(" Saved layouts", "heading+bold")]]
    lines.extend([(f" {name:<20} {value['density']} / {value['focus']} / {value['split']}%", "text")]
                 for name, value in sorted(state.named.items()))
    if not state.named:
        lines.append([(" Save your current workspace with :layout save <name>", "dim")])
    lines.append([(" Esc: close   :layout load <name>   :layout delete <name>", "muted")])
    state.overlay_count = len(lines)
    state.overlay_page = max(1, height - 5)
    state.overlay_top = max(0, min(state.overlay_top, max(0, len(lines) - state.overlay_page)))
    visible = lines[state.overlay_top:state.overlay_top + state.overlay_page]
    if len(lines) > state.overlay_page:
        visible.append([(f" {state.overlay_top + 1}-{min(len(lines), state.overlay_top + state.overlay_page)}/{len(lines)}  Up/Down/PgUp/PgDn scroll", "muted")])
    return L.box(views.g, visible, width, height, "Workspace layouts", min_width=52)
