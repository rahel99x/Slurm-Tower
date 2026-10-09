"""Mouse range selection of exact job IDs for existing marked-job actions."""
from __future__ import annotations

MAX_SELECTION = 50000
ROW_KINDS = {"jobs": {"job", "recent"}, "history": {"fin"},
             "group": {"group"}, "deps": {"dep"}}
JOB_SCOPES = ("jobs", "history", "group", "deps", "analytics", "research", "log")


def initialize(app):
    if not isinstance(getattr(app, "job_selection_state", None), dict):
        app.job_selection_state = {"capture": None}
    app.job_selection_state.setdefault("deselected", {})
    app.job_selection_state.setdefault("lines_deselected", False)
    return app.job_selection_state


def selected(app, tab, identifier):
    """Keep an explicitly cleared table clear across maintenance frames."""
    return None if initialize(app)["deselected"].get(tab, False) else identifier


def resume(app, tab=None):
    initialize(app)["deselected"][tab or getattr(app, "tab", "")] = False


def cleared(app, tab=None):
    return bool(initialize(app)["deselected"].get(tab or getattr(app, "tab", ""), False))


def lines_cleared(app):
    return bool(initialize(app)["lines_deselected"])


def resume_lines(app):
    """A deliberate line gesture restores its cursor without selecting a job."""
    initialize(app)["lines_deselected"] = False


def clear_lines(app):
    """Clear text and log cursors without changing job or dialog ownership."""
    from .text_selection import clear as clear_text
    clear_text(app)
    state = initialize(app)
    state["lines_deselected"] = True
    app.sel_anchor = app.click_row = None
    app.sel_end = 0
    app.log_selection_expected = False
    logs = getattr(app, "logs", None)
    if logs is not None:
        logs.clear_selection(reset_cursor=True)
        logs.match = None
    session = getattr(app, "job_panel_state", {}).get("session")
    if session is not None and session is not logs:
        session.clear_selection(reset_cursor=True)
        session.match = None
    log_workbench = getattr(app, "log_workbench_state", None)
    if isinstance(log_workbench, dict):
        log_workbench["citation"] = None
    log_tools = getattr(app, "log_tools_state", None)
    if isinstance(log_tools, dict):
        log_tools.update(selection=None, cursor_deselected=True)


def clear(app):
    state = initialize(app)
    state["capture"] = None
    state["deselected"].update(dict.fromkeys(JOB_SCOPES, True))
    app.marks.clear()
    app.selected_id = None
    clear_lines(app)
    pointer = getattr(app, "interaction_state", {})
    pointer.update(active=False, focused=None, frame_required=True)
    getattr(app, "job_panel_state", {})["focus"] = ""
    if app.tab in ("jobs", "history"):
        from .job_panels import focus_main
        focus_main(app)
    from . import chart_interaction, metric_live, pane_drag
    chart_interaction.cancel(app)
    metric_live.cancel(app)
    pane_drag.cancel(app)
    toolbar = getattr(app, "toolbar_state", None)
    if isinstance(toolbar, dict):
        toolbar.update(dragging=False, pressed=False, drag_width=None)
    history = getattr(app, "history_browser_state", None)
    if isinstance(history, dict):
        history.update(drag=None, focused=False, last_selected=None)
        for view in history.get("views", {}).values():
            if isinstance(view, dict):
                view.update(selected=None, explicit=False)
    app.say("Selections cleared; click a job or line to select again")


def context_click(app, y, x, button="left"):
    """A graph or History export owns right-click; all other pages clear."""
    if button != "right":
        return False
    if any(type(value) is not int for value in (y, x)):
        return False
    if not (0 <= x < getattr(app, "width", 120)
            and 0 <= y < getattr(app, "height", 100000)):
        return False
    mode = getattr(app, "mode", "main")
    if mode in ("log_tools_page", "log_tools_results", "log_tools_marks"):
        # The modal keeps its own source and control ownership. Its clear must
        # precede the global toolbar so even a top-row right-click is inert.
        from .log_tools import handle_mouse
        return handle_mouse(app, y, x, button=button)
    if mode in ("help", "details", "analysis"):
        from . import chart_interaction
        if mode == "analysis" and chart_interaction.handle_mouse(app, y, x, button=button):
            return True
        clear_lines(app)
        chart_interaction.cancel(app)
        if mode == "analysis":
            from .analysis_ui import context_click as analysis_context
            if analysis_context(app, y, x, button=button):
                return True
        app.say("Text selection cleared; dialog remains open")
        return True
    if mode != "main":
        return False
    tab = getattr(app, "tab", "")
    from .chart_interaction import handle_mouse as chart_mouse
    if chart_mouse(app, y, x, button=button):
        return True
    if tab == "history":
        rect = getattr(app, "history_jobs_rect", None)
        if rect is not None and rect.contains(y, x):
            from .history_log_export import handle_mouse
            return handle_mouse(app, y, x, button=button)
    clear(app)
    return True


def publish(app, rows, hits, width, height):
    """Publish the clipped History list, excluding summaries and Details."""
    app.history_jobs_rect = None
    if getattr(app, "tab", "") != "history" or height is None:
        return
    from .interaction import Rect
    from .workspace_layout import enabled, _section_title
    headers = [y for y, kind, value in hits if kind == "sort_header"
               and isinstance(value, (tuple, list)) and value[:1] == ("history",)]
    records = [y for y, kind, value in hits if kind == "fin"]
    if not headers and not records:
        return
    left, right, bottom = 0, width, max(0, height - 1)
    top = max(0, min(headers) - 1 if headers else min(records))
    native = isinstance(getattr(app, "job_panel_state", None), dict)
    main = getattr(app, "workspace_main_rect", None) if enabled(app) or native else None
    if main is not None:
        left, right = main.x, min(width, main.x + main.width)
        top, bottom = max(top, main.y), min(bottom, main.y + main.height)
    else:
        last = max(records) if records else max(headers)
        for y in range(last + 1, min(len(rows), bottom)):
            title = _section_title(rows[y])
            if title and title.startswith(("selected", "details")):
                bottom = y
                break
    if top < bottom and left < right:
        app.history_jobs_rect = Rect(top, left, bottom, right)


def command_names():
    return []


def run_command(app, args):
    return False


def overlay(views, snap, app, width, height):
    return None


def _order(app):
    tab = getattr(app, "tab", "")
    if tab == "jobs":
        return tuple((list(getattr(app, "visible_ids", [])) + list(getattr(app, "recent_ids", [])))[:MAX_SELECTION])
    if tab == "history":
        cached = getattr(app, "last_history_ids", None)
        if isinstance(cached, (list, tuple)):
            return tuple(cached[:MAX_SELECTION])
        return tuple(record.id for record in app.history_jobs())[:MAX_SELECTION]
    return tuple(getattr(app, "group_ids" if tab == "group" else "dep_ids", []))[:MAX_SELECTION]


def _hit(app, y, x):
    if any(type(value) is not int for value in (y, x)):
        return None
    if not (0 <= x < getattr(app, "width", 120)
            and 0 <= y < getattr(app, "height", 100000)):
        return None
    if getattr(app, "tab", "") in ("jobs", "history"):
        from .job_panels import contains
        if contains(app, y, x):
            return None
    if getattr(app, "tab", "") == "history":
        rect = getattr(app, "history_jobs_rect", None)
        if rect is not None and not rect.contains(y, x):
            return None
    kinds = ROW_KINDS.get(getattr(app, "tab", ""), set())
    return next((identifier for row, kind, identifier in getattr(app, "last_hits", [])
                 if row == y and kind in kinds and isinstance(identifier, str)), None)


def active(app):
    return bool(initialize(app)["capture"])


def _valid(app, capture):
    return (getattr(app, "mode", "main") == "main" and app.tab == capture["tab"]
            and getattr(app, "toolbar_state", {}).get("menu") is None
            and not getattr(app, "toolbar_state", {}).get("panel")
            and (getattr(app, "width", None), getattr(app, "height", None)) == capture["size"]
            and _order(app) == capture["ids"])


def tick(app):
    state = initialize(app)
    if state["capture"] and not _valid(app, state["capture"]):
        state["capture"] = None


def handle_key(app, key):
    state = initialize(app)
    capture = state["capture"]
    if capture:
        state["capture"] = None
        if key == "esc":
            app.marks = set(capture["base"])
            app.say("Drag selection cancelled")
            return True
    return False


def _range(app, capture, identifier):
    ids = capture["ids"]
    if identifier not in ids:
        return
    first, last = sorted((ids.index(capture["anchor"]), ids.index(identifier)))
    app.marks = (set(capture["base"]) if capture["extend"] else set()) | set(ids[first:last + 1])
    capture["moved"] = True
    resume(app)
    app.cursor[app.tab] = ids.index(identifier)
    # The exact published order was validated above. Rebuilding accounting or
    # taking a Store snapshot for each pointer report adds no selection safety.
    app.selected_id = identifier
    app.say(f"{len(app.marks)} jobs marked; drag to adjust, release to finish")


def handle_mouse(app, y, x, button="left", shift=False):
    state = initialize(app)
    capture = state["capture"]
    if any(type(value) is not int for value in (y, x)):
        state["capture"] = None
        return bool(capture)
    if capture:
        if not _valid(app, capture):
            state["capture"] = None
            return button in ("release", "motion", "drag")
        if button in ("motion", "drag", "release"):
            identifier = _hit(app, y, x)
            # Runtime status or auto-link headers may move the table while the
            # pointer stays still. Only vertical pointer movement chooses a
            # new endpoint; release retains the last deliberately marked ID.
            if (identifier and y != capture["point"][0]
                    and (identifier != capture["anchor"] or capture["moved"])):
                _range(app, capture, identifier)
            if identifier:
                capture["point"] = (y, x)
            if button == "release":
                state["capture"] = None
                if capture["moved"]:
                    app.say(f"{len(app.marks)} jobs marked; use the existing job action and review the group")
            return True
        if button in ("left", "press"):
            state["capture"] = None
        else:
            return False
    if (button != "press" or getattr(app, "mode", "main") != "main"
            or getattr(app, "toolbar_state", {}).get("menu") is not None
            or getattr(app, "toolbar_state", {}).get("panel")
            or getattr(app, "tab", "") not in ROW_KINDS):
        return False
    identifier = _hit(app, y, x)
    ids = _order(app)
    if identifier not in ids:
        return False
    state["capture"] = {"tab": app.tab, "anchor": identifier, "ids": ids,
                        "base": set(app.marks), "extend": bool(shift), "moved": False,
                        "point": (y, x), "size": (getattr(app, "width", None), getattr(app, "height", None))}
    # A press retains ordinary row selection. Marks change only on a range drag.
    resume(app)
    if app.tab in ("jobs", "history"):
        from .job_panels import focus_main
        focus_main(app)
    app.cursor[app.tab] = ids.index(identifier)
    app.selected_id = identifier
    return True
