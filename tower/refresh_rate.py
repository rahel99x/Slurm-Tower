"""Shared live update-rate preference with bounded, non-compounding cadences.

The slider expresses a requested speedup. Existing base intervals stay intact;
expensive scheduler probes, remote reads, and source error backoff keep their
own limits. The default 1x rate preserves every existing interval exactly.
"""
from __future__ import annotations

import math
import re

MIN_MULTIPLIER = 1
MAX_MULTIPLIER = 50
SOURCE_FLOORS = {"gpu": 5.0, "weather": 30.0, "budget": 30.0}
SOURCE_FLOOR = 0.5
LOCAL_FILE_FLOOR = 0.25
REMOTE_FILE_FLOOR = 1.5


def validate_multiplier(value):
    """Accept finite whole numbers from 1 to 50; reject bools and text."""
    if (type(value) not in (int, float) or not MIN_MULTIPLIER <= value <= MAX_MULTIPLIER
            or not math.isfinite(value) or value != int(value)):
        raise ValueError("polling_multiplier must be a whole number between 1 and 50")
    return int(value)


def _interval(base, value, floor):
    rate = validate_multiplier(value)
    if type(base) not in (int, float) or base < 0:
        raise ValueError("polling interval must be finite and non-negative")
    try:
        base = float(base)
    except OverflowError as exc:
        raise ValueError("polling interval must be finite and non-negative") from exc
    if not math.isfinite(base):
        raise ValueError("polling interval must be finite and non-negative")
    # Never slow down an existing explicit cadence, including zero intervals
    # used by one-shot callers. Changing speed never edits the base interval.
    return base if rate == 1 else max(min(base, floor), base / rate)


def source_interval(base, value, *, source=""):
    return _interval(base, value, SOURCE_FLOORS.get(source, SOURCE_FLOOR))


def file_interval(base, value, *, remote=False):
    return _interval(base, value, REMOTE_FILE_FLOOR if remote else LOCAL_FILE_FLOOR)


def multiplier(app):
    """Read the current preference without work, IO, or admission of tasks."""
    state = getattr(app, "refresh_rate_state", None)
    cfg = getattr(app, "cfg", None)
    value = state.get("multiplier", 1) if isinstance(state, dict) else (cfg.get("polling_multiplier", 1) if cfg else 1)
    try:
        return validate_multiplier(value)
    except (TypeError, ValueError, OverflowError):
        return 1


def _sync(app, value):
    cfg = getattr(app, "cfg", None)
    if cfg is not None:
        setter = getattr(cfg, "set", None)
        if callable(setter):
            setter("polling_multiplier", value)
        elif isinstance(cfg, dict):
            cfg["polling_multiplier"] = value
    for name in ("sampler", "research", "logs"):
        target = getattr(app, name, None)
        if target is None:
            continue
        setter = getattr(target, "set_polling_multiplier", None)
        if callable(setter):
            setter(value)
        else:
            target.polling_multiplier = value
    catalog = getattr(getattr(app, "logs", None), "catalog", None)
    if catalog is not None:
        catalog.polling_multiplier = value


def initialize(app):
    if not isinstance(getattr(app, "refresh_rate_state", None), dict):
        cfg = getattr(app, "cfg", None)
        value = validate_multiplier(cfg.get("polling_multiplier", 1) if cfg else 1)
        app.refresh_rate_state = {"multiplier": value}
        _sync(app, value)
    return app.refresh_rate_state


def set_multiplier(app, value):
    value = validate_multiplier(value)
    state = initialize(app)
    state["multiplier"] = value
    _sync(app, value)
    return value


def adjust(app, delta):
    if type(delta) not in (int, float) or (type(delta) is float and not math.isfinite(delta)) or delta != int(delta):
        raise ValueError("rate adjustment must be a finite whole number")
    return set_multiplier(app, max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, multiplier(app) + int(delta))))


def restore(app, data):
    initialize(app)
    if not isinstance(data, dict) or "multiplier" not in data:
        return
    try:
        value = validate_multiplier(data["multiplier"])
    except (TypeError, ValueError, OverflowError):
        return
    set_multiplier(app, value)


def save(app):
    return {"multiplier": multiplier(app)}


def cadence(app, source, base=None):
    """Return the source's current interval, including dynamic plugin settings."""
    sampler = getattr(app, "sampler", None)
    effective = getattr(sampler, "effective_interval", None)
    if callable(effective):
        return effective(source)
    intervals = getattr(sampler, "intervals", None)
    if isinstance(intervals, dict) and source in intervals:
        base = intervals[source]
    elif base is None:
        cfg = getattr(app, "cfg", None)
        configured = cfg.get("intervals", {}) if cfg else {}
        base = configured.get(source, 0)
    return source_interval(base, multiplier(app), source=source)


def cadence_summary(app):
    from .metric_sampling import format_interval
    return (f"Jobs poll every {format_interval(cadence(app, 'jobs'), ascii_=True)}; "
            "source floors and error backoff still apply")


def command_names():
    return ["rate"]


def execute(app, cmd, args):
    if cmd != "rate":
        return False
    try:
        if not args:
            pass
        elif args == ["reset"]:
            set_multiplier(app, 1)
        elif len(args) == 1 and isinstance(args[0], str) and re.fullmatch(r"[0-9]{1,2}", args[0]):
            set_multiplier(app, int(args[0]))
        else:
            raise ValueError("rate [1..50|reset]")
        app.say(cadence_summary(app))
    except (TypeError, ValueError, OverflowError) as exc:
        app.fail(str(exc))
    return True


def run_command(app, args):
    return bool(args) and execute(app, args[0], args[1:])


def handle_key(app, key):
    return False


def handle_mouse(app, y, x, button="left", shift=False):
    return False


def overlay(views, snap, app, width, height):
    return None
