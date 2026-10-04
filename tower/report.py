"""A complete portable dashboard report, rendered entirely as ASCII terminal text.

The interactive Views remain the single source of tables and charts. Rendering
uses isolated UI state so exporting never changes the user's current screen.
"""
from __future__ import annotations

import copy
import textwrap
import time
from typing import List

from . import clock, layout
from .controller import KEY_LABELS_ASCII
from .views import ANALYTICS_VIEWS, TABS
from .research import RESEARCH_VIEWS


_TRANSLATE = str.maketrans({"\u00b7": ".", "\u2026": "...", "\u2192": "->", "\u2190": "<-", "\u2013": "-", "\u2014": "--", "\u00d7": "x"})


def ascii_text(value) -> str:
    """Keep printable ASCII; make Unicode and terminal controls visible, harmless text."""
    text = str(value).translate(_TRANSLATE).replace("\t", "    ")
    return "".join(ch if " " <= ch <= "~" else ch.encode("unicode_escape").decode("ascii") for ch in text)


def _render(rows, width: int) -> str:
    clean = [[(ascii_text(text), "") for text, _ in row] for row in rows]
    return layout.to_text(clean, width, color=False)


def _ui_copy(obj):
    """Copy mutable UI containers while retaining services, configuration and store bindings."""
    result = copy.copy(obj)
    for key, value in vars(obj).items():
        if isinstance(value, (dict, list, set)):
            setattr(result, key, copy.copy(value))
    return result


def build(snap: dict, app, views, actions=None, title: str = "", width: int = 132) -> str:
    """All dashboard pages, analytics and node subviews, as a bounded-width ASCII report.

    The report includes every snapshot row and available recorded job series;
    log output is the selected log's current 40-line window. Screen filters are
    cleared only on the private copy, ensuring a full report without losing the
    caller's filter, selection, marks, glyph mode, scroll positions or log state.
    """
    width = max(60, min(240, int(width)))
    local = _ui_copy(app)
    display = _ui_copy(views)
    display.g = layout.Glyphs(True)
    local.labels = KEY_LABELS_ASCII
    local._ascii_cfg = True
    local.views_ref = display
    local.filter = ""
    local.filter_edit = ""
    local.log_lines = 0
    local.cursor = {key: 0 for key, _ in TABS}
    local.top = {key: 0 for key, _ in TABS}
    local.logs = _ui_copy(app.logs)
    local.logs.browser = False
    # A new buffer cache avoids mutating the interactive reader or copying its
    # potentially large retained files. The normal bounded file reader is reused.
    local.logs.buffers = {}
    selected_log = app.log_job or app.selected_id
    now = clock.now()
    generated = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(now))
    who = ascii_text(app.user)
    if getattr(app, "host_label", ""):
        who += " @ " + ascii_text(app.host_label)
    border = "=" * width
    out: List[str] = [border, ascii_text(title or "SLURM TOWER | COMPLETE TERMINAL REPORT")[:width], border,
                      f"Snapshot: {generated}"[:width], f"User: {who}"[:width]]
    if snap.get("account", {}).get("account"):
        out.append("Account: " + ascii_text(snap["account"]["account"]))
    if getattr(app, "demo", False):
        out.append("[DEMO] Simulated cluster data. No live cluster connection.")
    out.extend(textwrap.wrap("Ten dashboard pages, ASCII charts, job series, node maps, research evidence and source diagnostics. This is a fixed snapshot; unmeasured values remain unavailable.", width))
    out.extend(textwrap.wrap("All jobs are included regardless of the screen filter. Tables and charts fit this report's width. The Log page contains one 40-line window of the selected log; it is not the whole file.", width))
    out.extend(["", "CONTENTS", "  01 Jobs        02 Cluster       03 History       04 Analytics",
                "  05 Nodes       06 Group         07 Dependencies  08 Log",
                "  09 Sources     10 Research      11 Event journal", ""])

    def heading(text: str):
        out.extend(["", border, ascii_text(text)[:width], border])

    def rows(rendered):
        out.append(_render(rendered, width))

    def page(number: int, key: str, label: str):
        heading(f"{number:02d} / {label.upper()}")
        local.tab = key
        rendered, _ = display.compose(snap, local, width, None, actions)
        rows(rendered)

    page(1, "jobs", "Jobs")
    selected_job = local.selected_id
    for job in snap["jobs"]:
        if job.id != selected_job:
            rows([layout.rule(display.g, width, f"job detail: {job.id}")])
            rows(display.selected_panel(snap, job, width, 0, local))
    page(2, "cluster", "Cluster")
    page(3, "history", "History")
    if not snap["finished"]:
        out.append("No completed runs in this snapshot. Accounting history appears when available.")

    local.analytics_view = "job"
    page(4, "analytics", "Analytics")
    first_series = local.analytics_job
    for jid in display.analytics_jobs(snap, local):
        if jid != first_series:
            local.analytics_job = jid
            rows(display.analytics_job(snap, local, width, None))
    for key, label in ANALYTICS_VIEWS:
        if key != "job":
            rows([layout.rule(display.g, width, f"analytics / {label}")])
            local.analytics_view = key
            rendered, _ = display.analytics_tab(snap, local, width, None)
            rows(rendered)

    local.nodes_view = "mine"
    page(5, "nodes", "Nodes")
    local.nodes_view = "map"
    rendered, _ = display.nodes_tab(snap, local, width, None)
    rows(rendered)
    page(6, "group", "Group")
    page(7, "deps", "Dependencies")
    local.log_job = selected_log or selected_job
    page(8, "log", "Log")
    page(9, "sources", "Sources")
    for health in sorted(snap.get("health", {}).values(), key=lambda h: h.name):
        if health.error:
            out.extend(textwrap.wrap(ascii_text(f"{health.name}: {health.error}"), width,
                                     subsequent_indent="  ", break_long_words=True, break_on_hyphens=False))

    local.research_view = "experiment"
    if getattr(local, "research", None):
        local.research.request(local.research.context(snap, local), wait=True)
    page(10, "research", "Research")
    for key, label in RESEARCH_VIEWS:
        if key != "experiment":
            local.research_view = key
            local.research_scroll = 0
            rows([layout.rule(display.g, width, f"research / {label}")])
            if getattr(local, "research", None):
                local.research.request(local.research.context(snap, local), wait=True)
            rendered, _ = display.research_tab(snap, local, width, None)
            rows(rendered)

    heading("11 / EVENT JOURNAL")
    events = list(snap.get("events", []))
    if events:
        out.append(f"{len(events)} recorded events in this snapshot, oldest first.")
        for event in events:
            timestamp = time.strftime("%m-%d %H:%M:%S", time.localtime(event.get("t", 0)))
            job = f" job={event['job']}" if event.get("job") else ""
            record = ascii_text(f"{timestamp} [{event.get('kind', 'event')}]{job} {event.get('text', '')}")
            out.extend(textwrap.wrap(record, width, subsequent_indent="  ", break_long_words=True, break_on_hyphens=False))
    else:
        out.append("No activity recorded yet. Job transitions, alerts and actions appear here.")
    out.extend(["", "-" * width, "End of report | Slurm Tower | Plain ASCII, no external resources."])
    # Defensive final bound also covers explanatory text on narrow exports.
    return "\n".join(ascii_text(line)[:width] for block in out for line in block.split("\n")) + "\n"
