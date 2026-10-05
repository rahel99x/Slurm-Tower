"""Bounded, identity-aware navigation and the searchable Research workspace picker.

The controller records a location before changing tabs or opening another job's
logs. Returning restores the view, rather than replaying an action or retaining
an obsolete visual selection. No scheduler or file reads happen here.
"""
from __future__ import annotations

import copy
import os

from .layout import box, clip_row, cut
from .research import RESEARCH_VIEWS, clean

MAX_BACK = 32
TAB_NAMES = {"jobs": "Jobs", "cluster": "Cluster", "history": "History", "analytics": "Analytics",
             "nodes": "Nodes", "group": "Group", "deps": "Deps", "log": "Logs", "sources": "Sources", "research": "Research"}
WORKSPACE_INFO = {
    "experiment": "Live metrics, progress and application events",
    "arrays": "Task outcomes, failed indices and selective retries",
    "evidence": "Scheduler, application logs and failure evidence",
    "artifacts": "Declared outputs, validation and previews",
    "passport": "Reproducibility records and run comparisons",
    "submit": "Prepare and review a batch submission",
    "predict": "Resource recommendations from comparable runs",
    "forecast": "Scheduler estimates and calibrated intervals",
    "blockers": "Why a pending job is waiting",
    "tradeoffs": "Resource alternatives and explicit tradeoffs",
    "scaling": "Scaling analysis, experiments and results",
    "workflow": "Dependency graphs, execution and recovery",
}


def initialize(app):
    if not isinstance(getattr(app, "navigation_state", None), dict):
        app.navigation_state = {"stack": [], "restoring": False, "pending_target": None,
                                "query": "", "picker_cursor": 0, "picker_top": 0, "picker_page": 8}
    return app.navigation_state


def restore(app, data):
    # Back history is intentionally session-local: a saved job/path may describe
    # another cluster after switching profiles. The picker preference is harmless.
    state = initialize(app)
    data = data if isinstance(data, dict) else {}
    state["query"] = str(data.get("query", ""))[:256] if isinstance(data.get("query", ""), str) else ""


def save(app):
    return {"query": initialize(app)["query"][:256]}


def command_names():
    return ["back", "workspaces", "workspace"]


def _bounded_map(value):
    return {str(k)[:64]: max(0, min(v, 10**9)) for k, v in value.items()
            if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)} if isinstance(value, dict) else {}


def location(app):
    """Capture explicit identities, filters, and scroll positions; never buffers."""
    fields = ("tab", "mode", "selected_id", "detail_id", "filter", "research_view", "research_job_id", "research_scroll",
              "analytics_view", "analytics_job", "nodes_view", "log_job", "days_index")
    result = {name: getattr(app, name, None) for name in fields}
    result.update(cursor=_bounded_map(app.cursor), top=_bounded_map(app.top),
                  sort=dict(app.sort), reverse=dict(app.reverse))
    logs = app.logs
    result["logs"] = {name: getattr(logs, name, None) for name in
                      ("path", "which", "file_index", "top", "cursor", "search", "wrap", "_buffer_token",
                       "browser", "browse_return", "browser_cursor", "browser_top", "file_filter")}
    result["logs"]["entry"] = copy.deepcopy(logs.entry)
    result["logs"]["entries"] = copy.deepcopy(logs.entries[:512])
    table = getattr(app, "table_state", None)
    if isinstance(table, dict):
        result["table_context"] = {field: copy.deepcopy(table.get(field)) for field in ("facets", "groups", "collapsed")}
    layout = getattr(app, "layout_state", None)
    if layout is not None:
        result["panel_context"] = {field: copy.deepcopy(getattr(layout, field, None)) for field in ("focus", "maximized", "scroll")}
    log_workbench = getattr(app, "log_workbench_state", None)
    if isinstance(log_workbench, dict):
        result["log_view_context"] = {field: copy.deepcopy(log_workbench.get(field)) for field in ("view", "pan", "scroll", "collapsed", "preview", "current_group")}
    analysis = getattr(app, "analysis_state", None)
    if isinstance(analysis, dict):
        result["analysis_context"] = {field: copy.deepcopy(analysis.get(field)) for field in
                                      ("modal", "cursor", "scroll", "section", "job", "metric", "chart_job", "zoom", "pan", "window", "diff_kind", "diff_ids", "unchanged", "evidence_cursor", "evidence_focus", "modal_back")
                                      if field in analysis}
        # Loaded comparisons are immutable results. Retain their reference
        # rather than duplicate potentially large passports in back history.
        result["analysis_context"]["comparison"] = analysis.get("comparison")
    project = getattr(app, "project_state", None)
    if isinstance(project, dict):
        result["project_context"] = {field: copy.deepcopy(project.get(field)) for field in
                                     ("root", "binding", "logs", "run_warnings", "restore_run_id", "summary", "status", "run_cursor", "run_top", "output_cursor", "output_top", "filter")}
        for field in ("runs", "warnings"):
            result["project_context"][field] = project.get(field, [])
        backup = project.get("binding_backup")
        result["project_context"]["binding_backup"] = dict(backup) if isinstance(backup, dict) else None
    hub = app.research
    settings = hub.settings if hub is not None else app.cfg.get("research", {})
    result["research_settings"] = {key: settings.get(key, "") for key in ("metrics_file", "contract", "workdir", "passport", "planning_file")}
    result["log_manifest"] = app.cfg.get("logs", {}).get("manifest_file", "")
    result["passport_context"] = (getattr(hub, "passport", None), getattr(hub, "passport_diff", None))
    return result


def record(app, target_tab=None, *, force=False):
    """Hook before a tab change, or before open_log mutates the old location.

    open_log and enter_tab can both call this hook. A pending target prevents
    the latter from recording the intermediate, partially changed log state.
    """
    state = initialize(app)
    if state["restoring"] or target_tab == app.tab and not force:
        return False
    if not force and state.get("pending_target") == target_tab and state["stack"] and state["stack"][-1]["tab"] == app.tab:
        return False
    state["stack"].append(location(app))
    del state["stack"][:-MAX_BACK]
    state["pending_target"] = target_tab
    return True


def _restore_location(app, saved):
    state = initialize(app)
    state["restoring"] = True
    try:
        app.tab = saved["tab"]
        app.filter = saved.get("filter", "")
        app.cursor.update(saved.get("cursor", {}))
        app.top.update(saved.get("top", {}))
        app.sort.update(saved.get("sort", {}))
        app.reverse.update(saved.get("reverse", {}))
        if isinstance(getattr(app, "table_state", None), dict):
            app.table_state.update(copy.deepcopy(saved.get("table_context", {})))
        if getattr(app, "layout_state", None) is not None:
            for field, value in saved.get("panel_context", {}).items():
                setattr(app.layout_state, field, copy.deepcopy(value))
        if isinstance(getattr(app, "log_workbench_state", None), dict):
            app.log_workbench_state.update(copy.deepcopy(saved.get("log_view_context", {})))
        if isinstance(getattr(app, "analysis_state", None), dict) and saved.get("analysis_context"):
            app.analysis_state.update(saved["analysis_context"])
        project = getattr(app, "project_state", None)
        project_changed = False
        if isinstance(project, dict) and saved.get("project_context") is not None:
            context = saved["project_context"]
            project_changed = (project.get("root"), project.get("binding")) != (context.get("root"), context.get("binding"))
            project["generation"] = project.get("generation", 0) + 1
            project["busy"] = False
            project.update(context)
            if project.get("binding_backup") is None:
                project.pop("binding_backup", None)
            project["tree"], project["preview"] = None, None
        app.cfg["logs"]["manifest_file"] = saved.get("log_manifest", "")
        if app.research is not None and saved.get("research_settings") is not None:
            settings = saved["research_settings"]
            if project_changed or any(app.research.settings.get(key, "") != value for key, value in settings.items()):
                app.research.configure(**settings)
            app.research.passport, app.research.passport_diff = saved.get("passport_context", (None, None))
        for field in ("research_view", "research_job_id", "research_scroll", "analytics_view", "analytics_job", "detail_id",
                      "nodes_view", "log_job", "selected_id"):
            if field in saved:
                setattr(app, field, saved[field])
        if isinstance(saved.get("days_index"), int) and saved["days_index"] != app.days_index:
            app.set_days(saved["days_index"])
        app.mode = "analysis" if saved.get("mode") == "analysis" and saved.get("analysis_context") else "main"
        app.sel_anchor, app.click_row = None, None
        app.logs.clear_selection(reset_cursor=True)
        app.log_selection_expected, app.log_render_token = False, None
        log_state = saved.get("logs", {})
        for field, value in log_state.items():
            # The token contains the log session's opaque identity marker.
            # Its immutable tuple must keep that exact marker, while mutable
            # file-browser metadata remains isolated from the saved location.
            setattr(app.logs, field, value if field == "_buffer_token" else copy.deepcopy(value))
        app.logs.candidates.clear()
        app.log_record = app.job_record(app.log_job) if app.log_job else None
        # If the buffer is still retained, its identity token is valid and the
        # saved scroll can be used. A replaced/evicted file will invalidate it
        # through the normal LogSession buffer synchronization.
        app.logs.match, app.logs.last_bookmark = None, None
        app.jobs_selection_options = None
        app.last_history_options = None
        jid = saved.get("selected_id")
        if app.tab == "jobs" and app.views_ref is not None:
            snap = app.store.snapshot()
            app.visible_ids = [row["id"] for row in app.views_ref.job_rows(snap, app, app.actions)]
            app.recent_ids = [job.id for job in app.recent_jobs(snap)]
            ids = app.visible_ids + app.recent_ids
            if jid in ids:
                app.cursor["jobs"] = ids.index(jid)
            app.last_jobs_ids = ids
            app.jobs_selection_options = app.jobs_options()
        elif app.tab == "history":
            ids = [job.id for job in app.history_jobs()]
            if jid in ids:
                app.cursor["history"] = ids.index(jid)
            app.last_history_ids = ids
            if hasattr(app, "completion"):
                app.completion.acknowledge()
        app.sync_selection()
    finally:
        state["restoring"], state["pending_target"] = False, None


def back(app):
    state = initialize(app)
    if not state["stack"]:
        app.say("Already at the first location; Tab switches pages, :workspaces opens Research")
        return False
    saved = state["stack"].pop()
    _restore_location(app, saved)
    app.say("Back to " + TAB_NAMES.get(app.tab, app.tab))
    return True


def breadcrumb(app, width, ascii_=False):
    """A concise, clipped path; source labels never inject terminal controls."""
    state = initialize(app)
    parts = []
    previous = next((saved for saved in reversed(state["stack"]) if saved["tab"] != app.tab), None)
    if previous:
        parts.append(TAB_NAMES.get(previous["tab"], previous["tab"]))
    parts.append(TAB_NAMES.get(app.tab, app.tab))
    jid = app.log_job if app.tab == "log" else app.research_job_id if app.tab == "research" else app.selected_id
    if jid and app.tab in ("log", "research", "analytics", "history", "jobs"):
        parts.append("job " + clean(jid, ascii_, limit=128))
    if app.tab == "research":
        parts.append(dict(RESEARCH_VIEWS).get(app.research_view, app.research_view))
    elif app.tab == "analytics":
        parts.append(app.analytics_view.replace("_", " "))
    elif app.tab == "log":
        if app.logs.browser:
            parts.append("Files")
        elif app.logs.entry or app.logs.path:
            entry = app.logs.entry or {}
            parts.append(clean(entry.get("label") or os.path.basename(app.logs.path), ascii_, limit=256))
    sep = " > " if ascii_ else " › "
    return clip_row([(" " + sep.join(parts), "dim"), ("   :back", "cyan") if state["stack"] else ("", "")], max(0, width))


def _workspaces(app):
    query = initialize(app)["query"].strip().casefold()
    return [(key, label, WORKSPACE_INFO.get(key, "Research workspace")) for key, label in RESEARCH_VIEWS
            if not query or all(word in (key + " " + label + " " + WORKSPACE_INFO.get(key, "")).casefold()
                                for word in query.split())]


def _open_workspace(app, key):
    if app.tab == "research" and key != app.research_view:
        record(app, "research", force=True)
    app.enter_tab("research")
    app.research_view, app.research_scroll = key, 0
    app.mode = "main"
    app.say("Research: " + dict(RESEARCH_VIEWS).get(key, key))


def run_command(app, args):
    if not args or args[0] not in command_names():
        return False
    cmd, words = args[0], args[1:]
    if cmd == "back":
        if words:
            app.fail("usage: back")
        else:
            back(app)
        return True
    state = initialize(app)
    if cmd == "workspace" and words:
        query = " ".join(words).casefold()
        matches = [key for key, label in RESEARCH_VIEWS if query in (key.casefold(), label.casefold())]
        if matches:
            _open_workspace(app, matches[0])
            return True
    state.update(query=" ".join(words)[:256], picker_cursor=0, picker_top=0)
    app.mode = "workspace_picker"
    return True


def handle_key(app, key):
    state = initialize(app)
    if app.mode == "main" and key in ("alt-left", "ctrl-b"):
        back(app)
        return True
    if app.mode == "main" and key == "ctrl-p":
        run_command(app, ["workspaces"])
        return True
    if app.mode != "workspace_picker":
        return False
    rows = _workspaces(app)
    index, page = state["picker_cursor"], state["picker_page"]
    if key in ("esc",):
        app.mode = "main"
    elif key == "enter":
        if rows:
            _open_workspace(app, rows[max(0, min(index, len(rows) - 1))][0])
    elif key in ("up", "down", "pgup", "pgdn", "home", "end"):
        state["picker_cursor"] = max(0, min(max(0, len(rows) - 1),
            {"up": index - 1, "down": index + 1, "pgup": index - page, "pgdn": index + page,
             "home": 0, "end": len(rows) - 1}[key]))
    elif key == "backspace":
        state.update(query=state["query"][:-1], picker_cursor=0, picker_top=0)
    elif key == "space" or len(key) == 1 and key.isprintable():
        state.update(query=(state["query"] + (" " if key == "space" else key))[:256], picker_cursor=0, picker_top=0)
    return True


def handle_mouse(app, y, x, button="left", shift=False):
    if app.mode != "workspace_picker":
        return False
    state = initialize(app)
    if button == "left":
        index = next((index for row, index in state.get("picker_hits", []) if row == y), None)
        if index is not None:
            state["picker_cursor"] = index
    return True


def overlay(views, snap, app, width, height):
    if app.mode != "workspace_picker":
        return None
    state = initialize(app)
    entries = _workspaces(app)
    page = max(1, height - 9)
    state["picker_page"] = page
    cur = max(0, min(state["picker_cursor"], max(0, len(entries) - 1)))
    top = min(state["picker_top"], max(0, len(entries) - page))
    if cur < top:
        top = cur
    elif cur >= top + page:
        top = cur - page + 1
    state.update(picker_cursor=cur, picker_top=top)
    lines = [[(" Find a workspace: ", "dim"), (clean(state["query"], views.g.ascii) or "(type to search)", "cyan")], [("", "")]]
    for index, (_, label, desc) in enumerate(entries[top:top + page], top):
        style = "sel" if index == cur else ""
        marker = "> " if views.g.ascii else "› "
        lines.append([((marker if index == cur else "  ") + label + "  ", style),
                      (cut(desc, max(0, width - len(label) - 15), views.g.ascii), style or "dim")])
    if not entries:
        lines.append([(" No workspace matches. Backspace clears the search.", "yellow")])
    lines += [[("", "")], [(f" {len(entries)} workspaces  Up/Down choose  Enter opens  Esc closes", "dim")]]
    result = box(views.g, lines, width, height, "Research workspaces")
    state["picker_hits"] = [(result[index + 3][0], top + index) for index in range(min(page, len(entries) - top))
                            if index + 3 < len(result) - 1]
    return result
