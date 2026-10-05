"""Terminal log presentation and job-scoped evidence drilldown.

File metadata, previews and alternate views use ResearchHub's one worker.
Rendering consumes published snapshots only. Presentation never changes raw
LogSession bytes or the source selected by copy/yank commands.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
import json
import time

from . import layout as L
from .research import clean
from .remote import LocalFiles

META_TTL = 30.0
MAX_META_FILES = 32
PREVIEW_BYTES = 8192
VIEW_BYTES = 65536
MAX_VIEW_ROWS = 240


def initialize(app):
    app.log_workbench_state = dict(view="plain", pan=0, scroll=0, collapsed=[],
                                   current_group="", preview=False, cache=OrderedDict(),
                                   pending=None, generation=0, citation=None,
                                   pan_cache=OrderedDict(), pan_context=None)


def _state(app):
    if not isinstance(getattr(app, "log_workbench_state", None), dict):
        initialize(app)
    return app.log_workbench_state


def restore(app, state):
    target = _state(app)
    state = state if isinstance(state, dict) else {}
    if state.get("view") in ("plain", "json", "split"):
        target["view"] = state["view"]
    pan = state.get("pan", 0)
    target["pan"] = min(100000, max(0, pan)) if type(pan) is int else 0
    collapsed = state.get("collapsed", [])
    if isinstance(collapsed, list):
        target["collapsed"] = [v for v in collapsed[:256] if isinstance(v, str) and len(v) <= 160 and v.isprintable()]
    target["preview"] = state.get("preview") is True


def save(app):
    state = _state(app)
    return {key: state[key] for key in ("view", "pan", "collapsed", "preview")}


def command_names():
    return ["logview", "logpan", "loggroup", "logpreview"]


def visible_entries(app, entries):
    """Filter collapsed file groups without changing their catalog identities."""
    collapsed = set(_state(app)["collapsed"])
    return [entry for entry in entries if entry.get("group", "Application") not in collapsed]


def _entries(app):
    entries = list(getattr(app.logs, "entries", []))
    store = getattr(app, "store", None)
    binding = (getattr(app, "project_state", {}) or {}).get("binding")
    if store is not None and hasattr(app, "log_target") and not binding:
        from .views import stdout_path
        snap = store.snapshot()
        job = app.log_target(snap)
        if job is not None:
            details = snap.get("details", {}).get(job.id, {})
            for key, field in (("stdout", "StdOut"), ("stderr", "StdErr")):
                declared = details.get(field)
                if not isinstance(declared, str) or not declared.strip() or declared.strip().casefold() in {"(null)", "n/a", "unknown", "none"}:
                    # Expanding an explicit scheduler path is pure. Guessing a
                    # local fallback probes the filesystem and belongs to the
                    # catalog worker, never to a redraw of cached entries.
                    continue
                path = stdout_path(job, details, _backend(app), field)
                if path and not any(entry["path"] == path for entry in entries):
                    entries.append(dict(id="scheduler." + key, path=path, label=key, group="Scheduler", source="scheduler"))
    if app.logs.entry and not any(e["path"] == app.logs.entry["path"] for e in entries):
        entries.insert(0, dict(app.logs.entry))
    return entries


def _selected_group(app):
    state = _state(app)
    entries = app.log_entries() if hasattr(app, "log_entries") else visible_entries(app, _entries(app))
    index = max(0, min(app.logs.browser_cursor, len(entries) - 1)) if entries else 0
    return state["current_group"] or (entries[index].get("group", "Application") if entries else "")


def _toggle_group(app, group):
    state = _state(app)
    if not group:
        app.fail("Select a log group or use :loggroup GROUP.")
        return
    collapsed = state["collapsed"]
    if group in collapsed:
        collapsed.remove(group)
        message = "expanded"
    else:
        collapsed.append(group)
        message = "collapsed"
    state["current_group"] = group
    app.logs.browser_cursor, app.logs.browser_top = 0, 0
    app.say(f"{message} {group}; :loggroup all expands every group")


def run_command(app, args):
    if not args or args[0] not in command_names():
        return False
    state, command, values = _state(app), args[0], args[1:]
    try:
        if command == "logview":
            if len(values) != 1 or values[0] not in ("plain", "json", "split"):
                raise ValueError("logview plain|json|split")
            state["view"], state["scroll"] = values[0], 0
            app.tab = "log"
            app.say("Log view " + values[0] + "; Esc returns to original lines")
        elif command == "logpan":
            if len(values) != 1 or not values[0].isascii():
                raise ValueError("logpan COLUMNS (0 resets; use +/- to move)")
            number = int(values[0])
            state["pan"] = max(0, min(100000, state["pan"] + number if values[0].startswith(("+", "-")) else number))
            app.logs.wrap = False
            app.say(f"Horizontal offset {state['pan']} display columns")
        elif command == "loggroup":
            if values == ["all"]:
                state["collapsed"], state["current_group"] = [], ""
                app.say("Every log group expanded")
            else:
                _toggle_group(app, " ".join(values) if values else _selected_group(app))
        elif command == "logpreview":
            if values and values not in (["on"], ["off"]):
                raise ValueError("logpreview [on|off]")
            state["preview"] = values == ["on"] if values else not state["preview"]
            state["generation"] += 1
            app.say("Log previews " + ("on" if state["preview"] else "off"))
    except (ValueError, TypeError) as exc:
        app.fail(str(exc))
    return True


def handle_key(app, key):
    if app.tab != "log" or app.mode != "main":
        return False
    state = _state(app)
    if getattr(app, "keymap", {}).get(key) == "refresh":
        state["cache"].clear()
        state["generation"] += 1
    if app.logs.browser:
        if key in ("up", "down", "pgup", "pgdn", "home", "end"):
            state["current_group"] = ""
        if key == "space":
            _toggle_group(app, _selected_group(app))
            return True
        return False
    if state["view"] != "plain":
        if key == "esc":
            state["view"], state["scroll"] = "plain", 0
            app.say("Original log lines")
            return True
        if key in ("up", "down", "pgup", "pgdn", "home", "end"):
            step = {"up": -1, "down": 1, "pgup": -10, "pgdn": 10, "home": -MAX_VIEW_ROWS, "end": MAX_VIEW_ROWS}[key]
            state["scroll"] = max(0, min(MAX_VIEW_ROWS, state["scroll"] + step))
            return True
        if key in ("[", "]") and state["view"] == "split":
            entries = _split_entries(app)
            if len(entries) == 2:
                entry = entries[0 if key == "[" else 1]
                app.logs.clear_selection(reset_cursor=True)
                app.log_selection_expected = False
                app.logs.entry, app.logs.path, app.logs.top = dict(entry), "", None
                app.say("Copy source: " + entry.get("label", entry["path"]))
            return True
    if key in ("left", "right"):
        state["pan"] = max(0, min(100000, state["pan"] + (-8 if key == "left" else 8)))
        app.logs.wrap = False
        return True
    return False


def display_line(app, line):
    """Pan by terminal columns; never split wide characters or alter raw bytes."""
    state = _state(app)
    offset = state["pan"]
    if not offset:
        return line
    context = (app.logs.path, app.logs._buffer_token, offset)
    if state["pan_context"] != context:
        state["pan_context"] = context
        state["pan_cache"].clear()
    cached = state["pan_cache"].get(id(line))
    budget = max(1024, min(VIEW_BYTES, (getattr(app, "width", 120) + 16) * max(1, app.logs.page) * 2))
    if cached and cached[0] is line:
        return line[cached[1]:cached[1] + budget]
    used, index = 0, 0
    for index, char in enumerate(line):
        used += L.vlen(char)
        if used >= offset:
            break
    position = index + 1 if line else 0
    state["pan_cache"][id(line)] = (line, position)
    state["pan_cache"].move_to_end(id(line))
    while len(state["pan_cache"]) > 256:
        state["pan_cache"].popitem(last=False)
    return line[position:position + budget]


def status_label(app):
    state = _state(app)
    return f"pan {state['pan']} columns (Left/Right)" if state["pan"] else ""


def _backend(app):
    return app.files or app.logs.files or LocalFiles()


def _snapshot_tail(files, path, limit):
    """Read a stable exact backend; no local fallback for remote errors."""
    before = files.snapshot_stat(path) if hasattr(files, "snapshot_stat") else None
    if type(files) is LocalFiles:
        from .artifacts import read_local_tail
        raw, size, stable = read_local_tail(path, max_bytes=limit)
        if not stable:
            raise ValueError("File changed during inspection; refresh to retry")
    else:
        raw, size = files.tail(path, limit)
    if not isinstance(raw, bytes) or len(raw) > limit or type(size) is not int or size < len(raw):
        raise ValueError("Invalid or oversized file adapter reply")
    after = files.snapshot_stat(path) if before is not None else None
    if before is not None and before != after:
        raise ValueError("File changed during inspection; refresh to retry")
    truncated = size > len(raw)
    if truncated:
        newline = raw.find(b"\n")
        raw = raw[newline + 1:] if newline >= 0 else b""
    return raw, size, before, truncated


def _request(app, key, fn):
    """Coalesce presentation requests into the shared existing single worker."""
    state = _state(app)
    cached = state["cache"].get(key)
    if cached and time.monotonic() - cached[0] < META_TTL:
        state["cache"].move_to_end(key)
        return cached[1]
    hub = getattr(app, "research", None)
    if state["pending"] is not None or hub is None:
        return cached[1] if cached else None
    token = (state["generation"], key)
    state["pending"] = token
    def complete(result):
        current = _state(app)
        if current["pending"] == token:
            current["pending"] = None
        if token[0] != current["generation"]:
            return
        value = {"error": clean(result)} if isinstance(result, Exception) else result
        current["cache"][key] = (time.monotonic(), value)
        current["cache"].move_to_end(key)
        while len(current["cache"]) > 8:
            current["cache"].popitem(last=False)
    try:
        admitted = hub.start_task(fn, complete)
    except Exception:
        state["pending"] = None
        raise
    if not admitted:
        state["pending"] = None
    return cached[1] if cached else None


def _metadata(app, entries):
    state, files = _state(app), _backend(app)
    selected = app.log_entries() if hasattr(app, "log_entries") else entries
    cursor = max(0, min(app.logs.browser_cursor, len(selected) - 1)) if selected else 0
    selected_path = selected[cursor]["path"] if selected else ""
    ordered = sorted(entries, key=lambda entry: entry["path"] != selected_path)[:MAX_META_FILES]
    paths = tuple(sorted(entry["path"] for entry in ordered))
    preview = selected_path if state["preview"] else ""
    key = ("meta", id(files), paths, preview)
    def read():
        values = {}
        for path in paths:
            try:
                meta = files.snapshot_stat(path) if hasattr(files, "snapshot_stat") else {"size": files.stat(path)[0]}
                item = dict(meta)
                if path == preview:
                    raw, size, identity, truncated = _snapshot_tail(files, path, PREVIEW_BYTES)
                    item.update(preview=[clean(line, limit=500) for line in raw.decode("utf-8", "replace").splitlines()[-8:]],
                                truncated=truncated, size=size, file_identity=identity)
                values[path] = item
            except (OSError, ValueError, TypeError) as exc:
                values[path] = {"error": clean(exc)}
        return {"files": values, "omitted": max(0, len(entries) - len(paths))}
    return _request(app, key, read)


def _size(value):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024


def _updated(meta):
    value = meta.get("updated")
    if isinstance(value, (tuple, list)) and value:
        if isinstance(value[0], int):
            try:
                return datetime.fromtimestamp(value[0] / 1e9).strftime("%m-%d %H:%M")
            except (ValueError, OverflowError, OSError):
                return ""
        if isinstance(value[0], str):
            return value[0][:19]
    return ""


def render_browser(views, snap, app, width, height, legacy_rows, hits):
    """A grouped catalog with cached metadata, expandable previews and hit maps."""
    entries = _entries(app)
    if not entries:
        return legacy_rows, hits
    state, glyphs = _state(app), views.g
    data = _metadata(app, entries) or {}
    files = data.get("files", {})
    filtered = [entry for entry in entries if not app.logs.file_filter or any(app.logs.file_filter.casefold() in str(entry.get(k, "")).casefold() for k in ("label", "group", "path", "description"))]
    selected_entries = app.log_entries() if hasattr(app, "log_entries") else visible_entries(app, filtered)
    cursor = max(0, min(app.logs.browser_cursor, len(selected_entries) - 1)) if selected_entries else 0
    selected_id = selected_entries[cursor]["id"] if selected_entries else None
    grouped = OrderedDict()
    for entry in filtered:
        grouped.setdefault(entry.get("group", "Application"), []).append(entry)
    title = legacy_rows[0] if legacy_rows else L.rule(glyphs, width, "log files")
    rows = [title, [(f" {len(filtered)} files  Space folds group  :loggroup all expands  :logpreview toggles preview", "dim")]]
    warnings = [row for row in legacy_rows[1:5] if any("yellow" in style for _, style in row)]
    rows.extend(warnings[:2])
    if data.get("omitted"):
        rows.append([(f" Metadata inspects at most {MAX_META_FILES} files, selected first; {data['omitted']} omitted.", "yellow")])
    body, mapped, selected_row = [], [], 0
    for group, items in grouped.items():
        collapsed = group in state["collapsed"]
        indicator = ">" if collapsed else "v" if glyphs.ascii else "▾"
        mapped.append((len(body), "log_group", group))
        body.append([(" " + clean(f"{indicator} {group} ({len(items)})", glyphs.ascii), "cyan+bold")])
        if collapsed:
            continue
        for entry in items:
            selected = entry["id"] == selected_id
            if selected:
                selected_row = len(body)
            meta = files.get(entry["path"], {})
            suffix = " | " + clean(meta["error"], glyphs.ascii, 100) if meta.get("error") else " | " + _size(meta["size"]) + " " + _updated(meta) if type(meta.get("size")) is int else " | metadata pending"
            mapped.append((len(body), "log_file", entry["id"]))
            body.append([("   " + (glyphs.cursor if selected else " ") + " " + clean(entry.get("label", entry["path"]), glyphs.ascii) + suffix, "rev+bold" if selected else "")])
            mapped.append((len(body), "log_file", entry["id"]))
            body.append([("     " + clean(entry["path"], glyphs.ascii), "dim")])
            if selected and state["preview"]:
                for line in meta.get("preview", []):
                    body.append([("       " + clean(line, glyphs.ascii), "dim")])
                if meta.get("truncated"):
                    body.append([("       Preview is a bounded tail; open the file for the original view.", "yellow")])
    available = len(body) if height is None else max(1, height - len(rows))
    top = max(0, min(app.logs.browser_top, max(0, len(body) - available)))
    if selected_row < top:
        top = selected_row
    elif selected_row >= top + available:
        top = max(0, selected_row - available + 1)
    app.logs.browser_top, app.logs.browser_page = top, max(1, available // 2)
    prefix = len(rows)
    return [L.clip_row(row, width) for row in rows + body[top:top + available]], [(y - top + prefix, kind, key) for y, kind, key in mapped if top <= y < top + available]


def _split_entries(app):
    entries = _entries(app)
    out = next((entry for entry in entries if entry.get("id") == "scheduler.stdout" or entry.get("role") == "stdout" or entry.get("label") == "stdout"), None)
    err = next((entry for entry in entries if entry.get("id") == "scheduler.stderr" or entry.get("role") == "stderr" or entry.get("label") == "stderr"), None)
    if out and err and out["path"] != err["path"]:
        return [out, err]
    selected = app.logs.entry or next((entry for entry in entries if entry["path"] == app.logs.path), None)
    result = [selected] if selected else []
    result += [entry for entry in entries if not selected or entry["path"] != selected["path"]]
    return result[:2]


def _alternate(app):
    state, files = _state(app), _backend(app)
    view = state["view"]
    entries = _split_entries(app) if view == "split" else [dict(path=app.logs.path, label=(app.logs.entry or {}).get("label", "selected log"))] if app.logs.path else []
    key = ("alternate", id(files), view, tuple(entry["path"] for entry in entries))
    def read():
        sources = []
        for entry in entries:
            path = entry["path"]
            try:
                raw, size, identity, truncated = _snapshot_tail(files, path, VIEW_BYTES)
                all_lines = raw.decode("utf-8", "replace").splitlines()
                line_offset = max(0, len(all_lines) - MAX_VIEW_ROWS)
                lines = all_lines[-MAX_VIEW_ROWS:]
                if view == "json":
                    formatted = []
                    for index, line in enumerate(lines):
                        if len(line) <= 8192:
                            try:
                                value = json.loads(line)
                                pending = [(value, 0)]
                                nodes = 0
                                while pending:
                                    item, depth = pending.pop()
                                    nodes += 1
                                    if nodes > 2048 or depth > 24:
                                        raise ValueError("JSON preview nesting/collection bound")
                                    if isinstance(item, dict):
                                        pending.extend((child, depth + 1) for child in item.values())
                                    elif isinstance(item, list):
                                        pending.extend((child, depth + 1) for child in item)
                                pretty = json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False)
                                formatted.extend(f"L{line_offset + index + 1} {piece}" for piece in pretty.splitlines()[:32])
                                continue
                            except (ValueError, RecursionError, OverflowError):
                                pass
                        formatted.append(f"L{line_offset + index + 1} {clean(line, limit=8192)}")
                    lines = formatted[:MAX_VIEW_ROWS]
                sources.append(dict(path=path, label=entry.get("label", path), lines=lines, size=size,
                                    truncated=truncated, omitted_lines=line_offset, file_identity=identity))
            except (OSError, ValueError, TypeError) as exc:
                sources.append(dict(path=path, label=entry.get("label", path), lines=[], error=clean(exc)))
        return {"sources": sources}
    return _request(app, key, read)


def overlay(views, snap, app, width, height):
    state = _state(app)
    if app.tab != "log" or app.mode != "main" or app.logs.browser or state["view"] == "plain":
        return None
    data = _alternate(app)
    rows = [[(" Esc original view | arrows scroll/pan | Y copies current source file", "dim")],
            [(" Copy/yank preserves original bytes; formatted panels are presentation only.", "dim")]]
    if data is None:
        rows.append([(" Waiting for the shared background reader.", "dim")])
    elif data.get("error"):
        rows.append([(" " + clean(data["error"], views.g.ascii), "red")])
    else:
        sources = data.get("sources", [])
        if not sources:
            rows.append([(" Open a job log first; split view needs two registered files.", "yellow")])
        elif state["view"] == "split" and len(sources) == 2:
            rows.append([(" [ selects left copy source | ] selects right copy source", "cyan")])
            half = max(1, (width - 9) // 2)
            sep = " | " if views.g.ascii else " │ "
            rows.append([(L.pad(L.cut(clean(sources[0]["label"], views.g.ascii), half, views.g.ascii), half) + sep + L.cut(clean(sources[1]["label"], views.g.ascii), half, views.g.ascii), "cyan+bold")])
            for item in sources:
                if item.get("error") or item.get("truncated"):
                    rows.append([(clean(item.get("error") or f"{item['label']}: bounded tail; line numbers are relative", views.g.ascii), "yellow")])
            count = max(len(item["lines"]) for item in sources)
            state["scroll"] = min(state["scroll"], max(0, count - max(1, height - len(rows) - 5)))
            for i in range(state["scroll"], min(count, state["scroll"] + max(1, height - len(rows) - 5))):
                columns = [display_line(app, clean(item["lines"][i], views.g.ascii, VIEW_BYTES)) if i < len(item["lines"]) else "" for item in sources]
                rows.append([(L.pad(L.cut(columns[0], half, views.g.ascii), half) + sep + L.cut(columns[1], half, views.g.ascii), "")])
        else:
            item = sources[0]
            if state["view"] == "split":
                rows.append([(" Only one source is available. Register additional logs or refresh scheduler paths for a pair.", "yellow")])
            rows.append([(" " + clean(item["path"], views.g.ascii), "cyan+bold")])
            if item.get("error"):
                rows.append([(" " + item["error"], "red")])
            if item.get("truncated"):
                rows.append([(" Bounded tail; L numbers are relative to the inspected window.", "yellow")])
            elif item.get("omitted_lines"):
                rows.append([(f" Displaying the last {MAX_VIEW_ROWS} original lines; {item['omitted_lines']} preceding lines omitted.", "yellow")])
            state["scroll"] = min(state["scroll"], max(0, len(item["lines"]) - max(1, height - len(rows) - 5)))
            for line in item["lines"][state["scroll"]:state["scroll"] + max(1, height - len(rows) - 5)]:
                rows.append([(" " + display_line(app, clean(line, views.g.ascii, VIEW_BYTES)), "")])
    return L.box(views.g, rows, width, height, "Log workbench / " + state["view"], min_width=max(1, width - 4))


def open_citation(app, citation):
    """Open only an explicitly cited log source, then position cached raw lines."""
    if not isinstance(citation, dict) or not citation.get("path"):
        app.say("This citation describes a scheduler/event observation, not a log file.")
        return False
    path = citation["path"]
    if not isinstance(path, str) or not path or len(path) > 4096 or not path.isprintable():
        app.fail("Citation path is invalid; refresh Evidence.")
        return False
    jid = citation.get("job") or getattr(app, "research_job_id", None) or getattr(app, "selected_id", None)
    if jid and hasattr(app, "open_log"):
        app.open_log(jid)
        if app.tab != "log":
            return False
    app.logs.clear_selection(reset_cursor=True)
    app.log_selection_expected = False
    app.logs.entry = dict(id="citation." + citation.get("id", "source"), path=path,
                          label=citation.get("source", "Evidence log"), group="Evidence", source="citation")
    app.logs.browser, app.logs.browse_return, app.logs.path, app.logs.top = False, True, "", None
    state = _state(app)
    state["view"], state["citation"] = "plain", dict(citation)
    app.tab = "log"
    app.say("Opening cited source; Esc returns to its log catalog")
    return True


def apply_citation(app, buf):
    """Called after the existing log reader; performs no additional file I/O."""
    state = _state(app)
    citation = state.get("citation")
    if not citation or buf is None or buf.error:
        return
    state["citation"] = None
    metadata = citation.get("file_identity")
    if isinstance(metadata, dict) and metadata.get("ident") is not None and tuple(metadata["ident"]) != tuple(buf.ident or ()):
        app.fail("Cited log was replaced after inspection; refresh Evidence before following this location.")
        return
    index = None
    number = citation.get("line")
    if citation.get("line_basis") == "original" and not buf.skipped_bytes and type(number) is int:
        index = number - 1
    else:
        target = citation.get("excerpt_line", "")
        if target:
            # Search a bounded original prefix; disambiguate repeated messages
            # by taking the latest retained match from this inspected tail.
            target = target.replace("\t", "    ")
            if isinstance(metadata, dict) and type(metadata.get("size")) is int and metadata["size"] != buf.size:
                app.say("Cited log changed after inspection; its exact file is open. Refresh Evidence to locate the cited occurrence.")
                return
            distance = citation.get("tail_distance")
            if type(distance) is int and 0 <= distance < buf.total:
                candidate = buf.total - distance - 1
                line = buf.lines[candidate] if candidate < len(buf.lines) else buf.partial
                if line.startswith(target):
                    index = candidate
            if index is None:
                matches = []
                for i in range(max(0, buf.total - 1200), buf.total):
                    line = buf.lines[i] if i < len(buf.lines) else buf.partial
                    if line.startswith(target):
                        matches.append(i)
                if len(matches) == 1:
                    index = matches[0]
    if index is None or index < 0 or index >= buf.total:
        app.say("Citation is outside the retained log window or changed; the exact source file is open.")
        return
    app.logs.goto(index, buf)
    app.logs.match = index
    app.say(f"Cited {citation.get('id', 'source')} at retained line {index + 1}; original bytes remain selectable")
