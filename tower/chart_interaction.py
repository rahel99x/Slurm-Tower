"""Cell-accurate metric crosshairs and bounded, source-scoped box zoom.

The terminal pointer is represented by a cyan dotted crosshair. The paths here
only inspect the published graph geometry. They do not sample, scan files, copy
series, or request scheduler work. Zoom bounds are transient display state.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
import math
import time

from . import charts
from .interaction import Rect

MAX_PLOTS = 96
MAX_ZOOMS = 128
MAX_UNDO = 16
MAX_KEY_PARTS = 16
MAX_KEY_TEXT = 512
MAX_OVERLAY_CELLS = 4096
CAPTURE_TIMEOUT = 15.0
CROSSHAIR_STYLE = "cursor+bold"


@dataclass(frozen=True)
class Plot:
    key: tuple
    rect: Rect
    visible: Rect
    x_bounds: tuple
    y_bounds: tuple
    scale: str = "linear"
    layer: int = 0
    kind: str = "metric"
    payload: tuple = ()


def initialize(app):
    state = getattr(app, "chart_interaction_state", None)
    if not isinstance(state, dict):
        state = {"pending": [], "plots": (), "pointer": None, "hovered": None,
                 "capture": None, "zoom": OrderedDict(), "last_key": None,
                 "revision": 0, "frame_context": None, "ascii": False}
        app.chart_interaction_state = state
    return state


def _finite(value):
    try:
        return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)
    except (ValueError, TypeError, OverflowError):
        return False


def _key(key):
    if isinstance(key, str):
        key = (key,)
    if not isinstance(key, tuple) or not 0 < len(key) <= MAX_KEY_PARTS:
        return None
    if any(not isinstance(value, (str, int, float, bool, type(None))) or
           isinstance(value, str) and (len(value) > MAX_KEY_TEXT or value and not value.isprintable()) or
           isinstance(value, float) and not math.isfinite(value) for value in key):
        return None
    return key


def key(app, metric, source, jid=None, *, scope="metric", attempt=None):
    """Identify the actual source and attempt, independent of fresh snapshots."""
    research = getattr(app, "research", None)
    project = getattr(app, "project_state", {})
    project = project if isinstance(project, dict) else {}
    binding = project.get("binding", {})
    binding = binding if isinstance(binding, dict) and str(binding.get("job_id", "")) == str(jid or "") else {}
    identity = (scope, str(jid or ""), str(metric), str(source),
                attempt if attempt is not None else binding.get("attempt"),
                binding.get("project_root") or project.get("root"), binding.get("run_id"),
                getattr(research, "generation", None))
    # Do not truncate source paths into accidental identity collisions.
    return _key(identity)


def _state(app, name):
    value = getattr(app, name, {})
    return value if isinstance(value, dict) else {}


def _context(app):
    analysis = _state(app, "analysis_state")
    panel = _state(app, "job_panel_state")
    project = _state(app, "project_state")
    toolbar = _state(app, "toolbar_state")
    binding = project.get("binding", {})
    binding = binding if isinstance(binding, dict) else {}
    return (getattr(app, "mode", "main"), getattr(app, "tab", ""),
            getattr(app, "width", None), getattr(app, "height", None),
            getattr(app, "selected_id", None), getattr(app, "analytics_job", None),
            getattr(app, "research_job_id", None), getattr(app, "research_view", None),
            getattr(app, "analytics_view", None),
            analysis.get("modal"), analysis.get("chart_job"), analysis.get("metric"),
            panel.get("mode"), panel.get("research_view"), panel.get("analytics_view"),
            project.get("root"), binding.get("run_id"), binding.get("job_id"), binding.get("attempt"),
            getattr(getattr(app, "research", None), "generation", None),
            toolbar.get("menu"), toolbar.get("panel"))


def _blocked(app):
    startup = getattr(app, "startup_state", {})
    if isinstance(startup, dict) and startup.get("running"):
        from .startup import active
        if active(app):
            return True
    toolbar = _state(app, "toolbar_state")
    if toolbar.get("menu") is not None or toolbar.get("panel"):
        return True
    mode = getattr(app, "mode", "main")
    analysis = _state(app, "analysis_state")
    return mode != "main" and not (mode == "analysis" and analysis.get("modal") in ("chart", "diff"))


def begin_frame(app, width=None, height=None):
    """Start one outer frame. Nested renderers must not clear this registry."""
    state = initialize(app)
    if state["capture"] and state["capture"]["context"] != _context(app):
        cancel(app)
    state["pending"], state["plots"], state["hovered"] = [], (), None
    state["frame_context"] = _context(app)
    state["size"] = (width, height)
    views = getattr(app, "views_ref", None) or getattr(app, "views", None)
    state["ascii"] = bool(getattr(getattr(views, "g", None), "ascii", False))


def mark(app):
    """Remember a native renderer's first pending graph before laying it out."""
    return len(initialize(app)["pending"])


def _rect(value):
    if isinstance(value, Rect):
        return value
    if (isinstance(value, (tuple, list)) and len(value) == 4 and
            all(isinstance(item, int) and not isinstance(item, bool) for item in value)):
        return Rect(*value)
    return None


def _intersection(a, b):
    result = Rect(max(a.top, b.top), max(a.left, b.left), min(a.bottom, b.bottom), min(a.right, b.right))
    return result if result.top < result.bottom and result.left < result.right else None


def _bounds(value):
    return (tuple(value) if isinstance(value, (tuple, list)) and len(value) == 2 and
            all(_finite(item) for item in value) and value[0] < value[1] else None)


def record(app, identity, metadata, *, row=0, column=0, scale="linear", layer=0):
    """Stage a chart in local cells. Only the measured plot is interactive.

    ``metadata`` comes from ``charts.braille_chart`` or ``vbar_chart``. Use
    ``place_since`` after clipping and embedding the native document in panes.
    Bounds on a logarithmic plot remain log10 coordinates throughout.
    """
    state = initialize(app)
    identity = _key(identity)
    if (identity is None or not isinstance(metadata, dict) or not metadata.get("valid", True) or
            metadata.get("has_data", True) is False or
            scale not in ("linear", "log") or
            any(not isinstance(item, int) or isinstance(item, bool) for item in (row, column, layer)) or
            len(state["pending"]) >= MAX_PLOTS):
        return None
    rect, x_bounds, y_bounds = (_rect(metadata.get("plot_rect")), _bounds(metadata.get("x_bounds")),
                               _bounds(metadata.get("y_bounds")))
    if not rect or not x_bounds or not y_bounds or rect.right - rect.left < 3 or rect.bottom - rect.top < 2:
        return None
    # The raster itself is bounded. Reject impossible geometry from embedders.
    if rect.right - rect.left > charts.MAX_COLUMNS or rect.bottom - rect.top > charts.MAX_HEIGHT:
        return None
    rect = Rect(rect.top + row, rect.left + column, rect.bottom + row, rect.right + column)
    plot = Plot(identity, rect, rect, x_bounds, y_bounds, scale, layer)
    state["pending"].append(plot)
    return plot


def place_since(app, first, *, dy=0, dx=0, clip=None):
    """Translate and clip nested plots without changing their axis mapping.

    A clip is in the translated coordinate system. Repeated placements compose
    correctly for Research scrolling, Jobs Details, and a docked history pane.
    """
    state = initialize(app)
    if (not isinstance(first, int) or isinstance(first, bool) or not 0 <= first <= len(state["pending"]) or
            any(not isinstance(item, int) or isinstance(item, bool) for item in (dy, dx))):
        return
    clip = _rect(clip) if clip is not None else None
    for i in range(first, len(state["pending"])):
        plot = state["pending"][i]
        if plot is None:
            continue
        rect = Rect(plot.rect.top + dy, plot.rect.left + dx, plot.rect.bottom + dy, plot.rect.right + dx)
        visible = Rect(plot.visible.top + dy, plot.visible.left + dx, plot.visible.bottom + dy, plot.visible.right + dx)
        if clip is not None:
            visible = _intersection(visible, clip)
        state["pending"][i] = replace(plot, rect=rect, visible=visible) if visible else None


def take_since(app, first):
    """Detach a candidate layout so discarded width probes publish no plots."""
    state = initialize(app)
    if not isinstance(first, int) or isinstance(first, bool) or not 0 <= first <= len(state["pending"]):
        return ()
    records = tuple(plot for plot in state["pending"][first:] if plot is not None)
    del state["pending"][first:]
    return records


def put_records(app, records):
    """Restore only the final candidate's already transformed geometry."""
    state = initialize(app)
    for plot in records:
        if len(state["pending"]) >= MAX_PLOTS:
            break
        if isinstance(plot, Plot):
            state["pending"].append(plot)


def map_records(records, mapping, *, dx=0, dy=0, clip=None):
    """Map native plot rows through wrapping/sticky-header layout.

    The renderer maps each original row to its actual final row. A curve is
    dropped if its visible rows become noncontiguous or change relative order.
    Missing rows at the top/bottom merely clip the gesture's visible region.
    """
    if any(not isinstance(item, int) or isinstance(item, bool) for item in (dx, dy)):
        return ()
    lookup = mapping if callable(mapping) else getattr(mapping, "get", None)
    if not callable(lookup):
        return ()
    clip = _rect(clip) if clip is not None else None
    output = []
    for plot in records:
        if not isinstance(plot, Plot):
            continue
        pairs = []
        for row in range(plot.visible.top, plot.visible.bottom):
            mapped = lookup(row)
            if isinstance(mapped, int) and not isinstance(mapped, bool):
                pairs.append((row, mapped))
        if not pairs or any(b[0] != a[0] + 1 or b[1] != a[1] + 1 for a, b in zip(pairs, pairs[1:])):
            continue
        offset = pairs[0][1] - pairs[0][0] + dy
        rect = Rect(plot.rect.top + offset, plot.rect.left + dx, plot.rect.bottom + offset, plot.rect.right + dx)
        visible = Rect(pairs[0][1] + dy, plot.visible.left + dx,
                       pairs[-1][1] + dy + 1, plot.visible.right + dx)
        visible = _intersection(visible, clip) if clip is not None else visible
        if visible:
            output.append(replace(plot, rect=rect, visible=visible))
        if len(output) >= MAX_PLOTS:
            break
    return tuple(output)


def publish(app, width=None, height=None):
    """Freeze only currently painted geometry after all layout transforms."""
    state = initialize(app)
    width = width if isinstance(width, int) else getattr(app, "width", None)
    height = height if isinstance(height, int) else getattr(app, "height", None)
    plots, live_controls = [], []
    if not _blocked(app):
        layer = 1 if getattr(app, "mode", "main") == "analysis" else 0
        screen = Rect(0, 0, height, width) if isinstance(width, int) and isinstance(height, int) else None
        for plot in state["pending"]:
            if plot is None or plot.layer != layer:
                continue
            visible = _intersection(plot.visible, screen) if screen is not None else plot.visible
            if visible:
                painted = replace(plot, visible=visible)
                (live_controls if plot.kind == "live-controls" else plots).append(painted)
    from .metric_live import publish as publish_live
    publish_live(app, live_controls)
    state["plots"] = tuple(plots)
    state["frame_context"] = _context(app)
    tick(app)
    if state["pointer"]:
        hover(app, *state["pointer"])
    return state["plots"]


def _at(app, y, x):
    state = initialize(app)
    if (any(not isinstance(value, int) or isinstance(value, bool) for value in (y, x)) or
            _blocked(app) or state["frame_context"] != _context(app)):
        return None
    return next((plot for plot in reversed(state["plots"]) if plot.visible.contains(y, x)), None)


def hover(app, y, x):
    """Cosmetic feedback only; no chart is rasterized for a pointer report."""
    state = initialize(app)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in (y, x)):
        return False
    state["pointer"] = (y, x)
    plot = _at(app, y, x)
    state["hovered"] = plot.key if plot else None
    return plot is not None


def active(app):
    return initialize(app)["capture"] is not None


def _same_plot(current, original):
    return (current is not None and current.key == original.key and current.rect == original.rect and
            current.visible == original.visible and current.scale == original.scale and
            current.x_bounds == original.x_bounds and current.y_bounds == original.y_bounds)


def tick(app, now=None):
    state = initialize(app)
    capture = state["capture"]
    if capture:
        current = next((plot for plot in state["plots"] if _same_plot(plot, capture["plot"])), None)
        now = time.monotonic() if now is None else now
        if (_blocked(app) or capture["context"] != _context(app) or not _same_plot(current, capture["plot"]) or
                now - capture["last"] > CAPTURE_TIMEOUT):
            state["capture"] = None
    if _blocked(app) or state["frame_context"] != _context(app):
        state["hovered"] = None


def cancel(app):
    """Discard a preview. Zoom changes only on a valid release inside the plot."""
    state = initialize(app)
    was_active = state["capture"] is not None
    state["capture"] = None
    return was_active


def _say(app, message):
    callback = getattr(app, "say", None)
    if callable(callback):
        callback(message)


def _apply(app, plot, target):
    from .metric_live import stop_for_zoom
    stop_for_zoom(app, plot.key)
    state = initialize(app)
    zooms = state["zoom"]
    old = zooms.get(plot.key)
    undo = list(old.get("undo", ())) if old else []
    undo.append({"x": old["x"], "y": old["y"]} if old else None)
    zooms[plot.key] = {**target, "scale": plot.scale, "undo": undo[-MAX_UNDO:]}
    zooms.move_to_end(plot.key)
    while len(zooms) > MAX_ZOOMS:
        zooms.popitem(last=False)
    state["last_key"] = plot.key
    state["revision"] += 1
    _say(app, "Chart area zoomed; u undoes, 0 resets while over this graph")


def handle_mouse(app, y, x, button="left", shift=False):
    state = initialize(app)
    previous = state["capture"]
    if any(not isinstance(value, int) or isinstance(value, bool) for value in (y, x)):
        cancel(app)
        return previous is not None
    tick(app)
    capture = state["capture"]
    if previous is not None and capture is None and button in ("motion", "drag", "release"):
        return True
    if button in ("motion", "drag"):
        hover(app, y, x)
        if capture:
            capture["current"] = (y, x)
            capture["last"] = time.monotonic()
            return True
        return False
    if capture:
        if button == "release":
            state["capture"] = None
            plot = capture["plot"]
            start_y, start_x = capture["start"]
            if (not plot.visible.contains(y, x) or abs(x - start_x) < 2 or abs(y - start_y) < 1):
                return True
            left, right = sorted((start_x, x))
            top, bottom = sorted((start_y, y))
            # Terminal cells represent the endpoints of the actual plotted axes.
            xf = lambda value: (value - plot.rect.left) / (plot.rect.right - plot.rect.left - 1)
            yf = lambda value: 1 - (value - plot.rect.top) / (plot.rect.bottom - plot.rect.top - 1)
            target = {"x": (charts._between(*plot.x_bounds, xf(left)), charts._between(*plot.x_bounds, xf(right))),
                      "y": (charts._between(*plot.y_bounds, yf(bottom)), charts._between(*plot.y_bounds, yf(top)))}
            if _bounds(target["x"]) and _bounds(target["y"]):
                _apply(app, plot, target)
            hover(app, y, x)
            return True
        cancel(app)
        # A second press starts a fresh gesture; wheels/right-clicks pass on.
    plot = _at(app, y, x)
    if button in ("press", "left") and plot:
        state["last_key"] = plot.key
        if button == "press":
            state["capture"] = {"plot": plot, "context": _context(app), "start": (y, x),
                                "current": (y, x), "last": time.monotonic()}
        hover(app, y, x)
        return True
    return False


def bounds(app, identity, *, scale=None):
    """Get source-specific coordinates without consulting source data."""
    state = initialize(app)
    identity = _key(identity)
    zoom = state["zoom"].get(identity) if identity else None
    if zoom is None or scale is not None and zoom["scale"] != scale:
        return None
    return {"x": zoom["x"], "y": zoom["y"]}


def undo(app, identity=None):
    state = initialize(app)
    identity = _key(identity) if identity is not None else state["hovered"] or state["last_key"]
    value = state["zoom"].get(identity)
    if not value:
        return False
    history = list(value.get("undo", ()))
    previous = history.pop() if history else None
    if previous is None:
        state["zoom"].pop(identity, None)
    else:
        state["zoom"][identity] = {**previous, "scale": value["scale"], "undo": history}
    state["revision"] += 1
    cancel(app)
    return True


def reset(app, identity=None):
    state = initialize(app)
    identity = _key(identity) if identity is not None else state["hovered"] or state["last_key"]
    if identity not in state["zoom"]:
        return False
    state["zoom"].pop(identity, None)
    state["revision"] += 1
    cancel(app)
    return True


def handle_key(app, key):
    state = initialize(app)
    if active(app):
        cancel(app)
        return key == "esc"
    if _blocked(app) or state["frame_context"] != _context(app):
        return False
    if state["hovered"] is None:
        return False
    if key in ("u", "0"):
        (undo if key == "u" else reset)(app, state["hovered"])
        return True
    return False


def command_names():
    return ["chartzoom"]


def run_command(app, args):
    if not args or args[0] != "chartzoom":
        return False
    if len(args) != 2 or args[1] not in ("undo", "reset"):
        _say(app, "chartzoom undo|reset (last selected or hovered metric graph)")
    else:
        changed = (undo if args[1] == "undo" else reset)(app)
        _say(app, "Chart zoom " + ("updated" if changed else "is already at its original view"))
    return True


def overlay(views, snap, app, width, height):
    return None


def feedback(app, *, ascii_=None):
    """Return a small cosmetic overlay over the cached chart document."""
    state = initialize(app)
    tick(app)
    capture = state["capture"]
    pointer = state["pointer"]
    plot = capture["plot"] if capture else _at(app, *pointer) if pointer else None
    if plot is None:
        return []
    ascii_ = state["ascii"] if ascii_ is None else ascii_
    dot, output, seen = ("." if ascii_ else "·"), [], set()
    def put(y, x, char=dot):
        if plot.visible.contains(y, x) and (y, x) not in seen and len(output) < MAX_OVERLAY_CELLS:
            seen.add((y, x))
            output.append((y, x, [(char, CROSSHAIR_STYLE)]))
    if capture:
        sy, sx = capture["start"]
        cy, cx = capture["current"]
        cy = min(plot.visible.bottom - 1, max(plot.visible.top, cy))
        cx = min(plot.visible.right - 1, max(plot.visible.left, cx))
        left, right = sorted((sx, cx))
        top, bottom = sorted((sy, cy))
        for x in range(left, right + 1):
            if (x - left) % 2 == 0:
                put(top, x)
                put(bottom, x)
        for y in range(top, bottom + 1):
            if (y - top) % 2 == 0:
                put(y, left)
                put(y, right)
        # Corners are explicit plus signs even when a dotted edge overlaps.
        corners = {(top, left), (top, right), (bottom, left), (bottom, right)}
        output = [item for item in output if item[:2] not in corners]
        for y, x in sorted(corners):
            output.append((y, x, [("+", CROSSHAIR_STYLE)]))
    elif pointer:
        y, x = pointer
        for column in range(plot.visible.left, plot.visible.right):
            if (column - x) % 2 == 0 and column != x:
                put(y, column)
        for row in range(plot.visible.top, plot.visible.bottom):
            if (row - y) % 2 == 0 and row != y:
                put(row, x)
        put(y, x, "+")
    return output
