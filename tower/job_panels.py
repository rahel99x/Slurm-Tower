"""Live, job-scoped Details tabs with independent log and inspection state.

Interactive frames inspect published snapshots only. Log discovery and tails use
the existing bounded research worker; no second executor or scheduler mutation
is introduced by the panel.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

from . import layout as L
from .log_catalog import LogCatalog
from .logs import LogSession
from .research import ResearchHub, clean

TABS = (("inspector", "Inspector"), ("logs", "Logs"),
        ("investigate", "Investigate"), ("research", "Research"),
        ("analytics", "Analytics"), ("quick", "Quick Advisor"), ("off", "Off"))
MODES = tuple(name for name, _ in TABS)
MAX_ROWS = 2048
MAX_LOG_BYTES = 256 * 1024


def initialize(app):
    state = getattr(app, "job_panel_state", None)
    if not isinstance(state, dict):
        state = dict(mode="inspector", focus="", job=None, file_id=None,
                     entries=[], files=None, session=None, catalog=None)
        app.job_panel_state = state
    state.setdefault("research_view", "experiment")
    state.setdefault("analytics_view", "job")
    state.setdefault("scrolls", {})
    state.setdefault("view_states", {})
    state.setdefault("document_windows", {})
    state.setdefault("document_maps", {})
    state.setdefault("document_headers", {})
    return state


def restore(app, data):
    state = initialize(app)
    if isinstance(data, dict) and data.get("mode") in MODES:
        state["mode"] = data["mode"]
    if isinstance(data, dict):
        from .views import ANALYTICS_VIEWS
        from .research import RESEARCH_VIEWS
        for group, choices in (("research", RESEARCH_VIEWS), ("analytics", ANALYTICS_VIEWS)):
            if data.get(group + "_view") in dict(choices):
                state[group + "_view"] = data[group + "_view"]


def save(app):
    state = initialize(app)
    result = {"mode": state["mode"]}
    # Keep legacy preference files compact unless a workspace choice was made.
    for group, default in (("research", "experiment"), ("analytics", "job")):
        if state[group + "_view"] != default:
            result[group + "_view"] = state[group + "_view"]
    return result


def _view_key(state):
    mode = state["mode"]
    return mode + ":" + state[mode + "_view"] if mode in ("research", "analytics") else mode


def _choices(group):
    if group == "research":
        from .research import RESEARCH_VIEWS
        return RESEARCH_VIEWS
    if group == "analytics":
        from .views import ANALYTICS_VIEWS
        return [(key, label.title()) for key, label in ANALYTICS_VIEWS]
    return ()


def command_names():
    return ["jobpanel"]


def _say(app, message):
    callback = getattr(app, "say", None)
    if callable(callback):
        callback(message)


def _activate(app, mode, *, focus=True, view=None):
    state = initialize(app)
    if mode not in MODES:
        return False
    from .workspace_layout import initialize as layout_state
    layout = layout_state(app)
    state["scrolls"][_view_key(state)] = layout.scroll.get("jobs:details", 0)
    if view is not None:
        if view not in dict(_choices(mode)):
            return False
        state[mode + "_view"] = view
    state["mode"], state["focus"] = mode, ("views" if view is not None else "tabs") if focus else ""
    layout.scroll["jobs:details"] = state["scrolls"].get(_view_key(state), 0)
    if focus:
        layout.focus = "details"
    callback = getattr(app, "save", None)
    if callable(callback):
        callback()
    from . import quick_advisor
    if mode == "quick":
        quick_advisor.request(app)
    else:
        quick_advisor.cancel(app)
    return True


def run_command(app, args):
    if not args or args[0] != "jobpanel":
        return False
    if args[1:] == ["focus"] or len(args) == 1:
        initialize(app)["focus"] = "tabs"
        from .workspace_layout import initialize as layout_state
        layout_state(app).focus = "details"
        _say(app, "Details tabs: arrows choose; Enter focuses content; Esc returns to jobs")
    elif len(args) == 2 and args[1] in MODES:
        _activate(app, args[1])
    elif len(args) == 3 and args[1] in ("research", "analytics") and args[2] in dict(_choices(args[1])):
        _activate(app, args[1], view=args[2])
    else:
        callback = getattr(app, "fail", None)
        if callable(callback):
            callback("jobpanel [inspector|logs|investigate|research [VIEW]|analytics [VIEW]|quick|off|focus]")
    return True


def handle_key(app, key):
    state = initialize(app)
    if getattr(app, "tab", "") != "jobs" or getattr(app, "mode", "main") != "main":
        state["focus"] = ""
        return False
    if not state["focus"]:
        return False
    if key in ("ctrl-w", "ctrl_w", "f6"):
        state["focus"] = ""
        return False
    if key == "esc":
        state["focus"] = ""
        from .workspace_layout import initialize as layout_state
        layout_state(app).focus = "main"
        return True
    if key in ("enter", "tab", "btab"):
        if key == "enter" and state["focus"] == "content" and state["mode"] == "quick":
            from . import quick_advisor
            quick_advisor.request(app)
            return True
        if state["focus"] == "tabs" and state["mode"] in ("research", "analytics"):
            state["focus"] = "views"
        else:
            state["focus"] = "content" if state["focus"] in ("tabs", "views") else "tabs"
        return True
    if state["focus"] == "tabs" and key in ("left", "right", "up", "down", "home", "end"):
        index = MODES.index(state["mode"])
        index = 0 if key == "home" else len(MODES) - 1 if key == "end" else (index + (-1 if key in ("left", "up") else 1)) % len(MODES)
        _activate(app, MODES[index])
        return True
    if state["focus"] == "views" and key in ("left", "right", "up", "down", "home", "end"):
        choices = [name for name, _ in _choices(state["mode"])]
        index = choices.index(state[state["mode"] + "_view"])
        index = 0 if key == "home" else len(choices) - 1 if key == "end" else (index + (-1 if key in ("left", "up") else 1)) % len(choices)
        _activate(app, state["mode"], view=choices[index])
        return True
    if state["focus"] == "content":
        if state["mode"] == "logs" and key in ("left", "right"):
            entries = state["entries"]
            if entries:
                index = next((i for i, entry in enumerate(entries) if entry["id"] == state["file_id"]), 0)
                state["file_id"] = entries[(index + (-1 if key == "left" else 1)) % len(entries)]["id"]
                from .workspace_layout import initialize as layout_state
                layout_state(app).scroll["jobs:details"] = 0
                if state["session"]:
                    state["session"].top = None
            return True
        if key in ("up", "down", "pgup", "pgdn", "home", "end"):
            if state["mode"] == "logs" and state["session"]:
                session = state["session"]
                buf = session.buffers.get(session.path)
                if buf is not None:
                    page, total = max(1, session.page), buf.total
                    top = max(0, total - page) if session.top is None else session.top
                    top = 0 if key == "home" else max(0, total - page) if key == "end" else top + {"up": -1, "down": 1, "pgup": -page, "pgdn": page}[key]
                    session.top = max(0, min(max(0, total - page), top))
                    if key == "end":
                        session.top = None
            else:
                from .workspace_layout import _scroll, initialize as layout_state
                state_layout = layout_state(app)
                previous = state_layout.focus
                state_layout.focus = "details"
                _scroll(app, key)
                state_layout.focus = previous
            return True
    return False


def handle_mouse(app, y, x, button="left", shift=False):
    if getattr(app, "tab", "") != "jobs" or getattr(app, "mode", "main") != "main":
        return False
    state = initialize(app)
    for row, kind, value in getattr(app, "last_hits", []):
        if row != y or kind not in ("job_panel_tab", "job_panel_view", "job_panel_file", "job_panel_action"):
            continue
        target, left, right = value
        if left <= x < right:
            if button == "left":
                if kind == "job_panel_tab":
                    _activate(app, target)
                elif kind == "job_panel_view":
                    group, view = target.split(":", 1)
                    _activate(app, group, view=view)
                elif kind == "job_panel_action":
                    _content_action(app, target)
                else:
                    state["file_id"], state["focus"] = target, "content"
                    from .workspace_layout import initialize as layout_state
                    layout = layout_state(app)
                    layout.focus = "details"
                    layout.scroll["jobs:details"] = 0
                    if state["session"]:
                        state["session"].top = None
            return True
    if contains(app, y, x):
        if button in ("wheel-up", "wheel-down", "wheel_up", "wheel_down"):
            state["focus"] = "content"
            handle_key(app, "up" if button in ("wheel-up", "wheel_up") else "down")
        elif button == "left":
            state["focus"] = "content"
        return True
    if button == "left":
        state["focus"] = ""
    return False


def contains(app, y, x):
    rect = getattr(app, "job_panel_rect", None)
    return bool(getattr(app, "tab", "") == "jobs" and rect and
                rect.x <= x < rect.x + rect.width and rect.y <= y < rect.y + rect.height)


def overlay(views, snap, app, width, height):
    return None


def tick(app):
    """Release transient focus when the user leaves the inline workspace."""
    state = initialize(app)
    from . import quick_advisor
    quick_advisor.tick(app)
    if getattr(app, "tab", "") != "jobs" or getattr(app, "mode", "main") != "main":
        state["focus"] = ""
        return


def _worker(app, files):
    if getattr(app, "research", None) is None:
        app.research = ResearchHub(app.cfg, files)
    return app.research


def _buttons(g, state, width):
    """Pack accessible buttons into as many rows as a narrow pane requires."""
    rows, hits, current, position = [], [], [], 0
    for name, title in TABS:
        label = " " + title + " "
        if position and position + len(label) > width:
            rows.append(current)
            current, position = [], 0
        available = max(0, width - position)
        shown = L.cut(label, available, g.ascii)
        size = L.vlen(shown)
        if size:
            active = name == state["mode"]
            style = "sel+bold" if active else "secondary+bg:surface"
            if active and state["focus"] == "tabs":
                style += "+under"
            current.append((shown, style))
            hits.append((len(rows), "job_panel_tab", (name, position, position + size)))
            position += size
    if current:
        rows.append(current)
    group = state["mode"]
    if group in ("research", "analytics"):
        current, position = [], 0
        for name, title in _choices(group):
            label = " " + title + " "
            if position and position + L.vlen(label) > width:
                rows.append(current)
                current, position = [], 0
            shown = L.cut(label, max(0, width - position), g.ascii)
            size = L.vlen(shown)
            if not size:
                continue
            active = name == state[group + "_view"]
            style = "sel+bold" if active else "cyan+bg:surface"
            if active and state["focus"] == "views":
                style += "+under"
            current.append((shown, style))
            hits.append((len(rows), "job_panel_view", (group + ":" + name, position, position + size)))
            position += size
        if current:
            rows.append(current)
    return rows, hits


def _inspector(views, snap, app, job, width, state):
    """Reuse the unified inspector without changing its modal selection."""
    from .analysis_ui import SECTIONS, _inspector_rows
    proxy = copy.copy(app)
    proxy.chart_interaction_state = getattr(app, "chart_interaction_state", None)
    proxy.analysis_state = dict(job=job.id, evidence_job=job.id)
    proxy.log_job, proxy.logs = job.id, SimpleNamespace(entries=list(state.get("entries", [])))
    proxy.research_evidence = state.get("evidence", {}) if state.get("evidence_job") == job.id else {}
    # Keep the queue's measured scientific diagnostics: the unified inspector
    # alone does not include dependency blockers, rank imbalance, GPU traces,
    # live GPU samples, or the selected job's tags and note.
    active = any(record.id == job.id for record in snap.get("jobs", []))
    rows = [[(" Live summary" if active else "Recent summary", "heading+bold")],
            [(clean(f" Job {job.id}  {job.name}", views.g.ascii), "cyan+bold")]]
    hits = []
    if active:
        for item in views.selected_panel(snap, job, width, 0, app):
            text = L.row_text(item).lstrip()
            if text.startswith("step ") and L.vlen(text) > width:
                # Keep a diagnostic as one readable fact instead of splitting
                # task identity or percentages across terminal rows.
                rows.extend([("   " + field.strip(), item[0][1])]
                            for field in text.split(" " + views.g.dot + " "))
            elif text.startswith("trace ") and len(item) > 2:
                rows.append(item[:2])
                rows.extend([("   " + field.strip(), "dim")]
                            for field in item[-1][0].split(" " + views.g.dot + " ") if field.strip())
            else:
                rows.append(item)
    else:
        rows.extend(views.finished_summary(job, width)[:-1])
    metadata = snap.get("tags", {}).get(job.id, {})
    if metadata.get("tags"):
        rows.append([(" Tags " + clean(" ".join(metadata["tags"]), views.g.ascii), "cyan")])
    for section, title in enumerate(SECTIONS):
        proxy.analysis_state["section"] = section
        rows.append([(" " + title, "heading+bold")])
        rendered = _inspector_rows(views.g, snap, proxy, width)
        content = rendered[proxy.analysis_state.get("inspector_nav_rows", 1):]
        content = content[2:]
        if title == "Files":
            details = snap.get("details", {}).get(job.id, {})
            for index, item in enumerate(content):
                text = L.row_text(item).lstrip()
                field = next((name for name in ("StdOut", "StdErr") if text.startswith(name + " ")), None)
                path = details.get(field) if field else None
                if path and isinstance(path, str) and path not in ("(null)", "N/A", "none"):
                    from .views import stdout_path
                    path = stdout_path(job, details, views.files, field, probe=False)
                    target = ("inline_log", {"job": job.id, "id": field, "path": path, "source": "Inspector " + field})
                    hits.append((len(rows) + index, "job_panel_action", (target, 0, width)))
                elif text.startswith("l / Enter"):
                    hits.append((len(rows) + index, "job_panel_action", (("inline_logs", job.id), 0, width)))
        elif title == "Evidence" and content:
            hits.append((len(rows) + len(content) - 1, "job_panel_action", (("inline_evidence", job.id), 0, width)))
        rows.extend(content)
    return rows[:MAX_ROWS], [hit for hit in hits if hit[0] < MAX_ROWS]


def _logs(views, snap, app, job, width, height, state):
    from .views import stdout_path
    files = views.files
    if state["files"] is not files:
        if state["catalog"]:
            state["catalog"].close()
        state.update(files=files, catalog=LogCatalog(files, ttl=5),
                     session=LogSession(max_bytes=MAX_LOG_BYTES, files=files), file_id=None, entries=[])
    session, catalog = state["session"], state["catalog"]
    from .refresh_rate import multiplier
    session.polling_multiplier = catalog.polling_multiplier = multiplier(app)
    details = snap.get("details", {}).get(job.id, {})
    warnings = []
    try:
        manifest = views.log_manifest_path(app, job, details)
    except ValueError as exc:
        manifest = ""
        warnings.append(str(exc))
    worker = _worker(app, files) if getattr(app, "interactive", False) else None
    result = catalog.request(job.id, stdout_path(job, details, files, probe=False),
                            stdout_path(job, details, files, "StdErr", probe=False),
                            manifest_file=manifest, worker=worker, wait=not getattr(app, "interactive", False))
    state["entries"] = entries = result.get("entries", [])
    row = lambda text, style="": [(clean(text, views.g.ascii), style)]
    rows, hits = [row(f" Job {job.id} / {job.name}", "cyan+bold")], []
    rows.append(row(" Enter: content / Left-Right: file / End: follow / Esc: jobs", "dim"))
    warnings.extend(result.get("messages", []))
    for warning in warnings[:2]:
        rows.append(row(" " + warning, "yellow"))
    if not entries:
        rows.append(row(" Waiting for this job's log catalog." if result.get("status") == "loading"
                        else " No log paths available for this exact job yet.", "dim"))
        return rows, hits
    selected = next((entry for entry in entries if entry["id"] == state["file_id"]), entries[0])
    state["file_id"] = selected["id"]
    index = entries.index(selected)
    start = max(0, min(index - 1, len(entries) - 3))
    for entry in entries[start:start + 3]:
        label = ("> " if entry is selected else "  ") + entry.get("label", entry["id"])
        hits.append((len(rows), "job_panel_file", (entry["id"], 0, width)))
        rows.append(row(" " + label, "sel+bold" if entry is selected else "cyan"))
    rows.append(row(f" File {index + 1}/{len(entries)}: {selected['path']}", "magenta"))
    buf = session.buffer(selected["path"], worker=worker, background=getattr(app, "interactive", False))
    if buf is None or buf.loading:
        rows.append(row(" Waiting for the background log reader.", "dim"))
    elif buf.error:
        rows.append(row(" Log unavailable: " + buf.error, "yellow"))
    else:
        # Only a visible, bounded tail is formatted, even for multi-gigabyte logs.
        page = max(1, min(160, (height or 24) - len(rows) - 2))
        session.page = page
        from .scrolling import viewport
        target = max(0, buf.total - page) if session.top is None else session.top
        painted = viewport(app, "inline-log", target, buf.total, page,
                           context=(job.id, selected["path"], buf.ident, buf.reloads, page),
                           immediate=session.top is None)
        lines, first = buf.window(None if session.top is None else painted, page)
        rows.append(row(f" {'Following' if session.top is None else 'Paused'} / retained lines {first + 1 if lines else 0}-{first + len(lines)} of {buf.total}"
                        + (" / earlier bytes omitted" if buf.truncated else ""), "dim"))
        rows.extend(L.clip_row(row(line), width) for line in lines)
        if not lines:
            rows.append(row(" This log is empty.", "dim"))
    return rows, hits


def _evidence(views, snap, app, job, state, width):
    hub = _worker(app, views.files)
    context = hub.context(snap, app)
    context.update(view="evidence", jid=job.id, explicit_jid=job.id, job=job)
    binding = context.get("binding")
    if binding and binding.get("job_id") != job.id:
        context.update(binding=None, project_logs=None, project_warnings=[], run_id=None, run_root=None,
                       settings=dict(app.cfg.get("research", {})))
    result = hub.request(context, wait=not getattr(app, "interactive", False))
    state["evidence_job"] = job.id
    state["evidence"] = evidence = {item["id"]: item for item in result.get("evidence", [])}
    row = lambda text, style="": [(clean(text, views.g.ascii), style)]
    rows = [row(f" Job {job.id} / {job.name}", "cyan+bold"), row(" " + result.get("summary", "Waiting for the background investigation."), "bold")]
    hits = []
    coverage = result.get("coverage", {})
    if coverage:
        rows.append(row(f" Log coverage {coverage.get('inspected_files', 0)}/{coverage.get('catalog_files', 0)} files; {coverage.get('omitted_files', 0)} omitted", "dim"))
    for hypothesis in result.get("hypotheses", [])[:16]:
        rows.append(row(f" {hypothesis.get('name', '?')} / {hypothesis.get('confidence', 'weak')} evidence", "yellow+bold"))
        for identifier in hypothesis.get("support", [])[:6]:
            item = evidence.get(identifier, {})
            rows.append(row(f" [{identifier}] {item.get('source', '')}: {item.get('text', '')}", "yellow"))
        for check in hypothesis.get("next_checks", [])[:3]:
            rows.append(row(" Check: " + str(check), "cyan"))
    for item in list(evidence.values())[:64]:
        if item.get("path"):
            citation = dict(item, job=job.id)
            hits.append((len(rows), "job_panel_action", (("inline_log", citation), 0, width)))
        rows.append(row(f" [{item['id']}] {item.get('source', '')} / {item.get('path') or item.get('location', '')}", "cyan"))
        rows.append(row(" " + item.get("text", ""), "dim"))
    for limitation in result.get("limitations", [])[:12]:
        rows.append(row(" Unverified: " + str(limitation), "dim"))
    return rows[:MAX_ROWS], [hit for hit in hits if hit[0] < MAX_ROWS]


class _ScopedHub:
    """Expose the existing worker while rejecting another selected run's files."""
    def __init__(self, hub, jid, mismatch=False):
        self.hub, self.jid, self.mismatch = hub, jid, mismatch

    def __getattr__(self, name):
        return getattr(self.hub, name)

    def context(self, snap, app):
        context = self.hub.context(snap, app)
        jobs = snap.get("jobs", []) + snap.get("finished", []) + list(snap.get("departed_jobs", {}).values())
        context.update(jid=self.jid, explicit_jid=self.jid,
                       job=next((item for item in jobs if item.id == self.jid), None))
        if self.mismatch:
            context.update(binding=None, run_id=None, run_root=None, project_logs=None,
                           project_warnings=[], settings={"interval": self.hub.interval},
                           log_settings={})
        return context

    def request(self, context, **kwargs):
        if self.mismatch and context["view"] not in ("arrays", "evidence"):
            return {"status": "empty", "summary": "Waiting for report files linked to this exact job; another run's files remain detached."}
        if context["view"] == "submit" and not context.get("binding"):
            return {"status": "empty", "summary": "This job has no linked submission report. Prepare and review new submissions in the Research workspace."}
        return self.hub.request(context, **kwargs)

    def current(self, context):
        if self.mismatch and context["view"] not in ("arrays", "evidence"):
            return self.request(context)
        return self.hub.current(context)


def _analysis_settings(app):
    """Copy bounded preferences; rendered point caches remain per workspace."""
    source = getattr(app, "analysis_state", {})
    return {key: copy.deepcopy(value) for key, value in source.items()
            if key in ("pinned", "hidden", "order", "expanded", "colors", "metric_display",
                       "axes", "chart_events", "shared_scale", "metric_filter")}


def _scoped_app(app, job, state):
    key = _view_key(state)
    retained = state["view_states"].setdefault(key, {})
    if "analysis" not in retained:
        retained["analysis"] = _analysis_settings(app)
    proxy = copy.copy(app)
    proxy.tab, proxy.mode = state["mode"], "main"
    proxy.selected_id = proxy.research_job_id = proxy.analytics_job = job.id
    proxy.research_view, proxy.analytics_view = state["research_view"], state["analytics_view"]
    proxy.cursor, proxy.top = dict(getattr(app, "cursor", {})), dict(getattr(app, "top", {}))
    proxy.cursor["research"] = retained.get("cursor", 0)
    proxy.analysis_state = retained["analysis"]
    proxy.research_scroll, proxy.research_rows = 0, 0
    proxy.research_array_open = retained.get("array_open", False)
    proxy.research_task_offset = retained.get("task_offset", 0)
    proxy.research_array_focus = False
    proxy.research_groups, proxy.research_evidence = [], {}
    project = getattr(app, "project_state", {}) or {}
    binding = project.get("binding")
    mismatch = bool(binding and binding.get("job_id") != job.id or
                    not binding and getattr(app, "research_job_id", None) not in (None, job.id))
    proxy.project_state = {"binding": None if mismatch else copy.deepcopy(binding),
                           "logs": [] if mismatch else [dict(item) for item in project.get("logs", [])],
                           "run_warnings": [] if mismatch else list(project.get("run_warnings", []))}
    if state["mode"] == "research":
        hub = _worker(app, getattr(getattr(app, "views_ref", None), "files", None))
        proxy.research = _ScopedHub(hub, job.id, mismatch)
    proxy.compare_ids = list(dict.fromkeys([job.id] + list(getattr(app, "compare_ids", []))
                                         + sorted(getattr(app, "marks", []))))[:6]
    # Explicit inline actions may create a modal, but merely rendering must not
    # persist a copied App or change another workspace's table geometry.
    proxy.save = lambda: None
    retained["proxy"] = proxy
    return proxy, retained


def _research(views, snap, app, job, width, height, state, header_rows):
    from .research_views import render as research_render
    proxy, retained = _scoped_app(app, job, state)
    proxy.research_document_mode = True
    document_key = (_view_key(state), width)
    window = state["document_windows"].get(document_key)
    previous = state["document_maps"].get(document_key)
    if previous:
        from .workspace_layout import initialize as layout_state
        from .scrolling import published_position
        logical_top = layout_state(app).scroll.get("jobs:details", 0)
        top = published_position(app, "workspace:jobs:details", logical_top) + previous["sticky"]
        raw = [index for index, position in previous["mapping"].items()
               if top - 16 <= position <= top + (height or 24) + 16]
        if raw:
            window = (max(0, min(raw) - previous["header"] - 16),
                      max(0, max(raw) - previous["header"] + 16))
    proxy.research_document_window = window or (0, max(32, (height or 24) + 32))
    from . import chart_interaction
    chart_mark = chart_interaction.mark(app)
    rows, hits = research_render(views, snap, proxy, width, MAX_ROWS)
    nav_rows = getattr(proxy, "research_nav_rows", 1)
    chart_interaction.place_since(app, chart_mark, dy=1 - nav_rows, clip=(1, 0, MAX_ROWS, width))
    retained.update(cursor=proxy.cursor.get("research", 0), array_open=proxy.research_array_open,
                    task_offset=proxy.research_task_offset)
    state["document_headers"][( _view_key(state), width)] = header_rows + 1
    content = [[(clean(f" Job {job.id} / {job.name}", views.g.ascii), "cyan+bold")]] + rows[nav_rows:MAX_ROWS + nav_rows]
    actions = [(y - nav_rows + 1, "job_panel_action", ((kind, value),
                value.get("left", 0) if kind == "control" and isinstance(value, dict) else 0,
                value.get("right", width) if kind == "control" and isinstance(value, dict) else width))
               for y, kind, value in hits if nav_rows <= y < nav_rows + MAX_ROWS]
    return content[:MAX_ROWS], actions


def _analytics(views, snap, app, job, width, height, state):
    proxy, retained = _scoped_app(app, job, state)
    proxy.analytics_document_mode = True
    scoped_views = copy.copy(views)
    # A finished job without session samples must never fall back to a running
    # job's chart. The ordinary Analytics workspace keeps its own cycling list.
    scoped_views.analytics_jobs = lambda current, target: [job.id]
    narrow_advisor = width < 120 and state["analytics_view"] == "advisor"
    if narrow_advisor:
        # The native table and the vertical cards need the same aggregation.
        # Building the clipped table before replacing it doubled the work over
        # the entire accounting history on every scrolling frame.
        scoped_views.analytics_advisor = lambda current, target, target_width, avail, days: _analytics_cards(
            views, current, target, None, width=target_width)
    from . import chart_interaction
    chart_mark = chart_interaction.mark(app)
    rows, hits = scoped_views.analytics_tab(snap, proxy, width, MAX_ROWS)
    nav_rows = getattr(proxy, "analytics_nav_rows", 1)
    if width < 120 and state["analytics_view"] == "compare":
        original = rows
        rows = rows[:nav_rows + 1] + _analytics_cards(views, snap, proxy, rows[nav_rows + 1:])
        # Replacing the compact comparison table with readable cards changes
        # the source rows below it. Keep pointer coordinates on those rows.
        cutoff = nav_rows + 3 + len(proxy.compare_ids[:6])
        delta = len(rows) - len(original)
        records = chart_interaction.take_since(app, chart_mark)
        chart_interaction.put_records(app, chart_interaction.map_records(
            records, lambda y: y + delta if y >= cutoff else None))
    chart_interaction.place_since(app, chart_mark, dy=1 - nav_rows, clip=(1, 0, MAX_ROWS, width))
    scope = "selected job" if state["analytics_view"] == "job" else "selected job + comparison set" if state["analytics_view"] == "compare" else "accounting window"
    content = [[(clean(f" Job {job.id} / {job.name} / {scope}", views.g.ascii), "cyan+bold")]] + rows[nav_rows:]
    actions = [(y - nav_rows + 1, "job_panel_action", ((kind, value),
                value.get("left", 0) if kind == "control" and isinstance(value, dict) else 0,
                value.get("right", width) if kind == "control" and isinstance(value, dict) else width))
               for y, kind, value in hits if y >= nav_rows]
    return content[:MAX_ROWS], actions


def _analytics_cards(views, snap, proxy, body, *, width=120):
    """Keep every requested/measured value when a wide table cannot fit."""
    from . import advisor, clock
    from .model import human, hms, secs, stamp
    row = lambda value, style="": [(clean(value, views.g.ascii), style)]
    if proxy.analytics_view == "advisor":
        now = clock.now()
        finished = [item for item in snap.get("finished", [])
                    if (stamp(item.end) or now) >= now - proxy.analytics_days_value() * 86400]
        advice = views.history_advice_cache.names(finished)
        if not advice and body is not None:
            return body
        if body is None:
            days = proxy.analytics_days_value()
            wasted = sum(item.wasted_core_hours for item in advice)
            rows = [L.rule(views.g, width,
                           f"advisor: what the jobs of the last {days:g} day{'s' if days != 1 else ''} should have asked for ({len(advice)} job names)"),
                    row(f"   {wasted:.1f} core-hours spent on idle cores over the window (1 - efficiency, times core-hours); suggestions keep {int(100 * (advisor.MEM_HEADROOM - 1))}% memory headroom and {int(100 * (advisor.TIME_HEADROOM - 1))}% time headroom over the worst run", "dim")]
        else:
            rows = body[:2]
        if not advice:
            rows.append(row("   nothing finished in the window", "dim"))
        for item in advice[:128]:
            rows.append(row(f" {item.name} / {item.id} runs", "bold"))
            rows.append(row(f" Memory peak {human(item.mem_peak) if item.mem_peak else '?'} / requested {human(item.mem_req) if item.mem_req else '?'} / suggested {item.mem_suggest or 'unchanged'}"))
            rows.append(row(f" CPU {item.cpus} / suggested {item.cpus_suggest or 'unchanged'} / efficiency {100 * item.cpu_eff:.0f}%" if item.cpu_eff is not None else f" CPU {item.cpus} / suggested {item.cpus_suggest or 'unchanged'} / efficiency unavailable"))
            rows.append(row(f" Time longest {hms(item.elapsed) if item.elapsed else '?'} / limit {hms(item.limit) if item.limit else '?'} / suggested {item.time_suggest or 'unchanged'}"))
            rows.append(row(f" Idle core-hours {item.wasted_core_hours:.1f} / notes {', '.join(item.notes) or 'none'}", "dim"))
            rows.append(row(" Flags " + (item.flags() or "nothing to change"), "cyan"))
        # Native running-job summaries clip their sentences to a table-sized
        # cell. Recompute the same published evidence as wrapped facts.
        running = [item for item in snap.get("jobs", []) if not item.pending]
        if running:
            rows.append(row(" Running jobs so far", "heading+bold"))
            by_name = views.history_advice_cache.groups(snap.get("finished", []))
            for item in running[:8]:
                observed = advisor.advise_running(item, snap.get("live", {}).get(item.id), proxy.store.series_of(item.id), by_name.get(item.name, ()))
                rows.append(row(f" {item.id} / {item.name}: {observed.summary(views.g.dot) or 'nothing to change yet'}", "cyan"))
        return rows
    ids = proxy.compare_ids[:6]
    jobs = {item.id: item for item in snap.get("jobs", [])}
    finished = {item.id: item for item in snap.get("finished", [])}
    rows = body[:1]
    for jid in ids:
        job, fin = jobs.get(jid), finished.get(jid)
        record = job or fin
        series = proxy.store.series_of(jid)
        live = [point for point in series if point.get("k") == "live"]
        cpu = [point.get("cpu") if point.get("cpu") is not None else point.get("eff") for point in live]
        cpu = [value for value in cpu if value is not None]
        rss = [point["rss"] for point in live if point.get("rss") is not None]
        gpu = [sum(value[0] for value in point["gpu"].values()) / len(point["gpu"])
               for point in series if point.get("k") == "gpu" and point.get("gpu")]
        elapsed = job.elapsed_s if job else secs(fin.elapsed) if fin else None
        cpus = getattr(record, "cpus", 0)
        requested = job.mem_bytes if job else fin.req_mem if fin else 0
        memory = max(rss) if rss else fin.rss if fin else None
        fraction = 100 * memory / requested if memory is not None and requested else None
        rows.append(row(f" Job {jid} / {getattr(record, 'name', '?')} / {getattr(record, 'state', '?')}", "cyan+bold"))
        rows.append(row(f" CPU {cpus} / mean {100 * sum(cpu) / len(cpu):.0f}% / max {100 * max(cpu):.0f}%" if cpu else f" CPU {cpus} / mean and max unavailable"))
        rows.append(row(" Peak memory " + (human(memory) if memory else "unavailable") + (f" / {fraction:.0f}% of request" if fraction is not None else " / fraction unavailable")))
        rows.append(row(f" GPU mean {sum(gpu) / len(gpu):.0f}%" if gpu else " GPU mean unavailable"))
        rows.append(row(f" Elapsed {hms(elapsed) if elapsed is not None else '?'} / core-hours {(elapsed or 0) * cpus / 3600:.1f} / samples {len(series)}", "dim"))
    # The remainder contains charts already scaled to the actual pane width.
    return rows + body[2 + len(ids):]


def _quick(views, app, job, width):
    """Render published diagnostics only; restored modes remain explicitly idle."""
    from . import clock, quick_advisor
    state = quick_advisor.initialize(app)
    if state.get("job") not in (None, job.id):
        quick_advisor.cancel(app)
    row = lambda text, style="": [(clean(text, views.g.ascii), style)]
    rows = [row(f" Job {job.id} / {job.name}", "cyan+bold")]
    hits = []

    def action(label, command):
        shown = L.cut(" " + label + " ", max(0, width), views.g.ascii)
        if shown:
            hits.append((len(rows), "job_panel_action", ((command, job.id), 0, L.vlen(shown))))
            rows.append(row(shown, "cyan+bold+bg:surface"))

    if state["status"] in ("queued", "loading"):
        action("Cancel analysis", "quick_cancel")
        size = max(0, min(62, width))
        tl, tr, bl, br, horizontal, vertical = views.g.box
        if size >= 4:
            title = L.cut(" Quick Advisor ", size - 4, views.g.ascii)
            rows.append(row(tl + title + horizontal * max(0, size - 2 - L.vlen(title)) + tr, "cyan+bold"))
            phase = int(clock.now() * 5) if getattr(app, "animations_enabled", False) else 0
            spinner = "|/-\\"[phase % 4] if views.g.ascii else "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[phase % 10]
            message = ("Waiting for the background reader" if state["status"] == "queued"
                       else "Reading the job's recorded evidence")
            content = L.cut(" " + spinner + " " + message, size - 2, views.g.ascii)
            rows.append([(vertical, "cyan"), (L.pad(content, size - 2), "secondary"), (vertical, "cyan")])
            track = max(1, min(24, size - 5))
            active = phase % track
            bar = ("=" if views.g.ascii else "█")
            empty = ("-" if views.g.ascii else "░")
            meter = " " + empty * active + bar + empty * (track - active - 1)
            rows.append([(vertical, "cyan"), (L.pad(meter, size - 2), "cyan+bold"), (vertical, "cyan")])
            rows.append(row(bl + horizontal * max(0, size - 2) + br, "cyan"))
        else:
            rows.append(row(" Analyzing...", "cyan"))
        rows.append(row(" Input and live updates remain available. No allocation is changed.", "dim"))
        return rows, hits
    result = state.get("result") if state["status"] == "ok" else None
    if result is None or result.get("job") != job.id:
        action("Analyze this job", "quick_refresh")
        if state["status"] == "error":
            rows.append(row(" Analysis unavailable: " + state.get("error", "Unknown reader error"), "yellow"))
        rows.append(row(" Select Analyze to combine Inspector, resource history and Advisor evidence.", "secondary"))
        rows.append(row(" Analysis runs only on request. A saved Quick Advisor tab does not start it.", "dim"))
        rows.append(row(" CPU phases / task RSS / time limits / GPU activity / comparable history", "cyan"))
        return rows, hits
    action("Refresh analysis", "quick_refresh")
    rows.append(row(" " + result["summary"], "heading+bold"))
    rows.append(row(f" Requested snapshot / {result['sample_count']:,} samples / {result['compatible_runs']} comparable run(s)", "dim"))
    rows.append(row(" Refresh explicitly to include newer samples. Arrows / wheel scroll this report.", "dim"))
    styles = {"good": "green", "risk": "red", "caution": "yellow", "unknown": "dim"}
    marks = {"good": "OK", "risk": "CHECK", "caution": "REVIEW", "unknown": "UNVERIFIED"}
    for section in result["sections"]:
        color = styles[section["status"]]
        rows.append(L.rule(views.g, width, section["name"]))
        rows.append(row(" " + marks[section["status"]] + " / " + section["title"], color + "+bold"))
        if section["values"]:
            rows.append([( " " + L.spark(views.g, section["values"], min(24, max(0, width - 3))), color)])
        rows.extend(row(" " + fact, "secondary") for fact in section["facts"])
        rows.append(row(" Next: " + section["action"], "cyan"))
    rows.append(L.rule(views.g, width, "Evidence limits"))
    rows.extend(row(" " + limitation, "dim") for limitation in result["limitations"])
    return rows[:MAX_ROWS], hits


def _content_action(app, target):
    """Dispatch explicit content actions in their exact-job rendering context."""
    state = initialize(app)
    kind, value = target
    if kind in ("quick_refresh", "quick_cancel"):
        if value != getattr(app, "selected_id", None) or state["mode"] != "quick":
            return False
        from . import quick_advisor
        if kind == "quick_refresh":
            quick_advisor.request(app)
        else:
            quick_advisor.cancel(app)
        return True
    if kind in ("inline_log", "inline_logs", "inline_evidence"):
        jid = value.get("job") if isinstance(value, dict) else value
        if jid != state.get("job") or jid != getattr(app, "selected_id", None):
            return False
        if kind == "inline_logs":
            app.open_log(jid)
        elif kind == "inline_evidence":
            _activate(app, "research", view="evidence")
        else:
            from .log_workbench import open_citation
            open_citation(app, value)
        return True
    retained = state["view_states"].get(_view_key(state), {})
    proxy = retained.get("proxy")
    if proxy is None or state.get("job") != getattr(proxy, "selected_id", None):
        return False
    if kind == "research_array":
        ids = [item["id"] for item in proxy.research_groups]
        if value in ids:
            retained.update(cursor=ids.index(value), task_offset=0,
                            array_open=not retained.get("array_open", False))
            state["focus"] = "content"
        return True
    if kind == "research_evidence":
        citation = proxy.research_evidence.get(value)
        if citation and citation.get("path"):
            from .log_workbench import open_citation
            # Opening a cited file is an explicit navigation action; the job
            # and path travel together through the normal full Logs interface.
            open_citation(app, citation)
        else:
            _say(app, "This citation is a scheduler observation with no log file attached.")
        return True
    if kind == "research_metric":
        from .analysis_ui import run_command
        run_command(proxy, ["chart", value])
    elif kind == "control" and isinstance(value, dict):
        action = value.get("action", ())
        if len(action) != 2 or action[0] != "command":
            return False
        proxy.run_command(action[1])
    else:
        return False
    if proxy.mode != "main":
        app.mode = proxy.mode
        app.analysis_state = proxy.analysis_state
        for name in ("analysis_result", "analysis_result_job", "analysis_result_generation", "research_evidence"):
            if hasattr(proxy, name):
                setattr(app, name, getattr(proxy, name))
        state["focus"] = ""
    return True


def render(views, snap, app, job, width, height=None):
    from . import chart_interaction
    chart_mark = chart_interaction.mark(app)
    state = initialize(app)
    rows, hits = _buttons(views.g, state, max(0, width))
    if state["job"] != getattr(job, "id", None):
        state.update(job=getattr(job, "id", None), file_id=None, entries=[])
        state["scrolls"].clear()
        state["view_states"].clear()
        state["document_windows"].clear()
        state["document_maps"].clear()
        from .workspace_layout import initialize as layout_state
        layout_state(app).scroll["jobs:details"] = 0
        if state["session"]:
            state["session"].top = None
    if getattr(app, "job_panel_defer_content", False):
        # The queue renderer resolves selection once before the independent
        # Details pane renders at its actual width. This placeholder neither
        # requests data nor constructs a second copy of its source document.
        return rows, hits
    if state["mode"] == "off":
        return rows, hits
    if job is None:
        return rows + [[(" Select an active or recent job to show its Details.", "dim")]], hits
    if state["mode"] == "logs":
        content, content_hits = _logs(views, snap, app, job, width, height, state)
        hits.extend((y + len(rows), kind, value) for y, kind, value in content_hits)
    elif state["mode"] == "investigate":
        content, content_hits = _evidence(views, snap, app, job, state, width)
        hits.extend((y + len(rows), kind, value) for y, kind, value in content_hits)
    elif state["mode"] == "research":
        content, content_hits = _research(views, snap, app, job, width, height, state, len(rows))
        hits.extend((y + len(rows), kind, value) for y, kind, value in content_hits)
    elif state["mode"] == "analytics":
        content, content_hits = _analytics(views, snap, app, job, width, height, state)
        hits.extend((y + len(rows), kind, value) for y, kind, value in content_hits)
    elif state["mode"] == "quick":
        content, content_hits = _quick(views, app, job, width)
        hits.extend((y + len(rows), kind, value) for y, kind, value in content_hits)
    else:
        content, content_hits = _inspector(views, snap, app, job, width, state)
        hits.extend((y + len(rows), kind, value) for y, kind, value in content_hits)
    chart_interaction.place_since(app, chart_mark, dy=len(rows), clip=(len(rows), 0, len(rows) + len(content), width))
    return rows + content, hits
