"""Interactive, bounded research dashboards and analysis overlays.

All frame rendering uses published snapshots or in-memory samples. Passport
files are read through the existing background worker, never while drawing.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
import math
import statistics
import time

from . import charts, clock, layout as L
from .model import human, secs, short_duration, stamp
from .research import clean

MAX_METRICS = 64
MAX_POINTS = 10000
MAX_EVENTS = 512
COLORS = ("cyan", "magenta", "green", "yellow", "blue", "red")
SECTIONS = ("Overview", "Resources", "Steps", "Files", "Evidence")


def initialize(app):
    if not isinstance(getattr(app, "analysis_state", None), dict):
        app.analysis_state = {"pinned": [], "hidden": [], "order": [], "expanded": [], "colors": {},
                              "modal": "", "scroll": 0, "metric": "", "cursor": 0,
                              "zoom": 1.0, "pan": 0.0, "section": 0, "evidence_cursor": 0}
    return app.analysis_state


def restore(app, ui):
    state = initialize(app)
    saved = ui.get("analysis", {}) if isinstance(ui, dict) else {}
    if not isinstance(saved, dict):
        return
    for key in ("pinned", "hidden", "order", "expanded"):
        value = saved.get(key, [])
        if isinstance(value, list):
            state[key] = list(dict.fromkeys(x for x in value[:MAX_METRICS]
                                           if isinstance(x, str) and 0 < len(x) <= 96 and x.isprintable()))
    colors = saved.get("colors", {})
    if isinstance(colors, dict):
        state["colors"] = {k: v for k, v in list(colors.items())[:MAX_METRICS]
                           if isinstance(k, str) and 0 < len(k) <= 96 and k.isprintable() and v in COLORS}


def save(app):
    state = initialize(app)
    return {"analysis": {k: state[k] for k in ("pinned", "hidden", "order", "expanded", "colors")}}


def command_names():
    return ["dashboard", "inspect", "chart", "timeline", "diff"]


def dashboard_names(app, series):
    state = initialize(app)
    available = list(series)[:MAX_METRICS]
    order = list(dict.fromkeys(state["pinned"] + state["order"] + available))
    query = state.get("metric_filter", "").casefold()
    return [name for name in order if name in series and name not in state["hidden"] and query in name.casefold()][:MAX_METRICS]


def observe_metrics(app, result, jid):
    """Record reported phase changes observed by Tower, with their source time."""
    state = initialize(app)
    phase = result.get("phase")
    if not phase:
        return
    identity = (jid, result.get("path", ""))
    previous = dict(state.get("phase_sources", {}))
    if previous.get(identity) == phase:
        return
    timestamp = result.get("last_t")
    if not _finite(timestamp):
        timestamp = max((point.get("t") for points in result.get("series", {}).values()
                         for point in points[-1:] if _finite(point.get("t"))), default=None)
    if not _finite(timestamp):
        return
    previous[identity] = phase
    while len(previous) > MAX_METRICS:
        previous.pop(next(iter(previous)))
    state["phase_sources"] = previous
    events = list(state.get("metric_events", []))
    events.append({"t": timestamp, "kind": "phase", "job": jid,
                   "text": f"Observed reported phase: {phase}", "source": result.get("path", "")})
    del events[:-MAX_METRICS]
    state["metric_events"] = events


def _finite(value):
    try:
        return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)
    except (TypeError, ValueError, OverflowError):
        return False


def _fmt(value):
    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.9g}" if math.isfinite(value) else "unavailable"
    if isinstance(value, dict):
        return clean(", ".join(f"{k}={_fmt(v)}" for k, v in list(value.items())[:12]), limit=400)
    if isinstance(value, (list, tuple)):
        return clean(", ".join(_fmt(v) for v in value[:12]), limit=400) or "none"
    return clean(value, limit=400)


def _time(value):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))
    except (ValueError, TypeError, OverflowError, OSError):
        return _fmt(value)


def _points(points):
    """Only malformed timestamps are discarded; unknown values remain gaps."""
    return sorted(({"t": p["t"], "value": p.get("value") if _finite(p.get("value")) else None,
                    "step": p.get("step")} for p in points[-MAX_POINTS:]
                   if isinstance(p, dict) and _finite(p.get("t"))), key=lambda p: p["t"])


def memory_series(app, jid):
    store = getattr(app, "store", None)
    if store is None:
        return []
    with getattr(store, "lock", nullcontext()):
        return list(getattr(store, "series", {}).get(jid, []))[-MAX_POINTS:]


def _resource_series(app, jid):
    values = {"CPU per core (%)": [], "Memory (GB)": [], "GPU utilization (%)": []}
    for sample in memory_series(app, jid):
        if not isinstance(sample, dict) or not _finite(sample.get("t")):
            continue
        t = sample["t"]
        if sample.get("k") == "live":
            cpu = sample.get("cpu") if sample.get("cpu") is not None else sample.get("eff")
            values["CPU per core (%)"].append({"t": t, "value": cpu * 100 if _finite(cpu) else None})
            rss = sample.get("rss")
            values["Memory (GB)"].append({"t": t, "value": rss / 1024 ** 3 if _finite(rss) else None})
        elif sample.get("k") == "gpu":
            samples = sample.get("gpu", {})
            if not isinstance(samples, dict):
                samples = {}
            util = [v[0] for v in samples.values() if isinstance(v, (list, tuple)) and v and _finite(v[0])]
            values["GPU utilization (%)"].append({"t": t, "value": statistics.fmean(util) if util and len(util) == len(samples) else None})
    return {name: points for name, points in values.items() if points}


def _analysis_jid(app):
    if getattr(app, "tab", "") == "research":
        return getattr(app, "research_job_id", None) or getattr(app, "selected_id", None)
    return getattr(app, "selected_id", None)


def chart_data(app, snap):
    state = initialize(app)
    jid = state.get("chart_job") if state.get("modal") == "chart" else _analysis_jid(app)
    result = getattr(app, "analysis_result", {}) or {}
    series = result.get("series", {}) if isinstance(result, dict) else {}
    hub = getattr(app, "research", None)
    generation = getattr(hub, "generation", None)
    if (series and getattr(app, "analysis_result_job", None) == jid
            and getattr(app, "analysis_result_generation", None) == generation):
        return series, result.get("path", "application metrics"), jid
    if hub is not None and hasattr(hub, "current"):
        context = hub.context(snap, app)
        context["view"], context["jid"] = "experiment", jid
        cached = hub.current(context)
        if cached.get("series"):
            return cached["series"], cached.get("path", "application metrics"), jid
    return _resource_series(app, jid), "Tower session resource samples", jid


def viewport(points, state):
    points = _points(points)
    if not points:
        return [], (0.0, 0.0)
    t0, t1 = points[0]["t"], points[-1]["t"]
    zoom = max(1.0, min(1024.0, state.get("zoom", 1.0)))
    pan = max(0.0, min(1.0, state.get("pan", 0.0)))
    window = state.get("window")
    span = t1 - t0
    if _finite(window) and window > 0 and math.isfinite(span) and span > 0:
        zoom = max(1.0, span / window)
    # Convex interpolation avoids overflowing opposite-sign finite endpoints.
    start_fraction, end_fraction = pan * (1 - 1 / zoom), pan * (1 - 1 / zoom) + 1 / zoom
    a, b = t0 * (1 - start_fraction) + t1 * start_fraction, t0 * (1 - end_fraction) + t1 * end_fraction
    return [p for p in points if a <= p["t"] <= b], (a, b)


def _crosshair(rows, width, height, points, selected, times, ascii_):
    """Place a visible guide on the same timestamp buckets as the chart."""
    plot_width = max(0, min(charts.MAX_COLUMNS, width - 10))
    if not points or not plot_width or not selected or times[1] <= times[0]:
        return rows
    # Braille is a two-column raster, and its timestamp rounding happens there.
    raster = 1 if ascii_ else 2
    fraction = charts._fraction(selected["t"], *times)
    x = min(plot_width - 1, round(fraction * (plot_width * raster - 1)) // raster) + 10
    guide = "|" if ascii_ else "│"
    out = list(rows)
    for y in range(1, min(len(out), height + 1)):
        before, after, position = [], [], 0
        for text, style in out[y]:
            for ch in text:
                size = L.vlen(ch)
                if position + size <= x:
                    before.append((ch, style))
                elif position >= x + 1:
                    after.append((ch, style))
                position += size
        out[y] = before + [(guide, "yellow+bold")] + after
    return out


def chart_rows(g, app, points, width, height, name, source, *, interactive=True):
    state = initialize(app)
    full = _points(points)
    visible, times = viewport(full, state if interactive else {})
    values = [p["value"] for p in visible]
    color = state["colors"].get(name, COLORS[sum(ord(c) for c in name) % len(COLORS)])
    known = [v for v in values if v is not None]
    deltas = [b["t"] - a["t"] for a, b in zip(full, full[1:]) if 0 < b["t"] - a["t"] < math.inf]
    cadence = statistics.median(deltas) if deltas else None
    rows = charts.braille_chart(g, values, width, height, lo=min([0.0] + known), title=clean(name, g.ascii),
                               sample_times=[p["t"] for p in visible], times=times,
                               sample_interval=cadence, color=lambda _: color)
    if interactive and visible:
        state["cursor"] = max(0, min(len(visible) - 1, int(state.get("cursor", 0))))
        selected = visible[state["cursor"]]
        state["cursor_t"] = selected["t"]
        rows = _crosshair(rows, width, height, visible, selected, times, g.ascii)
        step = f"  step {selected['step']}" if selected.get("step") is not None else ""
        exact = repr(selected["value"]) if selected["value"] is not None else "unavailable"
        rows.append([(clean(f" {_time(selected['t'])}  t={selected['t']!r}  value {exact}{step}", g.ascii), "yellow+bold")])
    age = max(0, clock.now() - full[-1]["t"]) if full else None
    gaps = sum(1 for p in visible if p["value"] is None)
    outages = sum(b["t"] - a["t"] > cadence * 2.5 for a, b in zip(visible, visible[1:])) if cadence else 0
    rows.append([(clean(f" Source: {source} | {len(visible)}/{len(full)} samples | latest {short_duration(age)} ago | gaps {gaps + outages}", g.ascii), "dim")])
    return rows


def open_inspector(app, jid=None):
    state = initialize(app)
    jid = jid or getattr(app, "selected_id", None)
    record = app.job_record(jid) if jid and hasattr(app, "job_record") else None
    if record is None:
        app.fail("Select an active, recent, or historical job to inspect.")
        return False
    if getattr(app, "mode", "main") == "analysis" and state.get("modal") != "inspect":
        history = list(state.get("modal_back", []))
        history.append({key: state.get(key) for key in ("modal", "job", "scroll", "cursor", "section", "metric", "chart_job", "zoom", "pan", "window")})
        state["modal_back"] = history[-8:]
    else:
        state["modal_back"] = []
    state.update(modal="inspect", job=jid, section=0, scroll=0)
    app.detail_id, app.mode = jid, "analysis"
    if getattr(app, "sampler", None):
        app.sampler.select(jid)
        if not app.store.job(jid):
            app.sampler.select_fin(jid)
    return True


def timeline_events(app, snap):
    """A bounded observation timeline; missing historical phases stay unknown."""
    items = []
    for event in (snap.get("events", [])[-MAX_EVENTS:] + snap.get("job_transitions", [])[-MAX_EVENTS:] + initialize(app).get("metric_events", [])):
        if not isinstance(event, dict) or not _finite(event.get("t")):
            continue
        items.append({"t": event["t"], "kind": event.get("kind", "event"),
                      "text": event.get("text") or f"{event.get('name', '')} {event.get('state', '')}",
                      "job": str(event.get("job") or ""), "path": event.get("path", ""),
                      "line": event.get("line"), "line_basis": event.get("line_basis", "original")})
    for citation in list(getattr(app, "research_evidence", {}).values())[:128]:
        if _finite(citation.get("t")):
            items.append(dict(citation, kind="log", text=citation.get("text", "")))
    replay = getattr(app, "replay", None)
    for record in getattr(replay, "entries", [])[-128:]:
        if isinstance(record, dict) and _finite(record.get("t")):
            command = record.get("cmd", [])
            if not isinstance(command, (list, tuple)):
                continue
            items.append({"t": record["t"], "kind": "recorded", "job": "",
                          "text": "Recorded scheduler observation: " + " ".join(map(str, command)) +
                                  (" / " + str(record["err"]) if record.get("err") else "")})
    jid = _analysis_jid(app)
    samples = memory_series(app, jid)
    # Resource observations are sampled rather than duplicating every frame.
    stride = max(1, (len(samples) + 95) // 96)
    for sample in samples[::stride]:
        if _finite(sample.get("t")):
            if sample.get("k") == "live":
                text = "Resource sample: CPU " + _fmt(sample.get("cpu", sample.get("eff"))) + " per core; RSS " + (human(sample["rss"]) if _finite(sample.get("rss")) else "unavailable")
            else:
                text = "GPU resource sample"
            items.append({"t": sample["t"], "kind": "resource", "text": text, "job": jid})
    unique = {}
    for item in items:
        unique[(item["t"], item.get("kind"), item.get("job"), item.get("text"))] = item
    return sorted(unique.values(), key=lambda item: item["t"])[-MAX_EVENTS:]


def _open_timeline_event(app, event, *, seek=False):
    replay = getattr(app, "replay", None)
    if seek:
        if replay is None:
            app.fail("Timeline seeking is available in recorded sessions.")
            return
        replay.clock.seek(event["t"])
        if getattr(app, "sampler", None):
            app.sampler.refresh_all()
        app.say("Replay moved to " + _time(event["t"]))
        return
    if event.get("path"):
        from . import log_workbench
        from .navigation_ui import record
        state = initialize(app)
        previous = state.get("modal", "timeline")
        record(app, "log", force=True)
        app.mode, state["modal"] = "main", ""
        if not log_workbench.open_citation(app, event):
            app.mode, state["modal"] = "analysis", previous
    elif event.get("job"):
        open_inspector(app, event["job"])
    else:
        app.say("This event has no job or file evidence attached.")


def run_command(app, args):
    if not args or args[0] not in command_names():
        return False
    state = initialize(app)
    if getattr(app, "mode", "main") == "main":
        state["modal_back"] = []
    cmd, args = args[0], args[1:]
    if cmd == "inspect":
        if len(args) > 1:
            app.fail("inspect [JOBID]")
        else:
            open_inspector(app, args[0] if args else None)
        return True
    if cmd == "dashboard":
        action = args[0] if args else "list"
        name = args[1] if len(args) > 1 else ""
        if action == "list" and len(args) == 1 or not args:
            state.update(modal="dashboard", scroll=0)
            app.mode = "analysis"
        elif action == "reset" and len(args) == 1:
            for key in ("pinned", "hidden", "order", "expanded"):
                state[key] = []
            state["colors"] = {}
            state["metric_filter"] = ""
            app.say("Dashboard arrangement reset.")
        elif action == "search" and len(args) <= 2:
            state["metric_filter"] = name[:96]
            app.say("Dashboard search: " + (name or "cleared"))
        elif action in ("pin", "unpin", "hide", "show", "expand", "collapse") and len(args) == 2 and 0 < len(name) <= 96 and name.isprintable():
            field = {"pin": "pinned", "unpin": "pinned", "hide": "hidden", "show": "hidden", "expand": "expanded", "collapse": "expanded"}[action]
            state[field] = [v for v in state[field] if v != name]
            if action in ("pin", "hide", "expand"):
                state[field] = (state[field] + [name])[-MAX_METRICS:]
            app.say(f"Dashboard {action}: {name}")
        elif action == "move" and len(args) == 3:
            try:
                position = int(args[2])
                if not 1 <= position <= MAX_METRICS:
                    raise ValueError
                available, _, _ = chart_data(app, app.store.snapshot())
                order = list(dict.fromkeys(state["order"] + list(available)))[:MAX_METRICS]
                if name not in available and name not in order:
                    raise ValueError
                order = [v for v in order if v != name]
                order.insert(min(position - 1, len(order)), name)
                state["order"] = order
                app.say(f"Dashboard moved {name} to {position}.")
            except (ValueError, TypeError):
                app.fail("dashboard move METRIC POSITION (1..64); use a loaded metric")
        elif action == "color" and len(args) == 3 and args[2] in COLORS and 0 < len(name) <= 96 and name.isprintable():
            state["colors"][name] = args[2]
            state["colors"] = dict(list(state["colors"].items())[-MAX_METRICS:])
            app.say(f"Dashboard {name}: {args[2]}")
        else:
            app.fail("dashboard [list|reset|search TEXT|pin|unpin|hide|show|expand|collapse METRIC|move METRIC POSITION|color METRIC COLOR]")
        return True
    if cmd == "chart":
        if state.get("modal") != "chart":
            state["chart_job"] = _analysis_jid(app)
        series, _, _ = chart_data(app, app.store.snapshot())
        if args and args[0] in ("zoom", "pan", "cursor", "window"):
            try:
                value = float(args[1]) if len(args) == 2 else float("nan")
                if not math.isfinite(value):
                    raise ValueError
                if args[0] == "zoom" and 1 <= value <= 1024:
                    state["zoom"] = value
                    state.pop("window", None)
                elif args[0] == "pan" and 0 <= value <= 1:
                    state["pan"] = value
                elif args[0] == "cursor" and value >= 1 and value == int(value):
                    state["cursor"] = min(MAX_POINTS - 1, int(value) - 1)
                elif args[0] == "window" and 0 < value <= 365 * 86400:
                    state.update(window=value, pan=1.0, cursor=0)
                else:
                    raise ValueError
            except (ValueError, IndexError, OverflowError):
                app.fail("chart zoom 1..1024 | pan 0..1 | cursor SAMPLE (1-based) | window SECONDS (up to 365 days)")
                return True
        elif args:
            if len(args) != 1 or args[0] not in series:
                app.fail("chart METRIC (load metrics in Experiment first)")
                return True
            state.update(metric=args[0], cursor=0, zoom=1.0, pan=0.0)
            state.pop("window", None)
        state.update(modal="chart", scroll=0)
        app.mode = "analysis"
        return True
    if cmd == "timeline":
        if args and args[0] not in ("events", "seek"):
            app.fail("timeline [events|seek EVENT_NUMBER]")
            return True
        events = timeline_events(app, app.store.snapshot())
        if args and args[0] == "seek":
            try:
                index = int(args[1]) - 1 if len(args) == 2 else -1
                if not 0 <= index < len(events):
                    raise ValueError
                _open_timeline_event(app, events[index], seek=True)
            except ValueError:
                app.fail("timeline seek EVENT_NUMBER (shown 1-based in Timeline)")
            return True
        if len(args) > 1:
            app.fail("timeline [events|seek EVENT_NUMBER]")
            return True
        state.update(modal="timeline", cursor=max(0, len(events) - 1), scroll=0)
        app.mode = "analysis"
        return True
    if cmd == "diff":
        if args and args[0] == "passport":
            hub = getattr(app, "research", None)
            if len(args) != 3 or hub is None:
                app.fail("diff passport LEFT RIGHT")
                return True
            if getattr(hub.files, "remote", False):
                app.fail("Passport comparison needs Tower running on the cluster.")
                return True
            paths = args[1:]
            def work():
                from .provenance import load, diff
                left, right = load(paths[0]), load(paths[1])
                return {"left": left, "right": right, "differences": diff(left, right)}
            def completed(result):
                if isinstance(result, Exception):
                    app.fail("Passport comparison: " + clean(result))
                    return
                state.update(modal="diff", diff_kind="passport", comparison=result, scroll=0, unchanged=False)
                app.mode = "analysis"
                app.say("Passport comparison ready.")
            if hub.start_task(work, completed):
                app.say("Comparing passports in the background…")
            else:
                app.fail("Research worker is busy; try the comparison again when it completes.")
        else:
            ids = args or list(getattr(app, "compare_ids", [])) or sorted(getattr(app, "marks", []))
            ids = list(dict.fromkeys(ids))
            if not 2 <= len(ids) <= 6 or any(app.job_record(jid) is None for jid in ids):
                app.fail("diff JOBID JOBID [up to six jobs] or mark two jobs first")
            else:
                state.update(modal="diff", diff_kind="jobs", diff_ids=ids, scroll=0, unchanged=False)
                app.mode = "analysis"
        return True
    return False


def handle_key(app, key):
    state = initialize(app)
    action = getattr(app, "keymap", {}).get(key)
    if action in ("up", "down", "home", "end", "page_up", "page_down"):
        key = {"page_up": "pgup", "page_down": "pgdn"}.get(action, action)
    if getattr(app, "mode", "main") != "analysis":
        if getattr(app, "mode", "main") == "main" and getattr(app, "keymap", {}).get(key) == "inspector":
            open_inspector(app)
            return True
        if (getattr(app, "mode", "main") == "main" and getattr(app, "tab", "") == "research"
                and getattr(app, "research_view", "") == "experiment" and key in ("up", "down")):
            from .research import select_job
            snap = app.store.snapshot()
            ids = list(dict.fromkeys(job.id for job in snap.get("jobs", []) + snap.get("finished", [])))
            if ids:
                current = ids.index(app.research_job_id) if app.research_job_id in ids else 0
                select_job(app, ids[max(0, min(len(ids) - 1, current + (-1 if key == "up" else 1)))])
            return True
        if getattr(app, "mode", "main") == "main" and getattr(app, "tab", "") == "research" and getattr(app, "research_view", "") == "evidence":
            ids = state.get("evidence_ids", [])
            if key in ("up", "down", "home", "end") and ids:
                current = state.get("evidence_cursor", 0)
                state["evidence_cursor"] = 0 if key == "home" else len(ids) - 1 if key == "end" else max(0, min(len(ids) - 1, current + (-1 if key == "up" else 1)))
                state["evidence_focus"] = True
                return True
            if key == "enter" and ids:
                from . import log_workbench
                citation = getattr(app, "research_evidence", {}).get(ids[min(state.get("evidence_cursor", 0), len(ids) - 1)])
                if citation and citation.get("path"):
                    log_workbench.open_citation(app, citation)
                else:
                    app.say("This citation is a scheduler observation with no log file attached.")
                return True
        return False
    if key in ("esc", "q", "ctrl-b", "alt-left"):
        history = state.get("modal_back", [])
        if history:
            state.update(history[-1])
            state["modal_back"] = history[:-1]
            app.mode = "analysis"
        else:
            app.mode, state["modal"] = "main", ""
        return True
    modal = state.get("modal")
    if modal == "chart":
        series, _, _ = chart_data(app, app.store.snapshot())
        names = list(series)
        name = state.get("metric") if state.get("metric") in names else names[0] if names else ""
        points, _ = viewport(series.get(name, []), state)
        if key in ("left", "right", "up", "down", "home", "end"):
            change = -1 if key in ("left", "up") else 1
            state["cursor"] = 0 if key == "home" else max(0, len(points) - 1) if key == "end" else max(0, min(max(0, len(points) - 1), state.get("cursor", 0) + change))
        elif key in ("+", "=", "-", "_"):
            state.pop("window", None)
            state["zoom"] = max(1.0, min(1024.0, state.get("zoom", 1.0) * (2 if key in ("+", "=") else .5)))
            state["cursor"] = 0
        elif key in ("[", "]"):
            state["pan"] = max(0.0, min(1.0, state.get("pan", 0.0) + (-.1 if key == "[" else .1)))
            state["cursor"] = 0
        elif key in ("tab", "btab") and names:
            index = names.index(name)
            next_name = names[(index + (1 if key == "tab" else -1)) % len(names)]
            next_points, _ = viewport(series[next_name], state)
            timestamp = points[min(state.get("cursor", 0), len(points) - 1)]["t"] if points else None
            closest = min(range(len(next_points)), key=lambda i: abs(next_points[i]["t"] - timestamp)) if next_points and timestamp is not None else 0
            state.update(metric=next_name, cursor=closest)
    elif modal == "inspect" and key in ("tab", "btab", "left", "right"):
        state["section"] = (state.get("section", 0) + (1 if key in ("tab", "right") else -1)) % len(SECTIONS)
        state["scroll"] = 0
    elif modal == "inspect" and key in ("l", "enter"):
        from .navigation_ui import record
        record(app, "log", force=True)
        app.mode, state["modal"] = "main", ""
        app.open_log(state.get("job"))
    elif modal == "inspect" and key == "e":
        from .research import select_job
        from .navigation_ui import record
        record(app, "research", force=True)
        app.mode, state["modal"] = "main", ""
        app.enter_tab("research")
        select_job(app, state.get("job"), view="evidence", record_back=False)
    elif modal == "timeline":
        events = timeline_events(app, app.store.snapshot())
        if key in ("up", "down", "home", "end", "pgup", "pgdn"):
            delta = -1 if key == "up" else 1 if key == "down" else -10 if key == "pgup" else 10
            state["cursor"] = 0 if key == "home" else max(0, len(events) - 1) if key == "end" else max(0, min(max(0, len(events) - 1), state.get("cursor", 0) + delta))
        elif key in ("enter", "s") and events:
            _open_timeline_event(app, events[min(state.get("cursor", 0), len(events) - 1)], seek=key == "s")
    elif modal == "diff" and key == "u":
        state["unchanged"] = not state.get("unchanged", False)
        state["scroll"] = 0
    if modal not in ("chart", "timeline"):
        if key in ("up", "down", "pgup", "pgdn", "home", "end"):
            delta = -1 if key == "up" else 1 if key == "down" else -10 if key == "pgup" else 10
            state["scroll"] = 0 if key == "home" else max(0, state.get("row_count", 0) - 1) if key == "end" else max(0, state.get("scroll", 0) + delta)
    return True


def _inspector_rows(g, snap, app, width):
    state = initialize(app)
    jid = state.get("job")
    job = app.job_record(jid, snap)
    rows = [[(" ", "")] + [(f" {name} ", "rev+bold" if i == state.get("section", 0) else "dim") for i, name in enumerate(SECTIONS)]]
    if job is None:
        return rows + [[(" This job is outside the current inventory. Its exact ID remains selected.", "yellow")]]
    row = lambda text, style="": [(clean(text, g.ascii), style)]
    rows.extend([row(f" Job {jid}  {job.name}", "cyan+bold"), row(f" {job.state}  | partition {job.partition or 'unavailable'}  | elapsed {job.elapsed or 'unavailable'}", "bold")])
    details = snap.get("details", {}).get(jid, {})
    section = SECTIONS[state.get("section", 0)]
    if section == "Overview":
        for label, value in (("Submitted", getattr(job, "submit", "")), ("Started", getattr(job, "start", "")), ("Ended / expected", getattr(job, "end", "")),
                             ("Time limit", getattr(job, "limit", "")), ("Exit", getattr(job, "exit", "")), ("Reason", getattr(job, "reason", "")),
                             ("Workdir", details.get("WorkDir") or getattr(job, "workdir", "")), ("Node list", getattr(job, "nodelist", ""))):
            rows.append(row(f" {label:18} {_fmt(value) if value not in ('', None) else 'unavailable'}"))
    elif section == "Resources":
        live = snap.get("live", {}).get(jid)
        rss = getattr(live, "rss", None) if live else getattr(job, "rss", None)
        if not live and not rss:
            # Finished.rss uses zero when accounting did not report MaxRSS.
            rss = None
        cpu = getattr(live, "rate", None) if live else getattr(job, "cpu_eff", None)
        requested = getattr(job, "mem_bytes", None) if hasattr(job, "mem_bytes") else getattr(job, "req_mem", None)
        rows.extend([row(f" Allocation  {job.cpus} CPUs  | {job.nodes} nodes  | {job.gpus} GPUs", "bold"),
                     row(" Requested memory  " + (human(requested) if _finite(requested) and requested > 0 else "unavailable")),
                     row(" Observed peak RSS " + (human(rss) if _finite(rss) else "unavailable")),
                     row(" CPU per core      " + (_fmt(cpu * 100) + "%" if _finite(cpu) else "unavailable"))])
        if _finite(cpu):
            rows.append(row(" CPU occupancy", "dim"))
            rows.append(L.gradient_bar(g, cpu, max(1, min(40, width - 8))))
        rows.append(row(" Live and accounting measurements retain their original source; missing samples stay unknown.", "dim"))
    elif section == "Steps":
        steps = snap.get("steps", {}).get(jid) or snap.get("fin_steps", {}).get(jid) or []
        if not steps:
            rows.append(row(" No step records published yet.", "dim"))
        for step in steps[:256]:
            rows.append(row(f" {step.id}  {step.name}  {step.state or 'live'}  elapsed {step.elapsed or 'unavailable'}", "bold"))
            rows.append(row(f"   CPU {short_duration(step.cpu_time)}  RSS {human(step.rss) if step.rss else 'unavailable'}  tasks {step.ntasks}  exit {step.exit or 'unavailable'}", "dim"))
    elif section == "Files":
        for field in ("WorkDir", "Command", "StdOut", "StdErr"):
            rows.append(row(f" {field:10} {details.get(field) or 'unavailable'}"))
        entries = getattr(getattr(app, "logs", None), "entries", []) if getattr(app, "log_job", None) == jid else []
        for entry in entries[:128]:
            rows.append(row(f" {entry.get('group', 'Logs')} / {entry.get('label', '')}: {entry.get('path', '')}", "cyan"))
        rows.append(row(" l / Enter opens this job's complete log browser.", "cyan"))
    else:
        citations = getattr(app, "research_evidence", {}) if state.get("evidence_job") == jid else {}
        for citation in list(citations.values())[:128]:
            rows.append(row(f" [{citation.get('id', '')}] {citation.get('source', '')}: {citation.get('text', '')}", "yellow"))
        if not citations:
            rows.append(row(" Open Evidence to collect bounded, cited observations for this job.", "dim"))
        rows.append(row(" e opens Evidence for this exact job.", "cyan"))
    return rows


def passport_rows(g, passport, differences=None, *, unchanged=False):
    row = lambda text, style="": [(clean(text, g.ascii), style)]
    rows = []
    if passport:
        rows.append(row(" Immutable run passport " + str(passport.get("id", "?")), "cyan+bold"))
        for key in ("captured_at", "workdir", "job_id", "script", "git", "resources", "parameters", "inputs", "environment", "modules", "container", "host"):
            rows.append(row(" " + key.replace("_", " ").title(), "bold"))
            value = passport.get(key)
            if isinstance(value, dict):
                for name, field in list(value.items())[:64]:
                    rows.append(row(f"   {name}: {_fmt(field)}", "dim" if field is None else ""))
            else:
                rows.append(row("   " + _fmt(value), "dim" if value is None else ""))
    if differences is not None:
        groups = defaultdict(list)
        for change in differences[:1024]:
            groups[change["path"].split("/")[1] if "/" in change["path"] else "run"].append(change)
        rows.append(row(f" {len(differences)} substantive changes", "yellow" if differences else "green"))
        for name, changes in groups.items():
            rows.append(row(f" {name.title()}  ({len(changes)} changed)", "cyan+bold"))
            for change in changes:
                rows.append(row(" " + change["path"], "bold"))
                left = _fmt(change.get("left")) if change.get("left_present", True) else "absent"
                right = _fmt(change.get("right")) if change.get("right_present", True) else "absent"
                rows.append(row("   Before  " + left, "red"))
                rows.append(row("   After   " + right, "green"))
        if not differences:
            rows.append(row(" No substantive differences between the two passports.", "green"))
    return rows


def _job_diff_rows(g, snap, app, width):
    state = initialize(app)
    ids = state.get("diff_ids", [])[:6]
    jobs = [app.job_record(jid, snap) for jid in ids]
    row = lambda text, style="": [(clean(text, g.ascii), style)]
    rows = [row(" Comparing " + ", ".join(ids), "cyan+bold"), row(" u shows / hides unchanged fields; sample curves align on first observed sample.", "dim")]
    fields = [("Name", lambda j: j.name), ("State", lambda j: j.state), ("Partition", lambda j: j.partition),
              ("CPUs", lambda j: j.cpus), ("GPUs", lambda j: j.gpus), ("Nodes", lambda j: j.nodes),
              ("Memory requested", lambda j: human(j.mem_bytes if hasattr(j, "mem_bytes") else j.req_mem) if (j.mem_bytes if hasattr(j, "mem_bytes") else j.req_mem) else None),
              ("Elapsed", lambda j: j.elapsed), ("Limit", lambda j: j.limit), ("Exit", lambda j: getattr(j, "exit", None))]
    for label, fn in fields:
        values = [fn(job) if job else None for job in jobs]
        changed = len({_fmt(v) for v in values}) > 1
        if changed or state.get("unchanged"):
            rows.append(row(" " + label + (" / changed" if changed else " / unchanged"), "yellow+bold" if changed else "dim"))
            for jid, value in zip(ids, values):
                rows.append(row(f"   {jid}: {_fmt(value)}", "" if changed else "dim"))
    all_series = {jid: _resource_series(app, jid) for jid in ids}
    for metric in ("CPU per core (%)", "Memory (GB)", "GPU utilization (%)"):
        pointsets = {jid: _points(series.get(metric, [])) for jid, series in all_series.items()}
        pointsets = {jid: points for jid, points in pointsets.items() if points}
        if not pointsets:
            continue
        rows.append(row(" " + metric + " / aligned measured curves", "cyan+bold"))
        finite = [p["value"] for points in pointsets.values() for p in points if p["value"] is not None]
        lo, hi = min([0.0] + finite), max(finite, default=1.0)
        span = max((points[-1]["t"] - points[0]["t"] for points in pointsets.values()), default=1.0)
        if not math.isfinite(span):
            span = 1.0
        for i, jid in enumerate(ids):
            points = pointsets.get(jid)
            if not points:
                rows.append(row(f" {jid}: no measured {metric} samples", "dim"))
                continue
            t0 = points[0]["t"]
            rows.extend(charts.braille_chart(g, [p["value"] for p in points], width, 3, lo=lo, hi=hi,
                                            title=jid, sample_times=[p["t"] - t0 for p in points],
                                            times=(0, span), elapsed=True, color=lambda _, i=i: COLORS[i % len(COLORS)]))
    if not any(all_series.values()):
        rows.append(row(" No resource samples observed for these jobs in this session. Accounting values remain visible above.", "dim"))
    return rows


def overlay(views, snap, app, width, height):
    state = initialize(app)
    if getattr(app, "mode", "main") != "analysis":
        return None
    g = views.g
    modal = state.get("modal", "")
    inner = max(1, min(160, width - 8))
    page = max(1, height - 6)
    row = lambda text, style="": [(clean(text, g.ascii), style)]
    if modal == "inspect":
        rows = _inspector_rows(g, snap, app, inner)
        title = "Job inspector / " + str(state.get("job", ""))
        footer = row(" Tab / arrows: section   Up / Down: scroll   l: logs   e: evidence   Esc: back", "dim")
    elif modal == "chart":
        series, source, _ = chart_data(app, snap)
        names = list(series)
        name = state.get("metric") if state.get("metric") in names else names[0] if names else ""
        state["metric"] = name
        rows = chart_rows(g, app, series.get(name, []), inner, max(1, min(20, page - 5)), name or "No metric samples", source)
        window = f" | window {state['window']:g}s" if state.get("window") else ""
        rows.append(row(f" Zoom x{state.get('zoom', 1):g} | pan {state.get('pan', 0):.0%}{window}", "cyan"))
        title, footer = "Chart inspector", row(" Arrows: sample  +/-: zoom  [ ]: pan  Tab: metric  Home/End  Esc: back", "dim")
    elif modal == "timeline":
        events = timeline_events(app, snap)
        state["cursor"] = max(0, min(max(0, len(events) - 1), state.get("cursor", 0)))
        rows = []
        for i, event in enumerate(events):
            selected = i == state["cursor"]
            rows.append(row(f" {'>' if selected else ' '} {i + 1:3} {_time(event['t'])} {event.get('kind', '')} {event.get('job') or ''}", "rev+bold" if selected else "cyan"))
            rows.append(row("      " + str(event.get("text", "")), "bold" if selected else "dim"))
        if not rows:
            rows = [row(" No timestamped events observed yet.", "dim")]
        state["scroll"] = max(0, state["cursor"] * 2 - page // 2)
        title, footer = "Observed event timeline", row(" Arrows: event  Enter: job / cited log  s: seek replay  Esc: back", "dim")
    elif modal == "diff":
        if state.get("diff_kind") == "passport":
            comparison = state.get("comparison", {})
            rows = passport_rows(g, comparison.get("left") if state.get("unchanged") else {}, comparison.get("differences", []))
            rows.insert(0, row(" Left " + str(comparison.get("left", {}).get("id", "?")) + " / Right " + str(comparison.get("right", {}).get("id", "?")), "cyan+bold"))
        else:
            rows = _job_diff_rows(g, snap, app, inner)
        title, footer = "Run comparison", row(" Up / Down: scroll   u: show / hide unchanged fields   Esc: back", "dim")
    else:
        series, _, _ = chart_data(app, snap)
        rows = [row(" Metric dashboard arrangement", "cyan+bold")]
        for i, name in enumerate(list(dict.fromkeys(state["order"] + list(series)))[:MAX_METRICS]):
            flags = [label for field, label in (("pinned", "pinned"), ("hidden", "hidden"), ("expanded", "expanded")) if name in state[field]]
            rows.append(row(f" {i + 1:2}. {name}  {', '.join(flags) or 'visible'}  {state['colors'].get(name, 'automatic color')}", "dim" if name in state["hidden"] else "cyan"))
        rows += [row(" :dashboard pin / hide / show / expand METRIC", "dim"), row(" :dashboard move METRIC POSITION | color METRIC cyan", "dim"), row(" :chart METRIC opens exact-sample inspection.", "dim")]
        rows.append(row(" :dashboard search TEXT filters visible cards; :dashboard search clears it.", "dim"))
        title, footer = "Dashboard", row(" Up / Down: scroll   Esc: back", "dim")
    state["row_count"] = len(rows)
    offset = max(0, min(state.get("scroll", 0), max(0, len(rows) - page)))
    state["scroll"] = offset
    rows = [L.clip_row(line, inner) for line in rows[offset:offset + page]] + [L.clip_row(footer, inner)]
    return L.box(g, rows, width, height, title, min_width=min(max(1, inner), 100))
