"""Explicit columns, field filters and named table views with stable job IDs."""
from __future__ import annotations

from dataclasses import replace
import copy
import re

from . import layout as L

MAX_VIEWS = 32
FIELDS = {"state", "partition", "tag", "name", "id"}
REQUIRED = {"id", "name", "st", "state"}


def initialize(app):
    app.table_state = {"hidden": {}, "facets": {}, "views": {}, "cursor": 0, "tab": "jobs", "groups": False, "collapsed": []}


def restore(app, data):
    if not isinstance(data, dict):
        return
    for tab in ("jobs", "history"):
        for key, check in (("hidden", _hidden), ("facets", _facets)):
            values = data.get(key, {})
            if isinstance(values, dict) and tab in values:
                try:
                    app.table_state[key][tab] = check(values[tab], tab)
                except ValueError:
                    pass
    views = data.get("views", {})
    if isinstance(views, dict):
        for name, value in list(views.items())[:MAX_VIEWS]:
            if not isinstance(name, str) or not re.fullmatch(r"[\w .-]{1,64}", name):
                continue
            try:
                app.table_state["views"][name] = _view(app, value)
            except ValueError:
                continue
    app.table_state["groups"] = data.get("groups") is True
    app.table_state["collapsed"] = [value for value in data.get("collapsed", [])[:256] if isinstance(value, str) and value.isdigit()] if isinstance(data.get("collapsed"), list) else []


def save(app):
    return {key: copy.deepcopy(app.table_state[key]) for key in ("hidden", "facets", "views", "groups", "collapsed")}


def command_names():
    return ["columns", "facet", "savedview", "jobgroups"]


def group_rows(app, rows):
    state = app.table_state
    if not state["groups"]:
        return rows
    groups, ordered = {}, []
    for item in rows:
        match = re.fullmatch(r"(\d+)_\d+", item["job"].id)
        base = match.group(1) if match else None
        if base:
            if base not in groups:
                groups[base] = []
                ordered.append((base, groups[base]))
            groups[base].append(item)
        else:
            ordered.append((None, [item]))
    result = []
    for base, items in ordered:
        if base and len(items) > 1:
            first = dict(items[0])
            first["info"] += f" | array {base}: {len(items)} observed tasks; " + ("Right expands" if base in state["collapsed"] else "Left collapses")
            result.append(first)
            if base not in state["collapsed"]:
                result.extend(items[1:])
        else:
            result.extend(items)
    return result


def definitions(tab):
    from .views import JOB_COLS, Views
    return JOB_COLS if tab == "jobs" else Views.FIN_COLS if tab == "history" else []


def _hidden(value, tab):
    available = {column.key for column in definitions(tab)}
    if (not isinstance(value, list) or len(value) > len(available) or
            any(not isinstance(key, str) or key not in available or key in REQUIRED for key in value)):
        raise ValueError("invalid hidden columns")
    return sorted(set(value))


def _facets(value, tab):
    if (not isinstance(value, dict) or len(value) > len(FIELDS) or
            any(key not in FIELDS or not isinstance(text, str) or len(text) > 256
                for key, text in value.items())):
        raise ValueError("invalid field filters")
    return {key: text for key, text in value.items() if text}


def _view(app, value):
    """Validate the complete restored view before changing any navigation."""
    from .views import SORTS
    if not isinstance(value, dict) or value.get("tab") not in ("jobs", "history"):
        raise ValueError("invalid table")
    tab = value["tab"]
    text, sort = value.get("filter", ""), value.get("sort", app.sort.get(tab))
    reverse, days = value.get("reverse", False), value.get("days", app.analytics_days_value())
    if (not isinstance(text, str) or len(text) > 256 or sort not in SORTS[tab] or
            not isinstance(reverse, bool) or isinstance(days, bool) or
            not isinstance(days, (int, float)) or days not in app.days_options):
        raise ValueError("invalid table settings")
    return {"tab": tab, "hidden": _hidden(value.get("hidden", []), tab),
            "facets": _facets(value.get("facets", {}), tab), "filter": text,
            "sort": sort, "reverse": reverse, "days": days}


def columns(app, tab, original):
    hidden = getattr(app, "table_state", {}).get("hidden", {}).get(tab, [])
    hidden = hidden if isinstance(hidden, list) else []
    key = app.sort.get(tab, "")
    mapping = {"state": "st" if tab == "jobs" else "state", "cpu_eff": "ce", "mem_eff": "me"}
    sorted_key = mapping.get(key, key)
    return [replace(column, title=column.title + (" v" if app.reverse.get(tab) else " ^"),
                    lo=max(column.lo, L.vlen(column.title) + 2), hi=max(column.hi, L.vlen(column.title) + 2))
            if column.key == sorted_key else column for column in original
            if column.key not in hidden or column.key in REQUIRED]


def fingerprint(app, tab):
    facets = getattr(app, "table_state", {}).get("facets", {}).get(tab, {})
    return tuple(sorted(facets.items())) if isinstance(facets, dict) else ()


def matches(app, tab, record, snap):
    facets = dict(fingerprint(app, tab))
    values = {"state": getattr(record, "state", ""), "partition": getattr(record, "partition", ""),
              "name": getattr(record, "name", ""), "id": getattr(record, "id", ""),
              "tag": " ".join(snap.get("tags", {}).get(record.id, {}).get("tags", []))}
    if record.id in snap.get("departed_jobs", {}):
        values["state"] = "ACCOUNTING"
    for field, expected in facets.items():
        actual = str(values.get(field, "")).casefold()
        choices = [part.casefold() for part in str(expected).split(",")]
        if field in ("state", "partition", "id"):
            if actual not in choices:
                return False
        elif field == "tag":
            if not any(choice in actual.split() for choice in choices):
                return False
        elif not any(choice in actual for choice in choices):
            return False
    return True


def chips(app, tab, width, ascii_=False):
    facets = fingerprint(app, tab)
    if not facets:
        return []
    from .research import clean
    value = clean(" Filters " + "  ".join(f"[{key}={value}]" for key, value in facets) + "  :facet clear", ascii_)
    return [(L.cut(value, width, ascii_), "accent")]


def run_command(app, args):
    if not args or args[0] not in command_names():
        return False
    command, values = args[0], list(args[1:])
    if command == "jobgroups":
        if values not in ([], ["on"], ["off"]):
            app.fail("Usage: jobgroups [on|off]")
        else:
            app.table_state["groups"] = not app.table_state["groups"] if not values else values == ["on"]
            app.say("Array task grouping " + ("on; Left/Right folds the selected array" if app.table_state["groups"] else "off"))
        return True
    tab = values.pop(0) if values and values[0] in ("jobs", "history") else app.tab
    if tab not in ("jobs", "history"):
        app.fail("Choose Jobs or History, or specify that table in the command")
        return True
    state = app.table_state
    if command == "columns":
        available = {column.key for column in definitions(tab)}
        if not values:
            state["tab"], state["cursor"], app.mode = tab, 0, "columns"
        elif values == ["reset"]:
            state["hidden"][tab] = []
            app.say(f"{tab} columns reset")
        elif len(values) >= 2 and values[0] in ("show", "hide"):
            requested = {part for value in values[1:] for part in value.split(",")}
            if not requested <= available or (values[0] == "hide" and requested & REQUIRED):
                app.fail("Unknown columns or required identity/state column; use :columns to browse")
            else:
                hidden = set(state["hidden"].get(tab, []))
                hidden = hidden | requested if values[0] == "hide" else hidden - requested
                state["hidden"][tab] = sorted(hidden)
                app.say(f"{tab} columns updated")
        else:
            app.fail("Usage: columns [jobs|history] [show|hide KEYS|reset]")
    elif command == "facet":
        if values == ["clear"]:
            state["facets"][tab] = {}
        else:
            parsed = dict(state["facets"].get(tab, {}))
            for value in values:
                field, separator, content = value.partition("=")
                if not separator or field not in FIELDS or len(content) > 256:
                    app.fail("Filters use state=FAILED,TIMEOUT partition=gpu tag=TAG name=TEXT id=ID")
                    return True
                if content:
                    parsed[field] = content
                else:
                    parsed.pop(field, None)
            state["facets"][tab] = parsed
        app.cursor[tab], app.top[tab] = 0, 0
        app.say(f"{tab} field filters updated")
    else:
        action = values[0] if values else "list"
        if action == "list":
            app.say("Saved views: " + (", ".join(sorted(state["views"])) or "none; savedview save NAME"))
        elif len(values) == 2 and action in ("save", "load", "delete"):
            name = values[1]
            if not re.fullmatch(r"[\w .-]{1,64}", name):
                app.fail("View names must be 1–64 letters, numbers, spaces, dots or hyphens")
            elif action == "save":
                if name not in state["views"] and len(state["views"]) >= MAX_VIEWS:
                    app.fail("At most 32 saved views; delete an unused view first")
                else:
                    state["views"][name] = {"tab": tab, "hidden": list(state["hidden"].get(tab, [])),
                        "facets": dict(state["facets"].get(tab, {})), "filter": app.filter,
                        "sort": app.sort.get(tab), "reverse": bool(app.reverse.get(tab)),
                        "days": app.analytics_days_value()}
                    app.say(f"Saved table view {name}")
            elif action == "delete":
                state["views"].pop(name, None)
                app.say(f"Deleted table view {name}")
            elif name not in state["views"]:
                app.fail("No saved view with that name")
            else:
                try:
                    view = _view(app, state["views"][name])
                except ValueError as exc:
                    app.fail(f"Saved view {name} is damaged: {exc}; delete it and save a new view")
                    return True
                target = view["tab"]
                app.enter_tab(target)
                state["hidden"][target] = view["hidden"]
                state["facets"][target] = view["facets"]
                app.filter, app.sort[target] = view["filter"], view["sort"]
                app.reverse[target] = view["reverse"]
                app.set_days(app.days_options.index(view["days"]))
                app.cursor[target], app.top[target] = 0, 0
                app.say(f"Loaded table view {name}")
        else:
            app.fail("Usage: savedview list|save NAME|load NAME|delete NAME")
    return True


def handle_key(app, key):
    if app.mode == "main" and app.tab == "jobs" and app.table_state["groups"] and key in ("left", "right"):
        match = re.fullmatch(r"(\d+)_\d+", app.selected_id or "")
        if match:
            collapsed = set(app.table_state["collapsed"])
            if key == "left":
                collapsed.add(match.group(1))
            else:
                collapsed.discard(match.group(1))
            app.table_state["collapsed"] = sorted(collapsed)[:256]
            return True
        return False
    if app.mode != "columns":
        return False
    state = app.table_state
    cols = definitions(state["tab"])
    if key in ("esc", "q", "enter"):
        app.mode = "main"
    elif key in ("up", "down", "home", "end"):
        step = {"up": -1, "down": 1, "home": -len(cols), "end": len(cols)}[key]
        state["cursor"] = max(0, min(len(cols) - 1, state["cursor"] + step))
    elif key == "space" and cols:
        column = cols[state["cursor"]]
        if column.key not in REQUIRED:
            hidden = set(state["hidden"].get(state["tab"], []))
            hidden.symmetric_difference_update({column.key})
            state["hidden"][state["tab"]] = sorted(hidden)
    return True


def overlay(views, snap, app, width, height):
    if app.mode != "columns":
        return None
    state = app.table_state
    cols = definitions(state["tab"])
    hidden = state["hidden"].get(state["tab"], [])
    cursor = state["cursor"]
    available = max(1, height - 5)
    start = max(0, cursor - available // 2)
    rows = [[(" Space show/hide | arrows move | Enter done", "dim")]]
    for index, column in enumerate(cols[start:start + available], start):
        required = " (required)" if column.key in REQUIRED else ""
        text = f" [{' ' if column.key in hidden else 'x'}] {column.title:16} {column.key}{required}"
        rows.append([(text, "sel" if index == cursor else "")])
    return L.box(views.g, rows, width, height, state["tab"].title() + " columns")
