"""Cached project/run picker and declared artifact explorer for the terminal UI."""
from __future__ import annotations

import os

from . import layout as L, projects, artifact_pages
from .log_presentation import json_page
from .research import clean

MODES = {"project_runs", "project_outputs", "project_preview"}


def initialize(app):
    if not isinstance(getattr(app, "project_state", None), dict):
        app.project_state = {}
    state = app.project_state
    defaults = {"root": "", "runs": [], "warnings": [], "run_warnings": [], "binding": None, "logs": [], "status": "empty", "summary": "Choose a project with :project PATH",
                "generation": 0, "busy": False, "run_cursor": 0, "run_top": 0, "output_cursor": 0, "output_top": 0, "filter": "", "filtering": False,
                "collapsed": [], "tree": None, "preview": None, "preview_scroll": 0, "restore_run_id": "", "notices_open": False, "notices_scroll": 0,
                "preview_node": None, "preview_pages": [(0, 0)], "preview_page": 0, "preview_columns": None,
                "preview_sort": None, "preview_column": 0, "preview_collapsed": [], "preview_format": None}
    for key, value in defaults.items():
        state.setdefault(key, value)
    return state


def restore(app, data):
    state = initialize(app)
    if not isinstance(data, dict):
        return
    root, run_id = data.get("project_root", ""), data.get("run_id", "")
    if isinstance(root, str) and 0 < len(root) <= 4096 and all(ch.isprintable() for ch in root):
        state["root"] = root
        state["summary"] = "Saved project; :runs reloads and revalidates its inventories"
    if isinstance(run_id, str) and projects._IDENT.fullmatch(run_id):
        state["restore_run_id"] = run_id


def save(app):
    state = initialize(app)
    binding = state.get("binding") or {}
    return {"project_root": state.get("root", ""), "run_id": binding.get("run_id", state.get("restore_run_id", ""))}


def selected_binding(app):
    value = initialize(app).get("binding")
    return value if isinstance(value, dict) else None


def log_entries(app):
    return list(initialize(app).get("logs", []))


def resolve_log_entry(app):
    """Resolve the chosen run's current exact stream before drawing or copying."""
    binding = selected_binding(app)
    if not binding:
        return None

    def selected(entry):
        role = entry.get("role")
        if role not in ("stdout", "stderr"):
            role = next((name for name in ("stderr", "stdout") if binding.get(name) and binding[name] == entry.get("path")), role)
        if role in ("stdout", "stderr"):
            app.logs.which = "err" if role == "stderr" else "out"
        return dict(entry)

    explicit = app.logs.entry
    if isinstance(explicit, dict) and explicit.get("path") and explicit.get("run_id", binding["run_id"]) == binding["run_id"]:
        return selected(explicit)
    entries = log_entries(app)
    if app.logs.file_index > 0 and entries:
        return selected(entries[(app.logs.file_index - 1) % len(entries)])
    role = "stderr" if app.logs.which == "err" else "stdout"
    path = binding.get(role, "")
    if path:
        existing = next((entry for entry in entries if entry.get("path") == path), None)
        return selected(existing) if existing else {"id": "project." + role, "path": path, "label": role, "group": "Run streams", "role": role,
                                              "source": "project", "run_id": binding["run_id"], "job_id": binding.get("job_id")}
    # Absence of a stderr declaration cannot turn into an unrelated stdout copy.
    return selected(entries[0]) if role == "stdout" and entries else None


def cycle_log_entry(app):
    """Move through the cached declarations without discovery or source reads."""
    if not selected_binding(app):
        return None
    entries = log_entries(app)
    if not entries:
        return None
    current = resolve_log_entry(app)
    current_index = next((index for index, entry in enumerate(entries) if current and entry.get("path") == current.get("path")), -1)
    chosen = dict(entries[(current_index + 1) % len(entries)])
    from .log_tools import before_source_change
    before_source_change(app)
    app.logs.entry, app.logs.file_index = chosen, 0
    if chosen.get("role") in ("stdout", "stderr"):
        app.logs.which = "err" if chosen["role"] == "stderr" else "out"
    app.logs.browser, app.logs.browse_return = False, False
    app.logs.path, app.logs.top, app.logs.match, app.logs.last_bookmark = "", None, None, None
    app.logs._buffer_token = None
    app.logs.clear_selection(reset_cursor=True)
    app.log_selection_expected, app.log_render_token = False, None
    return chosen


def clear_binding(app):
    """Leave the chosen run without losing the project inventory or manual paths."""
    state = initialize(app)
    backup = state.pop("binding_backup", None)
    if backup is not None and app.research is not None:
        app.research.configure(**backup["settings"])
        app.research.passport, app.research.passport_diff = backup["passport_record"], backup["passport_diff"]
        app.cfg["logs"]["manifest_file"] = backup["log_manifest"]
    if state.get("binding") or backup is not None:
        from .log_tools import before_source_change
        before_source_change(app)
        state.update(binding=None, logs=[], run_warnings=[], tree=None, preview=None, restore_run_id="")
        app.research_job_id, app.log_job, app.log_record = None, None, None
        if app.research is not None and backup is None:
            app.research.passport, app.research.passport_diff = None, None
        app.logs.entry, app.logs.entries = None, []
        app.logs.path, app.logs.top, app.logs.match, app.logs.last_bookmark = "", None, None, None
        app.logs._buffer_token = None
        app.logs.candidates.clear()
        app.logs.clear_selection(reset_cursor=True)
        app.log_selection_expected = False
    if state["busy"]:
        state["generation"] += 1
        state["busy"] = False


def command_names():
    return ["project", "runs", "run", "outputs", "artifact"]


def _hub(app):
    if app.research is None:
        from .research import ResearchHub
        app.research = ResearchHub(app.cfg, files=getattr(app, "files", None))
    return app.research


def _task(app, title, worker, complete, failed=None):
    state = initialize(app)
    hub = _hub(app)
    if state["busy"]:
        app.fail("A project read is already running; wait for its result")
        return False
    token = state["generation"] + 1
    state["generation"], state["busy"] = token, True

    def finished(value):
        if token != state["generation"]:
            return
        state["busy"] = False
        if isinstance(value, Exception):
            if failed is not None:
                failed()
            state["summary"] = f"{title}: {clean(value)}"
            app.fail(state["summary"])
            return
        complete(value)

    if not hub.start_task(worker, finished):
        state["busy"] = False
        app.fail("The background reader is busy; retry this project command shortly")
        return False
    app.say(title + " in the background")
    return True


def _refresh_runs(app, root):
    state = initialize(app)
    hub = _hub(app)

    def complete(value):
        previous = state.get("binding") or {}
        same_root = value["root"] == state.get("root")
        state.update(root=value["root"], runs=value["runs"], warnings=value["warnings"], status=value["status"], summary=value["summary"], limited=value["limited"])
        if not same_root:
            if previous:
                clear_binding(app)
            state.update(binding=None, logs=[], run_warnings=[], tree=None, preview=None, run_cursor=0, run_top=0, filter="", collapsed=[])
        wanted = previous.get("run_id") or state.get("restore_run_id") if same_root else None
        state["run_cursor"] = next((index for index, run in enumerate(state["runs"]) if run["run_id"] == wanted), 0)
        app.say(value["summary"])

    return _task(app, "Read project inventories", lambda: projects.discover_project(root, files=hub.files), complete)


def _apply_run(app, value):
    from .log_tools import before_source_change
    before_source_change(app)
    state = initialize(app)
    binding = value["binding"]
    if "binding_backup" not in state:
        hub = _hub(app)
        state["binding_backup"] = {"settings": {key: hub.settings.get(key, "") for key in ("metrics_file", "contract", "workdir", "passport")},
                                   "log_manifest": app.cfg["logs"].get("manifest_file", ""), "passport_record": hub.passport, "passport_diff": hub.passport_diff}
    state.update(binding=binding, logs=value["logs"], run_warnings=value["warnings"], restore_run_id=binding["run_id"], tree=None, preview=None,
                 summary=f"Selected {binding['run_id']} / attempt {binding['attempt']} / {binding['state']}")
    _hub(app).configure(metrics_file=binding["metrics_file"], contract=binding["contract"], workdir=binding["run_root"], passport=binding["passport"])
    # A prior run's in-memory passport must never appear under the new identity.
    app.research.passport = value.get("passport_record")
    app.research.passport_diff = None
    app.cfg["logs"]["manifest_file"] = binding["log_manifest"]
    app.research_job_id = binding["job_id"]
    app.selected_id = binding["job_id"]
    app.log_job = binding["job_id"]
    app.log_record = None
    app.logs.entry = None
    app.logs.entries = []
    app.logs.browser = False
    app.logs.candidates.clear()
    app.logs.clear_selection(reset_cursor=True)
    app.logs.path, app.logs.top, app.logs.match, app.logs.last_bookmark = "", None, None, None
    app.logs._buffer_token = None
    app.logs.which, app.logs.file_index = "out", 0
    app.log_selection_expected = False
    app.tab, app.research_view, app.mode = "research", "experiment" if binding["metrics_file"] else "artifacts", "main"
    app.research_scroll = 0
    app.say(state["summary"] + (f"; {len(value['warnings'])} binding notices (:runs)" if value["warnings"] else ""))


def _select(app, run_id):
    state = initialize(app)
    if not state["root"]:
        raise ValueError("Choose a project first with :project PATH")
    root = state["root"]
    hub = _hub(app)
    return _task(app, "Bind run " + clean(run_id), lambda: projects.select_run(root, run_id, files=hub.files), lambda value: _apply_run(app, value))


def _outputs(app):
    state = initialize(app)
    settings = _hub(app).settings
    contract, root = settings.get("contract", ""), settings.get("workdir", "")
    if not contract or not root:
        raise ValueError("Select a run with an output contract, or attach :artifacts CONTRACT ROOT first")
    hub = _hub(app)
    app.mode = "project_outputs"

    def complete(value):
        state.update(tree=value, preview=None, collapsed=[], output_cursor=0, output_top=0, filter="", filtering=False)
        app.say("Declared outputs: " + value["summary"])

    return _task(app, "Inspect declared outputs", lambda: projects.artifact_tree(contract, root, files=hub.files), complete)


def _visible_runs(state):
    query = state.get("filter", "").casefold()
    return [run for run in state["runs"] if not query or query in " ".join(str(run.get(key) or "") for key in ("run_id", "experiment_id", "state", "job_id", "name")).casefold()]


def _visible_outputs(state):
    tree = state.get("tree") or {}
    collapsed = state.get("collapsed", [])
    query = state.get("filter", "").casefold()
    return [node for node in tree.get("nodes", []) if (query or not any(node["path"].startswith(parent + "/") for parent in collapsed))
            and (not query or query in node["path"].casefold() or query in node["status"].casefold())]


def _preview(app, node):
    if node.get("directory"):
        state = initialize(app)
        path = node["path"]
        if path in state["collapsed"]:
            state["collapsed"].remove(path)
        else:
            state["collapsed"].append(path)
        return
    state = initialize(app)
    root = state["tree"]["root"]
    hub = _hub(app)

    def complete(value):
        state.update(preview=value, preview_scroll=0, preview_node=node, preview_pages=[(0, 0)], preview_page=0,
                     preview_columns=None, preview_sort=None, preview_column=0, preview_collapsed=[], preview_format=None)
        app.mode = "project_preview"
        app.say(value["summary"])

    _task(app, "Preview " + clean(node["path"]), lambda: artifact_pages.read_page(root, node["specification"], files=hub.files), complete)


def _preview_page(app, direction=0, *, reset=False):
    state = initialize(app)
    node = state.get("preview_node")
    if not node or not state.get("tree"):
        raise ValueError("Open a declared artifact first with :outputs")
    if state["busy"]:
        raise ValueError("An artifact page is already being read")
    preview = state.get("preview") or {}
    pages = [(0, 0)] if reset else list(state["preview_pages"])
    page_index = 0 if reset else state["preview_page"] + direction
    if page_index < 0:
        app.say("First artifact page")
        return False
    if page_index >= len(pages):
        if not preview.get("has_next"):
            app.say("Last artifact page")
            return False
        pages.append((preview["next_offset"], preview["next_row"]))
    offset, row = pages[page_index]
    root = state["tree"]["root"]
    hub = _hub(app)
    columns = None if state["preview_columns"] is None else list(state["preview_columns"])
    sort = state["preview_sort"]
    collapsed = list(state["preview_collapsed"])
    specification = dict(node["specification"])
    if state["preview_format"] is not None:
        specification["format"] = state["preview_format"]
    def failed():
        state["preview_sort"] = preview.get("sort")
        state["preview_columns"] = preview.get("columns")
    def complete(value):
        old_identity = preview.get("identity")
        if not reset and old_identity is not None and value.get("identity") != old_identity:
            app.fail("Artifact changed between pages; reopen it to use a consistent file")
            return
        state.update(preview=value, preview_scroll=0, preview_pages=pages, preview_page=page_index)
        app.say(value["summary"])
    return _task(app, "Read artifact page " + str(page_index + 1),
                 lambda: artifact_pages.read_page(root, specification, files=hub.files, offset=offset,
                                                  row=row, columns=columns, sort=sort, collapsed=collapsed), complete, failed)


def _csv_column(preview, value):
    header = preview.get("header", [])
    if value.isascii() and value.isdigit() and 1 <= int(value) <= len(header):
        return int(value) - 1
    if value in header:
        return header.index(value)
    raise ValueError("Choose an existing CSV header or its 1-based column number")


def _artifact_control(app, rest):
    state = initialize(app)
    preview = state.get("preview") or {}
    if app.mode != "project_preview":
        raise ValueError("Open a declared output in :outputs before using artifact page controls")
    if state["busy"]:
        raise ValueError("An artifact page is already being read")
    if rest in (["next"], ["prev"]):
        _preview_page(app, 1 if rest == ["next"] else -1)
    elif rest == ["refresh"]:
        _preview_page(app, reset=True)
    elif rest in (["text"], ["structured"]):
        state["preview_format"] = "text" if rest == ["text"] else None
        state["preview_columns"], state["preview_sort"] = None, None
        _preview_page(app, reset=True)
    elif rest and rest[0] == "columns" and len(rest) >= 2:
        if preview.get("format") != "csv":
            raise ValueError("Column selection requires a CSV artifact")
        columns = None if rest[1:] == ["all"] else list(dict.fromkeys(_csv_column(preview, item) for item in rest[1:]))
        state["preview_columns"] = columns
        _preview_page(app, reset=True)
    elif rest and rest[0] == "sort" and len(rest) == 3:
        if preview.get("format") != "csv" or rest[2] not in ("asc", "desc", "off"):
            raise ValueError("artifact sort COLUMN asc|desc|off (CSV global sorting)")
        column = _csv_column(preview, rest[1])
        if rest[2] != "off" and preview.get("size", 0) > artifact_pages.SORT_BYTES:
            raise ValueError("Global CSV sorting supports at most 8 MiB; no partial sort was applied")
        state["preview_sort"] = None if rest[2] == "off" else (column, rest[2])
        _preview_page(app, reset=True)
    elif rest and rest[0] == "json" and len(rest) == 2:
        if preview.get("format") != "json":
            raise ValueError("JSON node controls require a structured JSON artifact")
        path = "" if rest[1] == "/" else rest[1]
        if path in state["preview_collapsed"]:
            state["preview_collapsed"].remove(path)
        else:
            state["preview_collapsed"].append(path)
        nodes, more = json_page(preview["json_value"], state["preview_collapsed"])
        preview.update(nodes=nodes, lines=[item["text"] for item in nodes], row=0, next_row=len(nodes),
                       has_next=more, truncated=more,
                       summary=f"{preview.get('size', 0)} source bytes; JSON nodes 1-{len(nodes)}; expandable tree")
        state.update(preview_scroll=0, preview_pages=[(0, 0)], preview_page=0)
    else:
        raise ValueError("artifact next|prev|refresh|text|structured|columns COLUMN...|sort COLUMN asc|desc|off|json /POINTER")


def run_command(app, args):
    if not args or args[0] not in command_names():
        return False
    command, rest = args[0], list(args[1:])
    state = initialize(app)
    try:
        if command == "project":
            if len(rest) != 1:
                raise ValueError("project PATH")
            app.mode = "project_runs"
            _refresh_runs(app, rest[0])
        elif command == "runs":
            if rest or not state["root"]:
                raise ValueError("runs (choose :project PATH first)")
            app.mode = "project_runs"
            state["filter"], state["filtering"] = "", False
            _refresh_runs(app, state["root"])
        elif command == "run":
            if rest == ["clear"]:
                clear_binding(app)
                app.mode = "main"
                app.say("Run binding cleared; original research and log paths restored")
            elif len(rest) == 2 and rest[0] == "select":
                _select(app, rest[1])
            elif len(rest) == 2 and rest[0] == "passport":
                binding = selected_binding(app)
                if not binding:
                    raise ValueError("Select a run before choosing its passport")
                path = projects.relative_path(rest[1])
                hub = _hub(app)

                def complete(passport):
                    binding["passport"] = os.path.join(binding["run_root"], path)
                    hub.passport, hub.passport_diff = passport, None
                    hub.configure(passport=binding["passport"])
                    app.tab, app.research_view, app.mode = "research", "passport", "main"
                    app.say("Bound verified passport " + passport["id"])

                _task(app, "Verify run passport", lambda: projects.read_passport(binding["run_root"], path, job_id=binding["job_id"], files=hub.files), complete)
            else:
                raise ValueError("run select RUN_ID | run passport RELATIVE_PATH | run clear")
        elif command in ("outputs", "artifact"):
            if command == "artifact" and rest not in ([], ["browse"]):
                _artifact_control(app, rest)
                return True
            if rest not in ([], ["browse"]):
                raise ValueError(command + " [browse]")
            _outputs(app)
    except (OSError, ValueError, TypeError) as exc:
        app.fail(command + ": " + clean(exc))
    return True


def handle_key(app, key):
    if app.mode not in MODES:
        return False
    state = initialize(app)
    if key == "!" and app.mode == "project_runs":
        state["notices_open"] = not state["notices_open"]
        return True
    if state["notices_open"] and app.mode == "project_runs":
        if key == "esc":
            state["notices_open"] = False
        else:
            notices = state["warnings"] + state["run_warnings"]
            delta = {"up": -1, "down": 1, "pgup": -10, "pgdn": 10, "k": -1, "j": 1}.get(key, 0)
            state["notices_scroll"] = max(0, min(max(0, len(notices) - 1), state["notices_scroll"] + delta))
            if key in ("home", "end"):
                state["notices_scroll"] = 0 if key == "home" else max(0, len(notices) - 1)
        return True
    if state["filtering"] and app.mode != "project_preview":
        if key in ("enter", "esc"):
            state["filtering"] = False
            if key == "esc":
                state["filter"] = ""
        elif key in ("backspace", "\b", "\x7f"):
            state["filter"] = state["filter"][:-1]
        elif len(key) == 1 and key.isprintable():
            state["filter"] = (state["filter"] + key)[:128]
        state["run_cursor"], state["output_cursor"] = 0, 0
        return True
    if key == "esc":
        if app.mode == "project_preview":
            app.mode = "project_outputs"
        else:
            app.mode = "main"
        return True
    if key in ("/",) and app.mode != "project_preview":
        state["filtering"] = True
        return True
    if key in ("r",) and app.mode != "project_preview":
        try:
            _refresh_runs(app, state["root"]) if app.mode == "project_runs" else _outputs(app)
        except ValueError as exc:
            app.fail(clean(exc))
        return True
    page = max(1, getattr(app, "height", 24) - 12)
    action = getattr(app, "keymap", {}).get(key, key)
    if app.mode == "project_preview":
        preview = state.get("preview") or {}
        if key in ("[", "]"):
            try:
                _preview_page(app, -1 if key == "[" else 1)
            except (ValueError, OSError) as exc:
                app.fail(clean(exc))
            return True
        if preview.get("format") == "csv" and key in ("left", "right", "enter", "c"):
            header = preview.get("header", [])
            if not header:
                return True
            if key in ("left", "right"):
                state["preview_column"] = (state["preview_column"] + (-1 if key == "left" else 1)) % len(header)
            else:
                column = state["preview_column"]
                try:
                    if key == "enter":
                        sort = state["preview_sort"]
                        direction = "desc" if sort == (column, "asc") else "off" if sort == (column, "desc") else "asc"
                        _artifact_control(app, ["sort", str(column + 1), direction])
                    else:
                        indexes = list(state["preview_columns"] if state["preview_columns"] is not None else range(len(header)))
                        if column in indexes and len(indexes) > 1:
                            indexes.remove(column)
                        elif column not in indexes:
                            indexes.append(column)
                            indexes.sort()
                        state["preview_columns"] = indexes
                        _preview_page(app, reset=True)
                except (ValueError, OSError) as exc:
                    app.fail(clean(exc))
            return True
        if preview.get("format") == "json" and key in ("enter", "space"):
            nodes = preview.get("nodes", [])
            item = nodes[min(state["preview_scroll"], len(nodes) - 1)] if nodes else {}
            if item.get("expandable"):
                _artifact_control(app, ["json", item["node"] or "/"])
            return True
        count = len((state.get("preview") or {}).get("lines", []))
        if preview.get("format") == "csv":
            count = max(0, count - 1)
        cursor_key = "preview_scroll"
    else:
        items = _visible_runs(state) if app.mode == "project_runs" else _visible_outputs(state)
        count = len(items)
        cursor_key = "run_cursor" if app.mode == "project_runs" else "output_cursor"
    delta = {"up": -1, "down": 1, "page_up": -page, "page_down": page, "pgup": -page, "pgdn": page}.get(action)
    if delta is not None:
        state[cursor_key] = max(0, min(max(0, count - 1), state[cursor_key] + delta))
    elif action in ("home", "end"):
        state[cursor_key] = 0 if action == "home" else max(0, count - 1)
    elif key in ("enter", "right", "space") and app.mode != "project_preview" and count:
        item = items[min(state[cursor_key], count - 1)]
        try:
            if app.mode == "project_runs":
                _select(app, item["run_id"])
            else:
                _preview(app, item)
        except (OSError, ValueError) as exc:
            app.fail(clean(exc))
    elif key == "left" and app.mode == "project_preview":
        app.mode = "project_outputs"
    elif key == "left" and app.mode == "project_outputs" and count:
        item = items[min(state[cursor_key], count - 1)]
        parent = item["path"] if item["directory"] else item["path"].rpartition("/")[0]
        if parent and parent not in state["collapsed"]:
            state["collapsed"].append(parent)
            state["output_cursor"] = next((index for index, node in enumerate(_visible_outputs(state)) if node["path"] == parent), 0)
    return True


def _window(state, key, top_key, count, page):
    cursor = max(0, min(state[key], max(0, count - 1)))
    top = min(state[top_key], max(0, count - page))
    top = min(top, cursor)
    if cursor >= top + page:
        top = cursor - page + 1
    state[key], state[top_key] = cursor, top
    return cursor, top


def overlay(views, snap, app, width, height):
    if app.mode not in MODES:
        return None
    state = initialize(app)
    g = views.g
    row = lambda text, style="": [(L.cut(clean(text, g.ascii), max(0, width - 8), g.ascii), style)]
    binding = selected_binding(app) or {}
    identity = f"{binding.get('run_id', 'none')} / attempt {binding.get('attempt', '?')} / job {binding.get('job_id') or 'not recorded'}"
    lines = [row(" Project " + (state["root"] or "not selected"), "cyan+bold"), row(" Selected " + identity, "dim")]
    if state["busy"]:
        lines.append(row(" Background read in progress...", "yellow"))
    if app.mode == "project_runs":
        if state["notices_open"]:
            lines.append(row(" All binding and discovery notices | arrows scroll | ! / Esc back", "dim"))
            notices = state["warnings"] + state["run_warnings"]
            start = min(state["notices_scroll"], max(0, len(notices) - 1))
            for notice in notices[start:start + max(1, height - 9)]:
                lines.append(row(" " + notice, "yellow"))
            if not notices:
                lines.append(row(" No binding or discovery notices", "green"))
            return L.box(g, lines, width, height, "project notices")
        lines.append(row(" Enter binds | / filter | ! notices | r refresh | Esc back", "dim"))
        lines.append(row(" Filter: " + state["filter"] + ("_" if state["filtering"] else ""), "cyan"))
        items = _visible_runs(state)
        page = max(1, height - 11)
        cursor, top = _window(state, "run_cursor", "run_top", len(items), page)
        for index, run in enumerate(items[top:top + page], top):
            marker = (">" if g.ascii else "›") if index == cursor else " "
            text = f" {marker} {run['run_id']}  [{run['state']}]  attempt {run['attempt']}  job {run.get('job_id') or 'unrecorded'}"
            lines.append(row(text, "rev+bold" if index == cursor else "green" if run["state"] == "COMPLETED" else "yellow" if run["state"] in ("RUNNING", "PENDING") else ""))
        if not items:
            lines.append(row(" " + state["summary"], "dim"))
        notices = state["warnings"] + state["run_warnings"]
        lines.append(row(f" {len(items)} matching runs; {len(notices)} notices" + ("; discovery limited" if state.get("limited") else ""), "yellow" if notices else "dim"))
        if notices:
            lines.append(row(" " + notices[0], "yellow"))
        title = "project / runs"
    elif app.mode == "project_outputs":
        tree = state.get("tree") or {}
        lines.append(row(" Enter expands or previews | Left collapses | / filter | r refresh | Esc back", "dim"))
        lines.append(row(" " + tree.get("summary", "Waiting for declared output inspection"), "yellow" if tree.get("status") != "valid" else "green"))
        lines.append(row(" Filter: " + state["filter"] + ("_" if state["filtering"] else ""), "cyan"))
        items = _visible_outputs(state)
        page = max(1, height - 12)
        cursor, top = _window(state, "output_cursor", "output_top", len(items), page)
        for index, node in enumerate(items[top:top + page], top):
            marker = (">" if g.ascii else "›") if index == cursor else " "
            branch = ("+" if node["path"] in state["collapsed"] else "-") if node["directory"] else ("o" if g.ascii else "◆")
            status = node["status"]
            size = "" if node.get("size") is None else f"  {node['size']} B"
            lines.append(row(f" {marker} {'  ' * min(8, node['depth'])}{branch} {node['name']}  {status}{size}",
                             "rev+bold" if index == cursor else "green" if status == "valid" else "red" if status in ("missing", "invalid", "error") else "dim"))
        if not items:
            lines.append(row(" No declared outputs match this filter", "dim"))
        lines.append(row(f" {len(items)} visible nodes / {tree.get('declared', 0)} declared files" + ("; tree display limit reached" if tree.get("limited") else ""), "dim"))
        title = "declared artifacts"
    else:
        preview = state.get("preview") or {}
        lines.append(row(" " + preview.get("path", "") + " | " + preview.get("format", "text"), "bold"))
        lines.append(row(" " + preview.get("summary", ""), "yellow" if preview.get("truncated") or preview.get("status") != "ready" else "dim"))
        lines.append(row(" Arrows / PgUp / PgDn scroll | [ previous page | ] next page | Esc outputs", "dim"))
        if preview.get("format") == "csv":
            header = preview.get("header", [])
            column = min(state["preview_column"], max(0, len(header) - 1))
            name = header[column] if header else "none"
            lines.append(row(f" Column {column + 1}: {name} | Left/Right choose | Enter sort asc/desc/off | c show/hide", "cyan"))
            shown = []
            for index in preview.get("columns", []):
                name = header[index]
                sorting = preview.get("sort")
                if sorting and sorting[0] == index:
                    name += " ^" if sorting[1] == "asc" else " v"
                shown.append(("[" + name + "]") if index == column else name)
            lines.append(row(" " + " | ".join(shown), "bold+cyan"))
        elif preview.get("format") == "json":
            lines.append(row(" Enter expands/folds selected JSON node; :artifact json /POINTER", "cyan"))
        page = max(1, height - 11)
        display_lines = preview.get("lines", [])[1:] if preview.get("format") == "csv" else preview.get("lines", [])
        start = min(state["preview_scroll"], max(0, len(display_lines) - 1))
        page = max(1, height - len(lines) - 5)
        for index, text in enumerate(display_lines[start:start + page], start):
            selected = index == state["preview_scroll"]
            marker = ">" if g.ascii else "›"
            number = preview.get("row", 0) + index + 1
            lines.append(row(f" {marker if selected else ' '} {number:>4}  {text}", "rev+bold" if selected else ""))
        title = "artifact preview"
    return L.box(g, lines, width, height, title)
