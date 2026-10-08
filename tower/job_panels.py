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
        ("investigate", "Investigate"), ("off", "Off"))
MODES = tuple(name for name, _ in TABS)
MAX_ROWS = 256
MAX_LOG_BYTES = 256 * 1024


def initialize(app):
    state = getattr(app, "job_panel_state", None)
    if not isinstance(state, dict):
        state = dict(mode="inspector", focus="", job=None, file_id=None,
                     entries=[], files=None, session=None, catalog=None)
        app.job_panel_state = state
    return state


def restore(app, data):
    state = initialize(app)
    if isinstance(data, dict) and data.get("mode") in MODES:
        state["mode"] = data["mode"]


def save(app):
    return {"mode": initialize(app)["mode"]}


def command_names():
    return ["jobpanel"]


def _say(app, message):
    callback = getattr(app, "say", None)
    if callable(callback):
        callback(message)


def _activate(app, mode, *, focus=True):
    state = initialize(app)
    if mode not in MODES:
        return False
    state["mode"], state["focus"] = mode, "tabs" if focus else ""
    from .workspace_layout import initialize as layout_state
    layout = layout_state(app)
    layout.scroll["jobs:details"] = 0
    if focus:
        layout.focus = "details"
    callback = getattr(app, "save", None)
    if callable(callback):
        callback()
    return True


def run_command(app, args):
    if not args or args[0] != "jobpanel":
        return False
    if args[1:] == ["focus"] or len(args) == 1:
        initialize(app)["focus"] = "tabs"
        _say(app, "Details tabs: arrows choose; Enter focuses content; Esc returns to jobs")
    elif len(args) == 2 and args[1] in MODES:
        _activate(app, args[1])
    else:
        callback = getattr(app, "fail", None)
        if callable(callback):
            callback("jobpanel [inspector|logs|investigate|off|focus]")
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
        state["focus"] = "content" if state["focus"] == "tabs" else "tabs"
        return True
    if state["focus"] == "tabs" and key in ("left", "right", "up", "down", "home", "end"):
        index = MODES.index(state["mode"])
        index = 0 if key == "home" else len(MODES) - 1 if key == "end" else (index + (-1 if key in ("left", "up") else 1)) % len(MODES)
        _activate(app, MODES[index])
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
        if row != y or kind not in ("job_panel_tab", "job_panel_file"):
            continue
        target, left, right = value
        if left <= x < right:
            if button == "left":
                if kind == "job_panel_tab":
                    _activate(app, target)
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
    return rows, hits


def _inspector(views, snap, app, job, width, state):
    """Reuse the unified inspector without changing its modal selection."""
    from .analysis_ui import SECTIONS, _inspector_rows
    proxy = copy.copy(app)
    proxy.analysis_state = dict(job=job.id, evidence_job=job.id)
    proxy.log_job, proxy.logs = job.id, SimpleNamespace(entries=list(state.get("entries", [])))
    proxy.research_evidence = state.get("evidence", {}) if state.get("evidence_job") == job.id else {}
    # Keep the queue's measured scientific diagnostics: the unified inspector
    # alone does not include dependency blockers, rank imbalance, GPU traces,
    # live GPU samples, or the selected job's tags and note.
    active = any(record.id == job.id for record in snap.get("jobs", []))
    rows = [[(" Live summary" if active else "Recent summary", "heading+bold")],
            [(clean(f" Job {job.id}  {job.name}", views.g.ascii), "cyan+bold")]]
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
        content = _inspector_rows(views.g, snap, proxy, width)[1:]
        content = content[2:]
        rows.extend(content)
    return rows[:MAX_ROWS]


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
        lines, first = buf.window(session.top, page)
        rows.append(row(f" {'Following' if session.top is None else 'Paused'} / retained lines {first + 1 if lines else 0}-{first + len(lines)} of {buf.total}"
                        + (" / earlier bytes omitted" if buf.truncated else ""), "dim"))
        rows.extend(L.clip_row(row(line), width) for line in lines)
        if not lines:
            rows.append(row(" This log is empty.", "dim"))
    return rows, hits


def _evidence(views, snap, app, job, state):
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
        rows.append(row(f" [{item['id']}] {item.get('source', '')} / {item.get('path') or item.get('location', '')}", "cyan"))
        rows.append(row(" " + item.get("text", ""), "dim"))
    for limitation in result.get("limitations", [])[:12]:
        rows.append(row(" Unverified: " + str(limitation), "dim"))
    return rows[:MAX_ROWS]


def render(views, snap, app, job, width, height=None):
    state = initialize(app)
    rows, hits = _buttons(views.g, state, max(0, width))
    if state["job"] != getattr(job, "id", None):
        state.update(job=getattr(job, "id", None), file_id=None, entries=[])
        if state["session"]:
            state["session"].top = None
    if state["mode"] == "off":
        return rows, hits
    if job is None:
        return rows + [[(" Select an active or recent job to show its Details.", "dim")]], hits
    if state["mode"] == "logs":
        content, content_hits = _logs(views, snap, app, job, width, height, state)
        hits.extend((y + len(rows), kind, value) for y, kind, value in content_hits)
    elif state["mode"] == "investigate":
        content = _evidence(views, snap, app, job, state)
    else:
        content = _inspector(views, snap, app, job, width, state)
    return rows + content, hits
