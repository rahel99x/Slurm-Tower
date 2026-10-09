"""Selection-bound job actions over immutable, painted row identities.

Opening and activating this modal are explicit operations. Hover, wheel input,
painting and keyboard navigation use its frozen, bounded action list only.
"""
from __future__ import annotations

from . import layout as L
from .research import clean

MODE = "job_group_menu"
PANE = "modal:job-groups"


def initialize(app):
    state = getattr(app, "job_group_menu_state", None)
    if not isinstance(state, dict):
        state = app.job_group_menu_state = dict(token=0, context=None, items=(),
                                               cursor=0, top=0, page=1, hits=(),
                                               hover=None, pressed=None, paint_token=None)
    return state


def active(app):
    return getattr(app, "mode", "main") == MODE


def command_names():
    return ["jobgroupmenu"]


def _feedback(app, message):
    callback = getattr(app, "say", None)
    if callable(callback):
        callback(message)


def close(app):
    state = initialize(app)
    # Release evidence for old snapshots as soon as the modal closes. A menu
    # containing many historical groups must not retain their record objects.
    state.update(context=None, items=(), hits=(), paint_token=None, hover=None, pressed=None)
    if active(app):
        app.mode = "main"
    pointer = getattr(app, "interaction_state", {})
    pointer.update(active=False, focused=None, pressed=None, frame_required=True)


def open_menu(app, context=None):
    """Open for the pointed marked row, or the pointed active single row.

    An unmarked active row is an exact single-job context even when another
    list retains marks. Unrelated marks must never broaden its actions.
    """
    if getattr(app, "mode", "main") != "main" or not isinstance(context, dict):
        return False
    pointed = context.get("pointed")
    marks = getattr(app, "marks", ())
    if pointed in marks:
        targets = tuple(jid for jid in context.get("ids", ()) if jid in marks)
    elif pointed and pointed == context.get("selected"):
        targets = (pointed,)
    else:
        return False
    if not targets:
        return False
    from . import job_group_actions as A, job_groups as G, manual_job_groups as M
    if len(targets) > M.MAX_IDENTITIES:
        _feedback(app, f"Select at most {M.MAX_IDENTITIES} jobs for a group action")
        return True
    frozen = A.freeze(app, context, targets)
    snap = A.validate(app, frozen)
    if snap is None:
        return True
    registry = G.registry(app)
    index = registry.ensure(snap)
    selected = frozenset(targets)
    destinations = [group for group in index.groups.values()
                    if not selected.issubset(group.members)]
    collapsed = {}
    grouped = False
    for jid in targets:
        group = index.for_job(jid)
        if group is not None:
            grouped = True
            if getattr(app, "table_state", {}).get("groups") and registry.is_collapsed(group):
                collapsed[group.id] = group
    required = tuple(dict.fromkeys((*collapsed, *(group.id for group in destinations))))
    evidence = M.target_evidences(app, snap, required, index=index, all_groups=True)
    frozen["ungroup_groups"] = {gid: evidence.get(gid) for gid in collapsed}
    items = []
    if len(targets) >= 2:
        items.append(dict(label="Create Group", action="create"))
    if grouped:
        items.append(dict(label="Ungroup", action="ungroup"))
    names = {}
    for group in destinations:
        names[group.label] = names.get(group.label, 0) + 1
    for group in sorted(destinations, key=lambda value: (value.label.casefold(), value.id)):
        expected = evidence.get(group.id)
        if expected is None:
            continue
        label = clean(group.label, limit=512)
        if names[group.label] > 1:
            members = group.members
            label += " (" + members[0] + (".." + members[-1] if len(members) > 1 else "") + ")"
        items.append(dict(label="Add to " + label, action="add", group_id=group.id,
                          expected=expected))
    if getattr(app, "tab", "") == "history":
        items.append(dict(label="Export logs", action="export"))
    items.append(dict(label="Cancel", action="cancel"))
    state = initialize(app)
    state.update(token=state["token"] + 1, context=frozen, items=tuple(items),
                 tab=getattr(app, "tab", ""), cursor=0, top=0, page=1,
                 hits=(), paint_token=None, hover=None, pressed=None)
    # End the old gesture before changing ownership; a late release is inert.
    getattr(app, "job_selection_state", {})["capture"] = None
    from . import chart_interaction, metric_live, pane_drag
    chart_interaction.cancel(app)
    metric_live.cancel(app)
    pane_drag.cancel(app)
    toolbar = getattr(app, "toolbar_state", {})
    toolbar.update(menu=None, panel=None, focus="", dragging=False,
                   menu_hits=[], menu_token=None)
    pointer = getattr(app, "interaction_state", {})
    pointer.update(active=False, focused=None, pressed=None, frame_required=True)
    app.mode = MODE
    return True


def _activate(app, index):
    state = initialize(app)
    if not active(app) or type(index) is not int or not 0 <= index < len(state["items"]):
        return
    item, frozen = state["items"][index], state["context"]
    close(app)
    action = item["action"]
    if action == "cancel":
        return
    from . import job_group_actions as A
    if action == "export":
        if A.validate(app, frozen) is not None:
            from .history_log_export import open_menu as export_menu
            export_menu(app, frozen["targets"])
        return
    A.execute(app, frozen, action, group_id=item.get("group_id"), expected=item.get("expected"))


def run_command(app, args):
    if not args or args[0] != "jobgroupmenu":
        return False
    state = initialize(app)
    if args[1:] == ["cancel"]:
        close(app)
    elif (active(app) and len(args) == 4 and args[1] == "choose"
          and args[2] == str(state["token"]) and args[3].isdigit() and _fresh(app)):
        _activate(app, int(args[3]))
    return True


def handle_key(app, key):
    if not active(app):
        return False
    state = initialize(app)
    if key == "f8" or getattr(app, "interaction_state", {}).get("active") and key not in ("esc", "ctrl-c", "q"):
        from .interaction import handle_key as focus_key
        if focus_key(app, key):
            return True
    if key in ("esc", "ctrl-c", "q"):
        close(app)
    elif key in ("up", "down", "left", "right", "tab", "btab", "pgup", "pgdn", "home", "end"):
        count, page = len(state["items"]), max(1, state["page"])
        delta = {"up": -1, "down": 1, "left": -1, "right": 1, "tab": 1, "btab": -1,
                 "pgup": -page, "pgdn": page, "home": -count, "end": count}[key]
        cursor = state["cursor"] + delta
        state["cursor"] = cursor % count if key in ("tab", "btab") and count else max(0, min(count - 1, cursor))
        state.update(pressed=None, hover=None)
    elif key in ("enter", "space"):
        _activate(app, state["cursor"])
    return True


def tick(app):
    state = initialize(app)
    if active(app) and state.get("tab") != getattr(app, "tab", ""):
        close(app)
        _feedback(app, "Job menu closed because its source page changed")


def _paint_context(app, width=None, height=None):
    state = initialize(app)
    return (state["token"], getattr(app, "mode", "main"), getattr(app, "tab", ""),
            width if width is not None else getattr(app, "width", None),
            height if height is not None else getattr(app, "height", None), state["top"])


def _fresh(app):
    state = initialize(app)
    return bool(active(app) and state.get("paint_token") == _paint_context(app))


def overlay(views, snap, app, width, height):
    state = initialize(app)
    state.update(hits=(), paint_token=None)
    if not active(app):
        return None
    from . import modal_scrollbars as B
    from . import scrollbars as S
    staged = S.initialize(app)["staged"]
    staged[:] = [pane for pane in staged if pane.key != PANE]
    ascii_ = views.g.ascii
    room, available = max(1, min(88, width - 8)), max(1, height - 4)
    targets = state["context"]["targets"]
    prefix = [[(L.cut(f" {len(targets)} selected job" + ("s" if len(targets) != 1 else "") + ": " +
                     ", ".join(targets[:8]) + (", ..." if len(targets) > 8 else ""), room, ascii_), "accent+bold")]]
    if available < 2:
        prefix = []
    items = state["items"]
    count = len(items)
    cursor = max(0, min(state["cursor"], max(0, count - 1)))
    state["cursor"] = cursor
    page = max(1, available - len(prefix) - (1 if available >= 5 else 0))
    top = min(max(0, state["top"]), max(0, count - page))
    if cursor < top:
        top = cursor
    elif cursor >= top + page:
        top = cursor - page + 1
    context = (MODE, state["token"])
    logical, painted = B.window(app, PANE, top, count, page, context=context, focus=cursor)
    state.update(top=logical, page=page)
    rows, logical_hits = list(prefix), []
    for index in range(painted, min(count, painted + page)):
        item = items[index]
        style = "sel" if index == cursor else "accent+under" if index == state["hover"] else "text"
        logical_hits.append((len(rows), index))
        rows.append([(L.cut(" [ " + clean(item["label"], ascii_, limit=1024) + " ]", room, ascii_), style)])
    if len(rows) < available:
        rows.append([(L.cut(" Arrows / wheel choose | Enter select | Esc cancel", room, ascii_), "dim")])
    rendered = L.box(views.g, rows, width, height, "Job groups")
    hits = []
    for logical_row, index in logical_hits:
        row_index = logical_row + 1
        if row_index < len(rendered) - 1:
            y, x, segments = rendered[row_index]
            right = x + L.vlen(L.row_text(segments)) - 2  # reserve the scrollbar cell
            if x + 1 < right:
                hits.append((y, x + 1, right, index))
    state.update(hits=tuple(hits), paint_token=_paint_context(app, width, height))
    return B.boxed(app, PANE, rendered, start=len(prefix), count=count, page=page,
                   target=logical, painted=painted, setter=lambda value: _scroll(app, value),
                   context=context, header=0 if prefix else -1)


def _scroll(app, value):
    state = initialize(app)
    state.update(top=max(0, int(value)), pressed=None, hover=None, paint_token=None)


def controls(app):
    if not _fresh(app):
        return ()
    from .interaction import Control, Rect
    state = initialize(app)
    token = str(state["token"])
    return tuple(Control("job-group-menu:" + token + ":" + str(index), state["items"][index]["label"],
                         Rect(y, left, y + 1, right),
                         ("command", "jobgroupmenu choose " + token + " " + str(index)),
                         "job-group-menu", layer=2)
                 for y, left, right, index in state["hits"])


def handle_mouse(app, y, x, button="left", shift=False):
    if not active(app):
        if button != "right" or getattr(app, "mode", "main") != "main":
            return False
        from .job_group_drag import source_at
        return open_menu(app, source_at(app, y, x, include_disclosure=True))
    state = initialize(app)
    if not _fresh(app):
        state.update(hover=None, pressed=None)
        return True
    hit = next((index for row, left, right, index in state["hits"]
                if row == y and left <= x < right), None)
    if button in ("motion", "drag"):
        state["hover"] = hit
    elif button in ("wheel-up", "wheel-down", "wheel_up", "wheel_down"):
        handle_key(app, "up" if button in ("wheel-up", "wheel_up") else "down")
    elif button == "press":
        state["pressed"] = (state["paint_token"], hit) if hit is not None else None
        if hit is not None:
            state["cursor"] = hit
    elif button == "release":
        pressed, state["pressed"] = state["pressed"], None
        if hit is not None and pressed == (state["paint_token"], hit):
            _activate(app, hit)
    elif button in ("left", "double") and hit is not None:
        state["cursor"] = hit
        _activate(app, hit)
    return True
