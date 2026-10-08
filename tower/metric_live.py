"""Per-metric live display windows, independent of scheduler sampling cadence.

These controls only change the displayed time range. A one millisecond window
never implies one millisecond measurements or additional scheduler requests.
State is transient, bounded, and scoped to an exact job/source/attempt.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
import time

from . import clock, layout as L
from .interaction import Rect

MIN_DELTA = 0.001
MAX_DELTA = 5.0
MAX_METRICS = 128
MIN_WIDTH = 24
DOCUMENT_INTERVAL = 0.1
CAPTURE_TIMEOUT = 15.0


@dataclass(frozen=True)
class Controls:
    key: tuple
    token: str
    rect: Rect
    visible: Rect
    toggle: Rect
    slider: Rect
    slider_full: Rect
    layer: int = 0


def initialize(app):
    state = getattr(app, "metric_live_state", None)
    if not isinstance(state, dict):
        state = {
            "entries": OrderedDict(),
            "current": OrderedDict(),
            "counter": 0,
            "records": (),
            "context": None,
            "command_records": (),
            "command_context": None,
            "command_viewport": None,
            "capture": None,
            "focus": None,
            "pending_focus": None,
            "revision": 0,
            "ascii": False,
        }
        app.metric_live_state = state
    return state


def canonical(identity):
    """A companion filled area shares its source curve's live display window."""
    from .chart_interaction import _key

    identity = _key(identity)
    if identity is None:
        return None
    if identity[0] == "resource-area":
        return ("resource-series", *identity[1:])
    return identity


def _family(identity):
    # Attempt, project/run and research generation remain in the exact key.
    # A newer published attempt invalidates older controls for the same source.
    return identity[:4]


def _finite(value):
    try:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    except (ValueError, TypeError, OverflowError):
        return False


def fraction(delta):
    """Left is five seconds; right is one millisecond, with equal log steps."""
    if not _finite(delta):
        delta = MAX_DELTA
    delta = min(MAX_DELTA, max(MIN_DELTA, delta))
    return math.log(MAX_DELTA / delta) / math.log(MAX_DELTA / MIN_DELTA)


def delta_at(value):
    if not _finite(value):
        value = 0.0
    value = min(1.0, max(0.0, value))
    if value == 0:
        return MAX_DELTA
    if value == 1:
        return MIN_DELTA
    return MAX_DELTA * math.exp(-value * math.log(MAX_DELTA / MIN_DELTA))


def format_delta(value):
    return f"{value:.3g}s" if value >= 1 else f"{value*1000:.3g}ms"


def _entry(app, identity, *, running=None):
    state = initialize(app)
    identity = canonical(identity)
    if identity is None:
        return None
    entry = state["entries"].get(identity)
    if entry is None and running is False:
        return None
    if entry is None:
        state["counter"] += 1
        entry = {
            "token": "m" + str(state["counter"]),
            "delta": MAX_DELTA,
            "enabled": False,
            "running": False,
        }
        state["entries"][identity] = entry
        state["wanted_revision"] = state.get("wanted_revision", 0) + 1
    state["entries"].move_to_end(identity)
    while len(state["entries"]) > MAX_METRICS:
        stale, _ = state["entries"].popitem(last=False)
        state["wanted_revision"] = state.get("wanted_revision", 0) + 1
        if state["current"].get(_family(stale)) == stale:
            state["current"].pop(_family(stale), None)
    if running is not None:
        entry["running"] = running is True
        if running is True:
            state["current"][_family(identity)] = identity
            state["current"].move_to_end(_family(identity))
            while len(state["current"]) > MAX_METRICS:
                state["current"].popitem(last=False)
        elif entry["enabled"]:
            entry["enabled"] = False
            state["revision"] += 1
    return entry


def set_running(app, identity, running):
    """The renderer supplies status from its already published exact job."""
    return _entry(app, identity, running=running is True)


def _slot_changed(state, jobs, identity):
    """Detect an in-place replacement without scanning unrelated job rows."""
    jid = str(identity[1]) if len(identity) > 1 else ""
    position = state.get("job_positions", {}).get(jid)
    return position is not None and (
        position >= len(jobs) or jobs[position] is not state.get("job_map", {}).get(jid)
    )


def _published_job(app, identity):
    """Index only wanted IDs, across the complete already published job list.

    A new list, list length, or wanted-ID set rebuilds this bounded index once.
    Additional metrics for the same job reuse it. State checks use the original
    Job objects, so in-place completion does not require rescanning other jobs.
    """
    state = initialize(app)
    store = getattr(app, "store", None)
    jobs = getattr(store, "jobs", None)
    if not isinstance(jobs, (list, tuple)):
        return None, False
    wanted_changed = False
    if state.get("indexed_revision") != state.get("wanted_revision", 0):
        wanted = frozenset(str(key[1]) for key in state["entries"] if len(key) > 1)
        wanted_changed = wanted != state.get("wanted_ids")
        state["wanted_ids"] = wanted
        state["indexed_revision"] = state.get("wanted_revision", 0)
    if (
        state.get("jobs_ref") is not jobs
        or state.get("store_ref") is not store
        or state.get("jobs_count") != len(jobs)
        or wanted_changed
        or _slot_changed(state, jobs, identity)
    ):
        wanted = state.get("wanted_ids", frozenset())
        found, positions = {}, {}
        for position, job in enumerate(jobs):
            jid = str(getattr(job, "id", ""))
            if jid in wanted:
                found[jid] = job
                positions[jid] = position
            if len(found) == len(wanted):
                break
        state["jobs_ref"], state["store_ref"] = jobs, store
        state["jobs_count"], state["job_map"] = len(jobs), found
        state["job_positions"] = positions
    return (
        state.get("job_map", {}).get(str(identity[1]) if len(identity) > 1 else ""),
        True,
    )


def _eligible(app, identity):
    state = initialize(app)
    entry = state["entries"].get(identity)
    valid = bool(
        entry
        and entry["running"]
        and state["current"].get(_family(identity)) == identity
    )
    if valid:
        job, available = _published_job(app, identity)
        if available:
            valid = job is not None and getattr(job, "state", None) == "RUNNING"
            if (
                valid
                and len(identity) > 4
                and isinstance(identity[4], str)
                and (
                    identity[0] == "resource-series"
                    or identity[4].startswith("scheduler:")
                )
            ):
                attempt = "|".join(
                    str(getattr(job, name, None) or "") for name in ("submit", "start")
                )
                prefix = "scheduler:" if identity[4].startswith("scheduler:") else ""
                valid = identity[4] == prefix + attempt
    if not valid and entry and entry["enabled"]:
        entry["enabled"] = False
        state["revision"] += 1
    return valid


def window(app, identity, now=None):
    """Use the dashboard clock, with no extrapolated endpoint or source read."""
    identity = canonical(identity)
    if identity is None or not _eligible(app, identity):
        return None
    entry = initialize(app)["entries"][identity]
    if not entry["enabled"]:
        return None
    capture = getattr(app, "chart_interaction_state", {}).get("capture")
    if capture and canonical(capture["plot"].key) == identity:
        # Keep the exact painted mapping stable while an XY area is selected.
        # Cancelling resumes Live; a committed box turns it off explicitly.
        return capture["plot"].x_bounds
    now = clock.now() if now is None else now
    if not _finite(now):
        return None
    first = now - entry["delta"]
    return (first, now) if _finite(first) and first < now else None


def enabled(app, identity):
    identity = canonical(identity)
    entry = initialize(app)["entries"].get(identity)
    return bool(identity is not None and _eligible(app, identity) and entry["enabled"])


def _say(app, message):
    callback = getattr(app, "say", None)
    if callable(callback):
        callback(message)


def set_enabled(app, identity, value):
    identity = canonical(identity)
    if identity is None or not _eligible(app, identity) or type(value) is not bool:
        return False
    state = initialize(app)
    entry = state["entries"][identity]
    if value:
        from .chart_interaction import initialize as chart_state

        chart = chart_state(app)
        # A new Live window supersedes all boxes for this metric/area source.
        removed = [key for key in chart["zoom"] if canonical(key) == identity]
        for key in removed:
            chart["zoom"].pop(key, None)
        if removed:
            chart["revision"] += 1
    if entry["enabled"] != value:
        entry["enabled"] = value
        state["revision"] += 1
    return True


def stop_for_zoom(app, identity):
    identity = canonical(identity)
    state = initialize(app)
    entry = state["entries"].get(identity)
    if entry and entry["enabled"]:
        entry["enabled"] = False
        state["revision"] += 1


def set_delta(app, identity, value):
    identity = canonical(identity)
    if (
        identity is None
        or not _eligible(app, identity)
        or not _finite(value)
        or not MIN_DELTA <= value <= MAX_DELTA
    ):
        return False
    state = initialize(app)
    entry = state["entries"][identity]
    if entry["delta"] != value:
        entry["delta"] = float(value)
        state["revision"] += 1
    return True


def _row(g, entry, width):
    """One stable-width row, with both slider endpoints at compact widths."""
    compact = width < 36
    if compact:
        toggle = (
            ("+ Live" if entry["enabled"] else "o Live")
            if g.ascii
            else ("● Live" if entry["enabled"] else "○ Live")
        )
        label = format_delta(entry["delta"])
        label_width = 6
    else:
        toggle = "[Live ON ]" if entry["enabled"] else "[Live off]"
        label = ("dt " if g.ascii else "Δ ") + format_delta(entry["delta"])
        label_width = 9 if g.ascii else 8
    text_prefix = toggle + " " + L.pad(label, label_width) + "5s "
    suffix = " 1ms"
    count = max(3, width - L.vlen(text_prefix) - L.vlen(suffix))
    slider_left = L.vlen(text_prefix)
    index = round(fraction(entry["delta"]) * (count - 1))
    track = "-" if g.ascii else "─"
    thumb = "o" if g.ascii else "◆"
    row = [
        (toggle, "cyan+bold" if entry["enabled"] else "muted"),
        (" " + L.pad(label, label_width), "text-secondary"),
        ("5s ", "dim"),
        (track * index, "track"),
        (thumb, "cursor+bold"),
        (track * (count - index - 1), "track"),
        (suffix, "dim"),
    ]
    return L.clip_row(row, width), (0, L.vlen(toggle), slider_left, slider_left + count)


def controls(g, app, identity, width, *, running=True, row=0, column=0, layer=0):
    """Render and stage one row before its curve. Filled companions omit it."""
    identity = canonical(identity)
    entry = _entry(app, identity, running=running is True)
    if (
        entry is None
        or not _eligible(app, identity)
        or running is not True
        or not isinstance(width, int)
        or isinstance(width, bool)
        or width < MIN_WIDTH
        or width > 4096
        or any(
            not isinstance(v, int) or isinstance(v, bool) for v in (row, column, layer)
        )
    ):
        return [], []
    rendered, spans = _row(g, entry, width)
    from .chart_interaction import Plot, put_records

    rect = Rect(row, column, row + 1, column + width)
    payload = (*spans, entry["token"])
    put_records(
        app,
        (
            Plot(
                identity,
                rect,
                rect,
                (0.0, 1.0),
                (0.0, 1.0),
                "linear",
                layer,
                "live-controls",
                payload,
            ),
        ),
    )
    hits = [
        (
            row,
            "control",
            {
                "id": "metric-live:" + entry["token"],
                "label": "Toggle Live metric window",
                "left": column + spans[0],
                "right": column + spans[1],
                "action": ("command", "metric-live " + entry["token"] + " toggle"),
                "group": "metric-live",
            },
        ),
        (
            row,
            "control",
            {
                "id": "metric-window:" + entry["token"],
                "label": "Adjust Live metric time window",
                "left": column + spans[2],
                "right": column + spans[3],
                "action": ("command", "metric-window " + entry["token"] + " focus"),
                "group": "metric-live",
            },
        ),
    ]
    return [rendered], hits


def _context(app):
    from .chart_interaction import _context as context

    return context(app)


def _blocked(app):
    from .chart_interaction import _blocked as blocked

    return blocked(app)


def _viewport(app):
    """Small, immutable presentation/source guard for palette commands.

    A palette hides the interaction registry while retaining the document it
    was opened over. Do not accept a saved token after that document moves,
    changes its split, or switches its reported source. This reads published
    UI state only; sample values and moving Live bounds are deliberately absent.
    """
    layout = getattr(app, "layout_state", None)
    scroll = getattr(layout, "scroll", {})
    scroll = scroll if isinstance(scroll, dict) else {}
    tab = getattr(app, "tab", "")
    browser = getattr(app, "history_browser_state", {})
    browser = browser if isinstance(browser, dict) else {}
    view = browser.get("views", {}).get(tab, {})
    view = view if isinstance(view, dict) else {}
    document = getattr(app, "analytics_document_state", {})
    document = document if isinstance(document, dict) else {}
    analysis = getattr(app, "analysis_state", {})
    analysis = analysis if isinstance(analysis, dict) else {}
    result = getattr(app, "analysis_result", {})
    result = result if isinstance(result, dict) else {}
    axes = analysis.get("axes", {})
    axis = axes.get(analysis.get("metric"), {}) if isinstance(axes, dict) else {}
    axis = axis if isinstance(axis, dict) else {}
    views = getattr(app, "views_ref", None) or getattr(app, "views", None)
    return (
        getattr(layout, "density", None),
        getattr(layout, "maximized", None),
        getattr(layout, "ratio", None),
        tuple(
            sorted(
                (key, value)
                for key, value in scroll.items()
                if isinstance(key, str) and key.startswith(tab + ":")
            )
        ),
        tuple(view.get(key) for key in ("dock", "enabled", "ratio", "top", "selected")),
        document.get("identity"),
        document.get("top"),
        getattr(app, "research_scroll", None),
        tuple(
            analysis.get(key) for key in ("scroll", "zoom", "pan", "window", "preset")
        ),
        tuple(
            tuple(analysis.get(key, ()))
            for key in ("pinned", "hidden", "order", "expanded")
        ),
        tuple(axis.get(key) for key in ("mode", "low", "high")),
        getattr(app, "analysis_result_job", None),
        getattr(app, "analysis_result_generation", None),
        result.get("path"),
        bool(getattr(getattr(views, "g", None), "ascii", False)),
    )


def _clip(rect, visible):
    candidate = Rect(
        max(rect.top, visible.top),
        max(rect.left, visible.left),
        min(rect.bottom, visible.bottom),
        min(rect.right, visible.right),
    )
    return (
        candidate
        if candidate.top < candidate.bottom and candidate.left < candidate.right
        else None
    )


def publish(app, records):
    """Publish transformed control rows from the same bounded plot pipeline."""
    state = initialize(app)
    published = []
    if not _blocked(app):
        for record in records:
            if not _eligible(app, record.key) or len(record.payload) != 5:
                continue
            a, b, c, d, token = record.payload
            entry = state["entries"].get(record.key)
            if not entry or token != entry["token"]:
                continue
            toggle = Rect(
                record.rect.top,
                record.rect.left + a,
                record.rect.bottom,
                record.rect.left + b,
            )
            slider = Rect(
                record.rect.top,
                record.rect.left + c,
                record.rect.bottom,
                record.rect.left + d,
            )
            visible_toggle = _clip(toggle, record.visible)
            visible_slider = _clip(slider, record.visible)
            if visible_toggle and visible_slider:
                published.append(
                    Controls(
                        record.key,
                        token,
                        record.rect,
                        record.visible,
                        visible_toggle,
                        visible_slider,
                        slider,
                        record.layer,
                    )
                )
            if len(published) >= MAX_METRICS:
                break
    state["records"] = tuple(published)
    state["context"] = _context(app)
    if not _blocked(app):
        # These records are only a command target after returning from the
        # palette. Never put them back into mouse or keyboard publication.
        state["command_records"] = state["records"]
        state["command_context"] = state["context"]
        state["command_viewport"] = _viewport(app)
    tick(app)
    return state["records"]


def descriptors(app):
    state = initialize(app)
    if _blocked(app) or state["context"] != _context(app):
        return ()
    output = []
    for control in state["records"]:
        for kind, rect, label, command in (
            (
                "metric-live",
                control.toggle,
                "Toggle Live metric window",
                "metric-live " + control.token + " toggle",
            ),
            (
                "metric-window",
                control.slider,
                "Adjust Live metric time window",
                "metric-window " + control.token + " focus",
            ),
        ):
            output.append(
                {
                    "id": kind + ":" + control.token,
                    "label": label,
                    "rect": rect,
                    "action": ("command", command),
                    "group": "metric-live",
                }
            )
    return tuple(output)


def _current(app, token):
    state = initialize(app)
    if _blocked(app) or state["context"] != _context(app):
        return None
    return next(
        (
            control
            for control in state["records"]
            if control.token == token and _eligible(app, control.key)
        ),
        None,
    )


def _command_current(app, token):
    control = _current(app, token)
    if control is not None:
        return control
    state = initialize(app)
    context = state["context"]
    if (
        _blocked(app)
        or not context
        or context[0] != "palette"
        or state.get("command_context") != _context(app)
        or state.get("command_viewport") != _viewport(app)
    ):
        return None
    return next(
        (
            control
            for control in state.get("command_records", ())
            if control.token == token and _eligible(app, control.key)
        ),
        None,
    )


def active(app):
    return initialize(app)["capture"] is not None


def cancel(app):
    state = initialize(app)
    capture = state["capture"]
    if capture:
        entry = state["entries"].get(capture["control"].key)
        if entry and entry["delta"] != capture["original"]:
            entry["delta"] = capture["original"]
            state["revision"] += 1
    if capture:
        state["cancelled_release"] = True
    state["capture"] = None
    state["focus"] = None
    state["pending_focus"] = None
    return capture is not None


def tick(app, now=None):
    state = initialize(app)
    for identity, entry in state["entries"].items():
        if entry["enabled"]:
            _eligible(app, identity)
    capture = state["capture"]
    if capture:
        current = _current(app, capture["control"].token)
        now = time.monotonic() if now is None else now
        if (
            current != capture["control"]
            or capture["context"] != _context(app)
            or now - capture["last"] > CAPTURE_TIMEOUT
        ):
            cancel(app)
    if state["focus"]:
        current = _current(app, state["focus"])
        pending = state.get("pending_focus")
        if pending:
            valid = (
                not _blocked(app)
                and pending["control"].token == state["focus"]
                and pending["context"] == _context(app)
                and pending["viewport"] == _viewport(app)
                and _eligible(app, pending["control"].key)
            )
            # The chart modal's outer compose publishes before its overlay.
            # Wait for that overlay, while keeping the same guarded source.
            awaiting_overlay = getattr(app, "mode", "main") == "analysis" and not any(
                plot is not None and plot.layer == 1
                for plot in getattr(app, "chart_interaction_state", {}).get(
                    "pending", ()
                )
            )
            awaiting_frame = (
                state["context"] and state["context"][0] == "palette"
            ) or awaiting_overlay
            if not valid or (current != pending["control"] and not awaiting_frame):
                state["focus"] = None
                state["pending_focus"] = None
            elif current is not None:
                state["pending_focus"] = None
        elif current is None:
            state["focus"] = None
    else:
        state["pending_focus"] = None


def _move(app, control, x):
    span = control.slider_full.right - control.slider_full.left - 1
    set_delta(app, control.key, delta_at((x - control.slider_full.left) / max(1, span)))


def _focus_graph(app, token, kind):
    """Transfer focus to this already published control without activating it."""
    from .interaction import _current as current_graph, initialize as interaction_state

    graph = current_graph(app)
    identity = kind + ":" + token
    target = graph.get(identity) if graph else None
    if target is not None and target.enabled:
        state = interaction_state(app)
        state["focused"], state["active"] = identity, True
        browser = getattr(app, "history_browser_state", None)
        if isinstance(browser, dict):
            browser["focused"] = False


def handle_mouse(app, y, x, button="left", shift=False):
    state = initialize(app)
    previous = state["capture"]
    if (
        button == "release"
        and previous is None
        and state.pop("cancelled_release", False)
    ):
        return True
    if button in ("press", "left"):
        state["cancelled_release"] = False
    if any(not isinstance(v, int) or isinstance(v, bool) for v in (y, x)):
        return cancel(app)
    tick(app)
    capture = state["capture"]
    if previous and not capture and button in ("motion", "drag", "release"):
        return True
    if capture:
        if button in ("motion", "drag", "release"):
            control = capture["control"]
            if (
                button == "release"
                and not control.visible.top <= y < control.visible.bottom
            ):
                cancel(app)
                return True
            _move(app, control, x)
            capture["last"] = time.monotonic()
            if button == "release":
                state["capture"] = None
            return True
        cancel(app)
    if (
        button not in ("press", "left")
        or _blocked(app)
        or state["context"] != _context(app)
    ):
        return False
    for control in reversed(state["records"]):
        if control.toggle.contains(y, x):
            from .chart_interaction import cancel as cancel_chart

            cancel_chart(app)
            entry = state["entries"][control.key]
            set_enabled(app, control.key, not entry["enabled"])
            _focus_graph(app, control.token, "metric-live")
            state["focus"] = None
            return True
        if control.slider.contains(y, x):
            from .chart_interaction import cancel as cancel_chart

            cancel_chart(app)
            state["focus"] = control.token
            _focus_graph(app, control.token, "metric-window")
            if button == "press":
                state["capture"] = {
                    "control": control,
                    "context": _context(app),
                    "original": state["entries"][control.key]["delta"],
                    "last": time.monotonic(),
                }
            _move(app, control, x)
            return True
    state["focus"] = None
    return False


def handle_key(app, key):
    state = initialize(app)
    if active(app):
        cancel(app)
        return key == "esc"
    control = _current(app, state["focus"]) if state["focus"] else None
    if not control:
        return False
    if key in ("esc", "enter", "tab", "btab", "up", "down"):
        state["focus"] = None
        return key in ("esc", "enter")
    if key in ("left", "right", "home", "end", "pgup", "pgdn"):
        entry = state["entries"][control.key]
        step = (5 if key in ("pgup", "pgdn") else 1) / max(
            1, control.slider_full.right - control.slider_full.left - 1
        )
        value = (
            0.0
            if key == "home"
            else (
                1.0
                if key == "end"
                else fraction(entry["delta"])
                + (-step if key in ("left", "pgup") else step)
            )
        )
        set_delta(app, control.key, delta_at(value))
        return True
    return False


def command_names():
    return ["metric-live", "metric-window"]


def run_command(app, args):
    if not args or args[0] not in command_names():
        return False
    control = _command_current(app, args[1]) if len(args) >= 2 else None
    if not control:
        _say(app, "Select a currently running metric's visible Live control")
        return True
    if (
        args[0] == "metric-live"
        and len(args) == 3
        and args[2] in ("on", "off", "toggle")
    ):
        entry = initialize(app)["entries"][control.key]
        set_enabled(
            app,
            control.key,
            not entry["enabled"] if args[2] == "toggle" else args[2] == "on",
        )
    elif args[0] == "metric-window" and len(args) == 3:
        if args[2] == "focus":
            state = initialize(app)
            state["focus"] = control.token
            state["pending_focus"] = (
                {
                    "control": control,
                    "context": _context(app),
                    "viewport": _viewport(app),
                }
                if _current(app, control.token) is None
                else None
            )
        else:
            try:
                value = float(args[2])
            except (ValueError, OverflowError):
                value = float("nan")
            if not set_delta(app, control.key, value):
                _say(app, "Metric window must be 0.001 to 5 seconds")
    else:
        _say(app, "metric-live TOKEN on|off|toggle | metric-window TOKEN focus|SECONDS")
    return True


def document_revision(app):
    return initialize(app)["revision"]


def document_interval(app):
    """At most ten document refreshes/second while a Live plot is visible."""
    if _blocked(app):
        return None
    chart = getattr(app, "chart_interaction_state", {})
    capture = chart.get("capture")
    captured = canonical(capture["plot"].key) if capture else None
    state = initialize(app)
    return (
        DOCUMENT_INTERVAL
        if any(
            enabled(app, record.key) and record.key != captured
            for record in state["records"]
        )
        else None
    )


def feedback(app, g):
    """Update only the small cached control rows between document refreshes."""
    state = initialize(app)
    tick(app)
    if _blocked(app) or state["context"] != _context(app):
        return []
    output = []
    for control in state["records"]:
        entry = state["entries"].get(control.key)
        if not entry:
            continue
        row, _ = _row(g, entry, control.rect.right - control.rect.left)
        left = control.visible.left - control.rect.left
        # Control text is one-cell terminal glyphs; cut in display coordinates.
        clipped = []
        position = 0
        for text, style in row:
            size = L.vlen(text)
            if position + size > left:
                skip = max(0, left - position)
                clipped.append((text[skip:], style))
            position += size
        from .interaction import decorate

        rendered = L.clip_row(clipped, control.visible.right - control.visible.left)
        rendered = decorate(
            app, [rendered], origin=(control.visible.top, control.visible.left)
        )[0]
        output.append((control.visible.top, control.visible.left, rendered))
    return output


def overlay(views, snap, app, width, height):
    return None
