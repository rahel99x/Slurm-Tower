"""A bounded, cell-accurate interaction graph for the painted terminal frame.

Renderers publish controls as data. Neither graph construction, hovering nor
directional traversal reads files, requests samples, or changes a selection.
Activation delegates to the existing controller, preserving its confirmations.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
from . import layout as L

MAX_CONTROLS = 4096
MAX_OVERLAY_ROWS = 4096
POINTER_STYLE = "bg:surface-raised+under+bold"
FOCUS_STYLE = "bg:track+under+bold"
ROW_KINDS = frozenset(("job", "recent", "fin", "source", "group", "dep", "log_file",
                       "log_group", "research_array", "research_evidence", "research_metric",
                       "partition_row", "node_row", "user_drill"))
BOUNDED_KINDS = frozenset(("node_cell", "job_panel_tab", "job_panel_file",
                           "job_panel_view", "job_panel_action"))


@dataclass(frozen=True)
class Rect:
    """Display-cell rectangle with exclusive bottom and right edges."""

    top: int
    left: int
    bottom: int
    right: int

    def contains(self, y: int, x: int) -> bool:
        return self.top <= y < self.bottom and self.left <= x < self.right

    def intersects(self, other: "Rect") -> bool:
        return (self.top < other.bottom and other.top < self.bottom
                and self.left < other.right and other.left < self.right)

    def clip(self, width: int, height: int):
        result = Rect(max(0, self.top), max(0, self.left), min(height, self.bottom), min(width, self.right))
        return result if result.top < result.bottom and result.left < result.right else None

    @property
    def center(self):
        return ((self.top + self.bottom - 1) / 2, (self.left + self.right - 1) / 2)


@dataclass(frozen=True)
class Control:
    """Immutable semantic control; action arguments contain only scalar data."""

    id: str
    label: str
    rect: Rect
    action: tuple
    group: str = "buttons"
    enabled: bool = True
    reason: str = ""
    button: bool = True
    layer: int = 0


@dataclass(frozen=True)
class Graph:
    controls: tuple[Control, ...]
    token: tuple
    width: int
    height: int
    generation: int
    observed_geometry: tuple = ()

    def get(self, identity):
        return next((control for control in self.controls if control.id == identity), None)

    def at(self, y, x):
        # Later / smaller controls win when a selectable row also contains a button.
        candidates = (control for control in self.controls if control.rect.contains(y, x))
        return max(candidates, key=lambda c: (c.layer, c.button,
                   -((c.rect.right - c.rect.left) * (c.rect.bottom - c.rect.top))), default=None)


def initialize(app):
    state = getattr(app, "interaction_state", None)
    if not isinstance(state, dict):
        state = {}
        app.interaction_state = state
    for key, value in (("graph", None), ("pointer", None), ("hovered", None), ("focused", None),
                       ("active", False), ("routing", False), ("generation", 0), ("pending_focus", None)):
        state.setdefault(key, value)
    return state


def command_names():
    return ["focusbuttons"]


def overlay(views, snap, app, width, height):
    return None


def _state(app, name):
    value = getattr(app, name, {})
    return value if isinstance(value, dict) else {}


def _context(app):
    """Reject actions after a page, overlay, or selected-job identity changes."""
    toolbar = _state(app, "toolbar_state")
    analysis = _state(app, "analysis_state")
    panel = _state(app, "job_panel_state")
    project = _state(app, "project_state")
    table_tools = _state(app, "table_tools_state")
    execution = _state(app, "execution_state")
    logs = getattr(app, "logs", None)
    return (getattr(app, "mode", "main"), getattr(app, "tab", ""),
            getattr(app, "selected_id", None), getattr(app, "nodes_view", None),
            getattr(app, "analytics_view", None), getattr(app, "research_view", None),
            analysis.get("modal"), analysis.get("job"), analysis.get("chart_job"), analysis.get("metric"), panel.get("mode"),
            panel.get("view"), panel.get("research_view"), panel.get("analytics_view"), project.get("root"),
            getattr(logs, "browser", None), getattr(logs, "path", None),
            toolbar.get("menu"), toolbar.get("panel"), table_tools.get("modal"),
            table_tools.get("tab"), _state(app, "table_state").get("tab") if getattr(app, "mode", "main") == "columns" else None,
            id(getattr(app, "confirm", None)) if getattr(app, "mode", "main") == "confirm" else None,
            id(execution.get("review")) if getattr(app, "mode", "main") == "execution" else None,
            repr(execution.get("pending_action"))[:512] if getattr(app, "mode", "main") == "execution" else None)


def _current(app):
    state = initialize(app)
    graph = state["graph"]
    if graph is None or graph.token != _context(app):
        return None
    # Screen size is optional for small embedders and headless renderers.
    for name, expected in zip(("width", "height"), graph.observed_geometry):
        actual = getattr(app, name, None)
        if actual != expected:
            return None
    return graph


def controls(app):
    graph = _current(app)
    return graph.controls if graph is not None else ()


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _rect(value):
    if isinstance(value, Rect):
        return value if all(_integer(item) for item in (value.top, value.left, value.bottom, value.right)) else None
    if isinstance(value, (tuple, list)) and len(value) == 4 and all(_integer(item) for item in value):
        return Rect(*value)
    return None


def _action(value):
    if not isinstance(value, (tuple, list)) or not value:
        return None
    if value[0] not in ("click", "command", "key", "set", "row"):
        return None
    if any(not isinstance(item, (str, int, float, bool, type(None))) for item in value):
        return None
    return tuple(value)


def _descriptor(value, *, layer=0):
    if isinstance(value, Control):
        value = {"id": value.id, "label": value.label, "rect": value.rect, "action": value.action,
                 "group": value.group, "enabled": value.enabled, "reason": value.reason,
                 "button": value.button}
    if not isinstance(value, dict):
        return None
    identity = value.get("id")
    rect = _rect(value.get("rect"))
    action = _action(value.get("action"))
    if not isinstance(identity, str) or not identity or len(identity) > 512 or not rect or not action:
        return None
    return Control(identity, str(value.get("label", identity))[:512], rect, action,
                   str(value.get("group", "buttons"))[:128],
                   bool(value.get("enabled", not value.get("disabled", False))),
                   str(value.get("reason", ""))[:512], bool(value.get("button", True)), layer)


def _overlay_spans(overlays, width, height):
    spans = {}
    for item in islice(overlays or (), MAX_OVERLAY_ROWS):
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            continue
        y, x, row = item
        if not _integer(y) or not _integer(x) or not 0 <= y < height:
            continue
        try:
            rect = Rect(y, x, y + 1, x + L.vlen(L.row_text(row))).clip(width, height)
        except (TypeError, ValueError):
            continue
        if rect:
            spans.setdefault(y, []).append((rect, row))
    return spans


def _row_rect(rows, y, width, height, *, overlays=None, main_right=None):
    if not _integer(y) or not 0 <= y < height:
        return None
    if overlays and y in overlays:
        rect, row = overlays[y][-1]
        # The overlay border and its margins do not activate list entries.
        return Rect(y, rect.left + 1, y + 1, rect.right - 1).clip(width, height)
    if not 0 <= y < len(rows):
        return None
    text = L.row_text(rows[y])
    right = min(width, L.vlen(text), width if main_right is None else main_right)
    left = min(right, L.vlen(text) - L.vlen(text.lstrip()))
    return Rect(y, left, y + 1, right).clip(width, height)


def _hit_controls(app, rows, hits, width, height, *, layer=0, spans=None):
    for hit in islice(hits or (), MAX_CONTROLS):
        if not isinstance(hit, (tuple, list)) or len(hit) != 3:
            continue
        y, kind, value = hit
        if not _integer(y) or not 0 <= y < height:
            continue
        if kind == "control" and isinstance(value, dict):
            descriptor = dict(value)
            descriptor["rect"] = (y, value.get("left"), y + 1, value.get("right"))
            control = _descriptor(descriptor, layer=layer)
            if control:
                yield control
        elif kind == "sort_header" and isinstance(value, (tuple, list)) and len(value) == 4:
            table, column, left, right = value
            rect = _rect((y, left, y + 1, right))
            if rect:
                yield Control(f"sort:{table}:{column}", str(column), rect,
                              ("click", y, left), f"sort:{table}", layer=layer)
        elif kind in BOUNDED_KINDS and isinstance(value, (tuple, list)) and len(value) == 3:
            target, left, right = value
            rect = _rect((y, left, y + 1, right))
            if rect:
                identity = str(target)
                if kind == "job_panel_action" and isinstance(target, (tuple, list)) and len(target) == 2:
                    action_kind, payload = target
                    identity = str(action_kind) + ":" + str(payload.get("id", "") if isinstance(payload, dict) else payload)
                yield Control(f"{kind}:{identity}", identity, rect, ("click", y, left),
                              kind, button=kind != "node_cell", layer=layer)
        elif kind in ROW_KINDS:
            right = None
            if getattr(app, "tab", "") == "jobs":
                panel = getattr(app, "job_panel_rect", None)
                if panel is not None and panel.y <= y < panel.y + panel.height and panel.x:
                    right = panel.x - 1
            rect = _row_rect(rows, y, width, height, overlays=spans, main_right=right)
            if rect:
                yield Control(f"{kind}:{value}", str(value), rect, ("row", y, rect.left),
                              kind, button=False, layer=layer)


def _toolbar_controls(app):
    state = _state(app, "toolbar_state")
    if not state:
        return
    tracks = []
    for hit in islice(state.get("hits", ()), MAX_CONTROLS):
        if not isinstance(hit, (tuple, list)) or len(hit) != 5:
            continue
        y, left, right, kind, key = hit
        rect = _rect((y, left, y + 1, right))
        if not rect:
            continue
        if kind == "track":
            tracks.append(rect)
        else:
            yield Control(f"toolbar:{kind}:{key}", str(key if kind == "menu" else kind), rect,
                          ("click", y, left), "toolbar", layer=3)
    if tracks:
        rect = Rect(tracks[0].top, min(r.left for r in tracks), tracks[-1].bottom,
                    max(r.right for r in tracks))
        yield Control("toolbar:track", "Update rate slider", rect,
                      ("click", rect.top, round(rect.center[1])), "toolbar", layer=3)
    if state.get("menu") is not None:
        disabled = state.get("menu_disabled", {})
        for hit in islice(state.get("menu_hits", ()), MAX_CONTROLS):
            if not isinstance(hit, (tuple, list)) or len(hit) != 4:
                continue
            y, left, right, key = hit
            rect = _rect((y, left, y + 1, right))
            if rect:
                reason = disabled.get(key, "")
                yield Control(f"toolbar:menu:{state['menu']}:{key}", str(key), rect,
                              ("click", y, left), "toolbar-menu", not bool(reason),
                              str(reason), layer=4)


def _modal_controls(app, rows, width, height, spans):
    mode = getattr(app, "mode", "main")
    state_names = {"analysis": "analysis_state", "project_runs": "project_state",
                   "project_outputs": "project_state", "project_preview": "project_state",
                   "log_compare": "log_workbench_state", "log_diff": "log_workbench_state",
                   "execution": "execution_state", "columns": "table_state"}
    # The log workbench uses additional mode names; only current modal data may
    # contribute controls, never a previous hidden panel's registries.
    state_name = state_names.get(mode)
    if state_name:
        yield from _hit_controls(app, rows, _state(app, state_name).get("control_hits", ()),
                                 width, height, layer=2, spans=spans)
    if mode == "main" and getattr(app, "tab", "") == "log":
        yield from _hit_controls(app, rows, _state(app, "log_workbench_state").get("control_hits", ()),
                                 width, height, layer=2, spans=spans)
    if mode == "table_tools":
        state = _state(app, "table_tools_state")
        for hit in islice(state.get("hits", ()), MAX_CONTROLS):
            if isinstance(hit, (tuple, list)) and len(hit) == 4:
                y, left, right, index = hit
                rect = _rect((y, left, y + 1, right))
                if rect:
                    yield Control(f"table-tools:{state.get('modal')}:{index}", str(index), rect,
                                  ("click", y, left), "table-tools", layer=2)
    if mode == "confirm":
        for hit in islice(_state(app, "command_state").get("confirm_hits", ()), MAX_CONTROLS):
            if isinstance(hit, (tuple, list)) and len(hit) == 4:
                y, left, right, choice = hit
                rect = _rect((y, left, y + 1, right))
                if rect:
                    yield Control(f"confirm:{choice}", str(choice), rect, ("click", y, left),
                                  "confirmation", layer=2)
    row_registries = []
    if mode == "palette":
        row_registries.append(("palette", _state(app, "command_state").get("result_hits", ())))
    navigation = _state(app, "navigation_tools_state")
    if mode in ("jump_picker", "locations_picker", "bindings_editor", "settings_editor"):
        row_registries.append(("navigation:" + mode, navigation.get("hits", ())))
    for prefix, registry in row_registries:
        for hit in islice(registry, MAX_CONTROLS):
            if isinstance(hit, (tuple, list)) and len(hit) == 2:
                y, index = hit
                rect = _row_rect(rows, y, width, height, overlays=spans)
                if rect:
                    yield Control(f"{prefix}:{index}", str(index), rect, ("row", y, rect.left),
                                  prefix, button=False, layer=2)
    if mode == "session_inbox":
        registry = _state(app, "session_tools_state").get("mouse_rows", {})
        prefix = "inbox"
    elif mode == "exports":
        registry = getattr(getattr(app, "activity", None), "mouse_rows", {})
        prefix = "export"
    elif mode in ("log_tools_results", "log_tools_marks"):
        registry = _state(app, "log_tools_state").get("mouse_rows", {})
        prefix = mode
    else:
        registry, prefix = {}, ""
    for y, value in islice(registry.items(), MAX_CONTROLS):
        if isinstance(value, (tuple, list)) and len(value) == 3:
            identity, left, right = value
            rect = _rect((y, left, y + 1, right))
            if rect:
                yield Control(f"{prefix}:{identity}", str(identity), rect,
                              ("row", y, left), prefix, button=False, layer=2)


def publish(app, rows, hits, width, height, overlays=None, extra_controls=()):
    """Publish one immutable graph from the final visible frame's metadata.

    ``rows`` contain normal display rows; ``overlays`` contain absolute
    ``(y, x, row)`` triples. Explicit controls may be ``Control`` instances or
    dictionaries with ``id, rect, action, group, label``. Existing three-item
    hits and modal registries are adapted without invoking any renderer.
    """
    state = initialize(app)
    width = max(0, width) if _integer(width) else 0
    height = max(0, height) if _integer(height) else len(rows)
    spans = _overlay_spans(overlays, width, height)
    toolbar_state = _state(app, "toolbar_state")
    menu_rect = _rect(toolbar_state.get("menu_rect")) if toolbar_state.get("menu") is not None else None
    candidates = []
    if getattr(app, "mode", "main") == "main":
        candidates.extend(_hit_controls(app, rows, hits, width, height))
        for hit in islice(getattr(app, "tab_hits", ()), MAX_CONTROLS):
            if isinstance(hit, (tuple, list)) and len(hit) == 4:
                y, left, right, key = hit
                rect = _rect((y, left, y + 1, right))
                if rect:
                    candidates.append(Control(f"tab:{key}", str(key), rect, ("click", y, left), "tabs"))
        chip_y = getattr(app, "table_chip_y", None)
        chips = getattr(app, "table_chip_cells", ("", ()))
        if _integer(chip_y) and isinstance(chips, (tuple, list)) and len(chips) == 2:
            for chip in islice(chips[1], MAX_CONTROLS):
                if isinstance(chip, (tuple, list)) and len(chip) == 3:
                    key, left, right = chip
                    rect = _rect((chip_y, left, chip_y + 1, right))
                    if rect:
                        candidates.append(Control(f"filter-chip:{chips[0]}:{key}", str(key), rect,
                                                  ("click", chip_y, left), "filter-chips"))
    candidates.extend(_modal_controls(app, rows, width, height, spans))
    candidates.extend(_toolbar_controls(app))
    for descriptor in islice(extra_controls or (), MAX_CONTROLS):
        control = _descriptor(descriptor, layer=2 if spans else 0)
        if control:
            candidates.append(control)
    visible, identities, primary_rects = [], set(), {}
    for control in candidates:
        if len(visible) >= MAX_CONTROLS:
            break
        rect = control.rect.clip(width, height)
        if not rect:
            continue
        if menu_rect is not None and control.layer < 4 and rect.intersects(menu_rect):
            continue
        identity = control.id
        if identity in identities:
            # Inline cited-file links intentionally repeat their native action
            # on each wrapped line. Keep each painted fragment selectable;
            # ordinary duplicate semantic metadata still contributes one node.
            if identity.startswith("job_panel_action:") and primary_rects.get(identity) != rect:
                identity += f":fragment:{rect.top}:{rect.left}:{rect.right}"
            if identity in identities:
                continue
        # A dropdown masks controls directly underneath its painted rectangle.
        # Generic modals omit all underlying controls even beyond their border.
        if control.layer == 0 and any(rect.intersects(span)
                                      for y in range(rect.top, rect.bottom)
                                      for span, _ in spans.get(y, ())):
            continue
        action = control.action
        if action[0] in ("click", "row") and len(action) == 3:
            action = (action[0], max(rect.top, min(rect.bottom - 1, action[1])),
                      max(rect.left, min(rect.right - 1, action[2])))
        visible.append(Control(identity, control.label, rect, action, control.group,
                               control.enabled, control.reason, control.button, control.layer))
        identities.add(identity)
        primary_rects.setdefault(control.id, rect)
    state["generation"] += 1
    graph = Graph(tuple(visible), _context(app), width, height, state["generation"],
                  (getattr(app, "width", None), getattr(app, "height", None)))
    state["graph"] = graph
    if graph.get(state["focused"]) is None:
        state["focused"], state["active"] = None, False
    pointer = state["pointer"]
    hovered = graph.at(*pointer) if pointer else None
    state["hovered"] = hovered.id if hovered else None
    if state.get("pending_focus"):
        state["pending_focus"] = None
        _focus(app)
    return graph


def nearest(graph: Graph, current: Control, direction: str):
    """Find a directional neighbor in O(n), without a quadratic edge matrix.

    Same-row/column controls win. Aligned controls in the same semantic group
    then win over diagonal shortcuts into a different pane. Stable screen
    order breaks ties, including controls packed into wrapped button rows.
    """
    if direction not in ("left", "right", "up", "down"):
        return None
    vertical = direction in ("up", "down")
    sign = -1 if direction in ("left", "up") else 1
    cy, cx = current.rect.center
    ranked = []
    for candidate in graph.controls:
        if candidate.id == current.id or not candidate.enabled:
            continue
        ny, nx = candidate.rect.center
        forward = (ny - cy if vertical else nx - cx) * sign
        if forward <= 0:
            continue
        orthogonal = abs(nx - cx if vertical else ny - cy)
        overlap = (current.rect.left < candidate.rect.right and candidate.rect.left < current.rect.right
                   if vertical else current.rect.top < candidate.rect.bottom and candidate.rect.top < current.rect.bottom)
        same_group = candidate.group == current.group
        rank = (0 if overlap else 1, 0 if same_group else 1,
                forward + 2 * orthogonal, orthogonal, forward,
                candidate.rect.top, candidate.rect.left, candidate.id)
        ranked.append((rank, candidate))
    return min(ranked, key=lambda value: value[0])[1] if ranked else None


def _focus(app, enabled=True):
    state = initialize(app)
    graph = _current(app)
    if not enabled:
        state["active"] = False
        state["pending_focus"] = None
        return True
    if graph is None:
        state["pending_focus"] = True
        return True
    target = graph.get(state["hovered"]) or graph.get(state["focused"])
    if target is None or not target.enabled:
        target = next((control for control in graph.controls if control.enabled and control.button),
                      next((control for control in graph.controls if control.enabled), None))
    if target is None:
        return False
    state["focused"], state["active"] = target.id, True
    return True


def run_command(app, args):
    if not args or args[0] != "focusbuttons":
        return False
    if len(args) > 2 or len(args) == 2 and args[1] not in ("on", "off"):
        if hasattr(app, "fail"):
            app.fail("focusbuttons [on|off]")
        return True
    enabled = args[1] != "off" if len(args) == 2 else not initialize(app)["active"]
    if not _focus(app, enabled) and hasattr(app, "say"):
        app.say("No visible controls yet; draw this page and press F8.")
    elif hasattr(app, "say"):
        app.say("Buttons: arrows move; Enter activates; Esc returns to content." if enabled else "Content keys restored.")
    return True


def _activate(app, control, *, keyboard=False):
    state = initialize(app)
    graph = _current(app)
    if graph is None or graph.get(control.id) != control or state["routing"]:
        return False
    if not control.enabled:
        if hasattr(app, "say") and control.reason:
            app.say(control.reason)
        return True
    action = control.action
    previous_active = state["active"]
    state["routing"], state["active"] = True, False
    try:
        if action[0] in ("click", "row") and len(action) == 3:
            app.click(action[1], action[2], getattr(app, "last_hits", ()))
            if keyboard and action[0] == "row" and getattr(app, "mode", "main") == graph.token[0]:
                app.handle("enter")
        elif action[0] == "command" and len(action) == 2 and isinstance(action[1], str):
            app.run_command(action[1])
        elif action[0] == "key" and len(action) == 2 and isinstance(action[1], str):
            app.handle(action[1])
        elif action[0] == "set" and len(action) == 3 and action[1] in ("nodes_view", "analytics_view", "research_view"):
            setattr(app, action[1], action[2])
        else:
            return False
    finally:
        state["routing"] = False
        state["active"] = previous_active and graph.token == _context(app)
        if previous_active and control.button and graph.token != _context(app) and getattr(app, "mode", "main") == graph.token[0]:
            state["pending_focus"] = True
    return True


def handle_key(app, key):
    state = initialize(app)
    if state["routing"]:
        return False
    if key == "f8":
        _focus(app, not state["active"])
        return True
    if not state["active"]:
        return False
    graph = _current(app)
    if graph is None:
        state["active"] = False
        return False
    if key == "esc":
        state["active"] = False
        return True
    current = graph.get(state["focused"])
    if current is None:
        state["active"] = False
        return False
    target = None
    if key in ("up", "down", "left", "right"):
        target = nearest(graph, current, key)
    elif key in ("home", "end", "tab", "btab"):
        ordered = sorted((control for control in graph.controls if control.enabled),
                         key=lambda control: (control.rect.top, control.rect.left, control.id))
        if ordered:
            index = next((i for i, control in enumerate(ordered) if control.id == current.id), 0)
            index = 0 if key == "home" else len(ordered) - 1 if key == "end" else (index + (1 if key == "tab" else -1)) % len(ordered)
            target = ordered[index]
    elif key in ("enter", "space"):
        return _activate(app, current, keyboard=True)
    else:
        # Typing a content shortcut exits graph mode and reaches its existing
        # handler. No hidden keymap or chart/log selection mode is replaced.
        state["active"] = False
        return False
    if target:
        state["focused"] = target.id
    return True


def handle_mouse(app, y, x, button="left", shift=False, **kwargs):
    state = initialize(app)
    if state["routing"]:
        return False
    if not _integer(y) or not _integer(x):
        return False
    state["pointer"] = (y, x)
    graph = _current(app)
    target = graph.at(y, x) if graph else None
    state["hovered"] = target.id if target else None
    if button in ("motion", "drag", "release", "press"):
        # Captured slider / job selection motion still reaches its owner.
        return False
    if button in ("wheel-up", "wheel-down", "wheel_up", "wheel_down"):
        state["active"] = False
        return False
    if button != "left" or shift:
        return False
    if target is None or not target.button:
        state["active"] = False
        return False
    state["focused"], state["active"] = target.id, True
    return _activate(app, target)


def _feedback_style(style, feedback):
    # Preserve semantic foreground, replace selection backgrounds, and remove
    # dim so the actual hit region remains readable on every supported theme.
    tokens = [token for token in style.split("+") if token not in ("dim", "sel", "rev", "under", "bold") and not token.startswith("bg:")]
    return "+".join(tokens + feedback.split("+"))


def _decorate_row(row, ranges):
    output, position, previous_style, pieces = [], 0, "", []
    for text, style in row:
        for char in text:
            size = L.vlen(char)
            # A wide character intersecting a region receives one whole style;
            # combining marks inherit its base. Never split a grapheme's cells.
            feedback = next((feedback for left, right, feedback in reversed(ranges)
                             if position < right and position + size > left), None) if size else None
            new_style = _feedback_style(style, feedback) if feedback else previous_style if not size and (pieces or output) else style
            if pieces and previous_style != new_style:
                output.append(("".join(pieces), previous_style))
                pieces = []
            pieces.append(char)
            previous_style = new_style
            position += size
    if pieces:
        output.append(("".join(pieces), previous_style))
    return output


def decorate(app, rows, origin=(0, 0)):
    """Return styled rows without changing text, width, or controller selection."""
    state = initialize(app)
    graph = _current(app)
    if graph is None:
        return rows
    targets = []
    hovered = graph.get(state["hovered"])
    focused = graph.get(state["focused"]) if state["active"] else None
    if hovered:
        targets.append((hovered, POINTER_STYLE))
    if focused:
        targets.append((focused, FOCUS_STYLE))
    if not targets:
        return rows
    y0, x0 = origin
    output = list(rows)
    for index, row in enumerate(rows):
        y = index + y0
        ranges = [(control.rect.left - x0, control.rect.right - x0, style)
                  for control, style in targets if control.rect.top <= y < control.rect.bottom]
        if ranges:
            output[index] = _decorate_row(row, ranges)
    return output


def decorate_overlays(app, overlays):
    """Apply identical feedback to absolute overlay triples."""
    if overlays is None:
        return None
    return [(y, x, decorate(app, [row], origin=(y, x))[0]) for y, x, row in overlays]
