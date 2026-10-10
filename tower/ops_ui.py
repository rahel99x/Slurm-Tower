"""One terminal workbench for reviewed operations across the research roadmap."""
from __future__ import annotations

import copy
from dataclasses import asdict, is_dataclass
from functools import lru_cache
import json
import shlex
import threading
import time
from types import MappingProxyType

from . import layout as L, operations as O
from .control_rows import buttons, place_hits

MAX_LINES = 8192
MAX_FIELD = 8192
MAX_PASTE = 4096


@lru_cache(maxsize=1)
def _presentation_specs():
    """Immutable adapter labels and fields; preparation APIs keep copy isolation.

    Operations are registered once at startup. Rebuilding their whole field
    dictionaries for each contextual button is unnecessary during a paint.
    """
    def freeze(value):
        if isinstance(value, dict):
            return MappingProxyType({key: freeze(item) for key, item in value.items()})
        if isinstance(value, (list, tuple)):
            return tuple(freeze(item) for item in value)
        return value
    return MappingProxyType({spec["key"]: freeze(spec) for spec in O.catalog()})


def _review_is_truncated(state, inner):
    plan = (state["result"] or {}).get("plan") or {}
    key = (id(plan), plan.get("digest"), inner)
    cached = state.get("review_size")
    if cached is None or cached[0] != key:
        count = 0
        for line in _review_lines(state):
            count += max(1, (len(line) + inner - 1) // inner)
            if count > MAX_LINES:
                break
        cached = state["review_size"] = (key, count > MAX_LINES)
    return cached[1]


def initialize(app):
    owner = getattr(app, "_chart_owner", app)
    if not isinstance(getattr(owner, "ops_state", None), dict):
        # Import adapters at application construction, never during a paint.
        _presentation_specs()
        owner.ops_state = {"view": "catalog", "feature": "", "values": {}, "index": 0,
            "top": 0, "page": 1, "result": None, "generation": 0, "running": False,
            "applying": False, "cancel": None, "return_mode": "main", "control_hits": [],
            "render_generation": None, "editing": None, "edit": "", "edit_cursor": 0,
            "focus": "content", "button": 0, "wrapped": None, "anchor": None,
            "line_hits": [], "used": {}, "terminal": None, "callback": None,
            "confirm_digest": None, "error": "", "last_scope": None,
            "review_document": None, "review_truncated": False,
            "quit_requested": False, "shutting_down": False}
    return owner.ops_state


def command_names():
    return ["ops"]


def _connection_scope(app):
    from .execution_ui import connection_scope
    return connection_scope(getattr(app, "_chart_owner", app))


def context(app, cancel=None):
    """Capture only queue/accounting records, never entire metric histories."""
    from .execution_ui import connection_scope
    app = getattr(app, "_chart_owner", app)
    slurm = getattr(getattr(app, "actions", None), "slurm", None) or getattr(getattr(app, "research", None), "slurm", None)
    def record(value):
        return asdict(value) if is_dataclass(value) else copy.deepcopy(value) if isinstance(value, dict) else vars(value).copy()
    with app.store.lock:
        jobs = tuple(record(value) for value in app.store.jobs[:10000])
        finished = tuple(record(value) for value in app.store.finished[:10000])
    scope = connection_scope(app)
    return O.Context(slurm=slurm, files=getattr(app, "files", None) or getattr(app.research, "files", None) or O.LocalFiles(),
        cfg=copy.deepcopy(getattr(app.cfg, "data", app.cfg)), jobs=jobs, finished=finished,
        selected=str(getattr(app, "selected_id", "") or ""), scope=scope, cancel=cancel,
        state_dir=str(getattr(app, "state_dir", "") or ""), replay=bool(getattr(app, "replay", None)))


def _reset(state, view):
    state.update(view=view, top=0, index=0, anchor=None, wrapped=None, confirm_digest=None,
                 control_hits=[], render_generation=None, editing=None, focus="content", button=0,
                 review_document=None, review_truncated=False)
    state["generation"] += 1


def _open(app, feature=""):
    state = initialize(app)
    if state["running"]:
        raise ValueError("An operation is running. Wait for its result or cancel the inspection.")
    spec = O.specification(feature) if feature else None
    if app.mode != "operations":
        state["return_mode"] = app.mode if app.mode not in ("palette", "confirm") else "main"
    app.mode = "operations"
    _reset(state, "form" if feature else "catalog")
    state.update(feature=feature, result=None, error="")
    if spec:
        state["values"] = {field["key"]: str(field.get("default", "")) for field in spec.get("fields", ())}
        if "job_id" in state["values"] and not state["values"]["job_id"]:
            selected = getattr(app, "research_job_id", None) if getattr(app, "tab", None) == "research" else None
            state["values"]["job_id"] = str(selected or getattr(app, "selected_id", "") or "")


def close(app):
    state = initialize(app)
    if state["running"] and not state["applying"] and state["cancel"] is not None:
        state["cancel"].set()
    # Do not detach a mutation's callback or abandon its receipt when closing.
    state["control_hits"], state["confirm_digest"] = [], None
    if getattr(app, "mode", None) == "operations":
        app.mode = state["return_mode"]


def defer_quit(app):
    """Keep the terminal responsive until an already accepted action is collected."""
    state = initialize(app)
    if getattr(app, "quit", False) and state["running"] and state["applying"]:
        state["quit_requested"] = True
        state["terminal"] = None
        app.quit = False
        app.say("Quit requested. Waiting for the reviewed action and its result.")
        return True
    return False


def tick(app):
    state = initialize(app)
    if state["quit_requested"] and not state["running"]:
        state["terminal"] = None
        app.quit = True


def shutdown(app):
    """Drain only this feature's owned callback before ResearchHub shuts down.

    Normal interactive exit uses defer_quit and keeps rendering. This fallback
    also covers an interrupted terminal loop and noninteractive callers. An
    accepted mutation retains its result; a read-only inspection is cancelled.
    """
    state = initialize(app)
    state.update(shutting_down=True, quit_requested=True, terminal=None)
    close(app)
    hub = getattr(app, "research", None)
    callback = state["callback"]
    if hub is None or callback is None:
        return
    with hub.lock:
        pending = hub.pending
        owned = pending is not None and pending[1] is callback
    if not owned:
        return
    if not state["applying"]:
        pending[0].cancel()
    try:
        result = pending[0].result()
    except Exception as exc:
        result = exc
    with hub.lock:
        if hub.pending is not pending:
            return
        hub.pending = None
    callback(result)
    state["terminal"] = None


def _background(app, callback, completion, *, applying=False):
    state = initialize(app)
    if state["running"]:
        raise ValueError("An operation is already running.")
    cancel = threading.Event()
    ctx = context(app, cancel)
    generation = state["generation"]
    scope = copy.deepcopy(ctx.scope)
    def done(value):
        state.update(running=False, applying=False, callback=None, cancel=None)
        # Publish evidence without changing the user's current mode or page.
        if isinstance(value, Exception):
            state["error"] = O.clean(value)
            state["result"] = O.report(state["feature"], state["error"], status="error")
            state["view"] = "report"
            state["wrapped"] = None
            app.fail("Operation: " + state["error"])
            return
        try:
            current_scope = _connection_scope(app)
        except (ValueError, OSError):
            current_scope = None
        if not applying and (generation != state["generation"] or scope != current_scope or cancel.is_set()):
            state.update(result=None, error="Connection or request changed; inspect again.", wrapped=None)
            return
        try:
            completion(value)
        except Exception as exc:
            state.update(result=O.report(state["feature"], "Invalid operation result: " + O.clean(exc), status="error"),
                         view="report", error=O.clean(exc), wrapped=None)
            app.fail("Operation result: " + O.clean(exc))
            return
        state["last_scope"] = scope
        if scope != current_scope:
            state["error"] = "This result belongs to the previous connection. Its actions are disabled."
            state["result"].pop("plan", None)
        state["wrapped"] = None
    work = lambda: callback(ctx)
    if getattr(app, "interactive", False):
        hub = getattr(app, "research", None)
        if hub is None or not hub.start_task(work, done):
            raise ValueError("The research worker is busy; retry when it finishes.")
        state.update(running=True, applying=applying, cancel=cancel, callback=done)
    else:
        state.update(running=True, applying=applying, cancel=cancel, callback=done)
        try:
            value = work()
        except Exception as exc:
            value = exc
        done(value)
        app.research_result = state["result"] or O.report(state["feature"], state["error"], status="error")
        app.command_ok = app.research_result.get("status") not in ("error", "unavailable", "blocked", "failed")


def _inspect(app):
    state = initialize(app)
    feature, values = state["feature"], O.parameters(state["feature"], state["values"])
    if state["running"]:
        raise ValueError("An operation is already running.")
    _reset(state, "report")
    state.update(result=None, error="")
    def publish(value):
        if not isinstance(value, dict) or value.get("schema") != O.REPORT_SCHEMA or value.get("feature") != feature:
            raise ValueError("The operation returned an invalid result.")
        state["result"] = value
        app.say(O.clean(value.get("summary", "Inspection complete.")))
    _background(app, lambda ctx: O.run(feature, values, ctx), publish)


def _review(app):
    state = initialize(app)
    plan = (state["result"] or {}).get("plan")
    if not plan:
        raise ValueError("Inspect an action before reviewing it.")
    O.validate_plan(plan, context(app), state["feature"])
    if plan["digest"] in state["used"]:
        raise ValueError("This plan was already attempted; inspect current state before retrying.")
    _reset(state, "review")


def _apply(app):
    state = initialize(app)
    plan = copy.deepcopy((state["result"] or {}).get("plan"))
    if (state["view"] != "review" or state["review_truncated"] or state["confirm_digest"] is None
            or not plan or state["confirm_digest"] != plan.get("digest")
            or state["render_generation"] != state["generation"]):
        raise ValueError("Display the action review before applying it.")
    ctx = context(app)
    O.validate_plan(plan, ctx, state["feature"])
    if plan["digest"] in state["used"]:
        raise ValueError("This plan was already attempted; inspect current state before retrying.")
    feature = state["feature"]
    def apply_once(worker_ctx):
        value = O.apply(feature, plan, worker_ctx)
        if isinstance(value, dict) and feature == "allocation-shell" and value.get("data", {}).get("terminal_identity"):
            from .ops_cluster import revalidate_terminal
            value["data"]["terminal_argv"] = revalidate_terminal(worker_ctx, value["data"]["terminal_identity"])
        return value
    def publish(value):
        state.update(result=value, view="report", confirm_digest=None, top=0, index=0)
        terminal = value.get("data", {}).get("terminal_argv") if isinstance(value, dict) else None
        if terminal:
            if (app.mode == "operations" and not state["quit_requested"] and not state["shutting_down"]
                    and _connection_scope(app) == ctx.scope):
                state["terminal"] = {"argv": terminal, "at": time.monotonic(), "scope": ctx.scope}
            else:
                value.setdefault("warnings", []).append("Terminal handoff was skipped because the view or connection changed.")
        app.say(O.clean(value.get("summary", "Reviewed operation completed.")))
    # Queue acceptance precedes the one-use claim; a busy worker has no effect.
    _background(app, apply_once, publish, applying=True)
    state["used"] = {key: when for key, when in state["used"].items() if time.time() - when < O.PLAN_LIFETIME + 2}
    state["used"][plan["digest"]] = time.time()
    state["confirm_digest"] = None


def take_terminal(app):
    state = initialize(app)
    value, state["terminal"] = state["terminal"], None
    if not value:
        return None
    if (app.mode != "operations" or time.monotonic() - value["at"] > 2
            or state["quit_requested"] or state["shutting_down"] or _connection_scope(app) != value["scope"]):
        app.fail("Terminal handoff expired or its connection changed; inspect again.")
        return None
    argv = value["argv"]
    if not isinstance(argv, list) or not argv or any(not isinstance(s, str) or "\x00" in s for s in argv):
        app.fail("Terminal handoff arguments were invalid.")
        return None
    return argv


def _field(app, key):
    state = initialize(app)
    if state["running"] or state["view"] != "form":
        return
    fields = O.specification(state["feature"]).get("fields", [])
    field = next((value for value in fields if value["key"] == key), None)
    if field is None:
        raise ValueError("Unknown input field.")
    state["index"] = fields.index(field)
    choices = field.get("choices")
    if choices:
        current = state["values"].get(key)
        state["values"][key] = choices[(choices.index(current) + 1) % len(choices)] if current in choices else choices[0]
    else:
        state.update(editing=key, edit=state["values"].get(key, ""), edit_cursor=len(state["values"].get(key, "")))


def _copy(app):
    from . import clipboard
    state = initialize(app)
    lines = _lines(state)
    if state["anchor"] is not None:
        lo, hi = sorted((state["anchor"], state["index"]))
        text = "\n".join(lines[lo:hi + 1]) + "\n"
    else:
        text = json.dumps(state["result"] or {"operations": O.catalog()}, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    app.say(clipboard.copy(text, getattr(app, "state_dir", None), **clipboard.options(app)))


def paste(app, text):
    """Insert inert bracketed-paste text into the current field only."""
    if getattr(app, "mode", None) != "operations":
        return False
    state = initialize(app)
    if state["view"] != "form" or state["editing"] is None or state["running"]:
        app.fail("Select a text field before pasting. Pasted text cannot run an operation.")
        return True
    if not isinstance(text, str) or any(not char.isprintable() for char in text):
        app.fail("Paste one line of plain text without newlines, tabs, or terminal control characters.")
        return True
    # The terminal parser retains one overflow sentinel beyond MAX_PASTE.
    # Reject the whole paste instead of silently shortening a filesystem path.
    if len(text) > MAX_PASTE or len(state["edit"]) + len(text) > MAX_FIELD:
        app.fail(f"Paste is too long. Use at most {MAX_PASTE} pasted characters and {MAX_FIELD} characters per field.")
        return True
    cursor = max(0, min(state["edit_cursor"], len(state["edit"])))
    state["edit"] = state["edit"][:cursor] + text + state["edit"][cursor:]
    state["edit_cursor"] = cursor + len(text)
    app.say("Text pasted into this field. Enter saves the field; Esc discards the edit.")
    return True


def run_command(app, args):
    if not args or args[0] != "ops":
        return False
    app = getattr(app, "_chart_owner", app)
    state = initialize(app)
    try:
        if len(args) == 1 or args[1] == "catalog":
            _open(app)
        elif args[1] == "open" and len(args) == 3:
            _open(app, args[2])
        elif args[1] == "run" and len(args) >= 3:
            _open(app, args[2])
            for value in args[3:]:
                if "=" not in value:
                    raise ValueError("Use ops run FEATURE field=value; quote values containing spaces.")
                key, text = value.split("=", 1)
                if key not in state["values"]:
                    raise ValueError("Unknown operation field: " + O.clean(key))
                state["values"][key] = text
            _inspect(app)
        elif args[1] == "field" and len(args) == 3:
            _field(app, args[2])
        elif args[1] == "inspect" and len(args) == 2:
            _inspect(app)
        elif args[1] == "review" and len(args) == 2:
            _review(app)
        elif args[1] == "apply" and len(args) == 2:
            _apply(app)
        elif args[1] == "form" and len(args) == 2:
            if state["running"]:
                raise ValueError("Wait for the running operation.")
            if not state["feature"]:
                raise ValueError("Choose an operation before editing its inputs.")
            _reset(state, "form")
        elif args[1] == "copy" and len(args) == 2:
            _copy(app)
        elif args[1] == "cancel" and len(args) == 2:
            if state["applying"]:
                raise ValueError("An action is running. Its result must be collected before another action.")
            if state["cancel"] is not None:
                state["cancel"].set()
        elif args[1] == "close" and len(args) == 2:
            close(app)
        elif len(args) == 2:
            _open(app, args[1])
        else:
            raise ValueError("Use ops [FEATURE], or ops run FEATURE field=value.")
    except (ValueError, KeyError, OSError, TypeError) as exc:
        app.fail("Operations: " + O.clean(exc))
    return True


def _controls(state):
    if state["running"]:
        return [("cancel", "Cancel inspection", "cancel")] if not state["applying"] else []
    if state["view"] == "catalog":
        return [("close", "Esc Close", "close")]
    if state["view"] == "form":
        return [("inspect", "Inspect / prepare", "inspect"), ("catalog", "All tools", "catalog"), ("close", "Close", "close")]
    if state["view"] == "review":
        confirm = [] if state["review_truncated"] else [("apply", "Confirm apply", "apply")]
        return confirm + [("form", "Edit inputs", "form"), ("copy", "Copy full review", "copy"), ("close", "Close", "close")]
    out = [("form", "Edit inputs", "form"), ("inspect", "Refresh", "inspect"), ("copy", "Copy report", "copy")]
    if (state["result"] or {}).get("plan"):
        out.insert(0, ("review", "Review action", "review"))
    return out + [("catalog", "All tools", "catalog"), ("close", "Close", "close")]


def _review_lines(state):
    plan = (state["result"] or {}).get("plan") or {}
    key = (id(plan), plan.get("digest"))
    if state["review_document"] is None or state["review_document"][0] != key:
        lines = ["Review the exact action below. Apply uses this sealed scope only.",
                 "Review expires after five minutes. Changed evidence requires a new inspection.",
                 ""] + json.dumps(plan, indent=2, ensure_ascii=True).splitlines()
        state["review_document"] = (key, lines)
    return state["review_document"][1]


def _lines(state):
    result = state["result"] or {}
    if state["view"] == "review":
        lines = _review_lines(state)
        if len(lines) > MAX_LINES:
            return lines[:MAX_LINES - 1] + ["Review truncated. Apply is disabled. Copy full review and reduce the action scope."]
        return lines
    lines = [str(result.get("summary", state["error"] or "No inspection yet."))]
    lines += ["! " + str(value) for value in result.get("warnings", ())]
    lines += [str(value) for value in result.get("rows", ())]
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES - 1] + ["Report display limit reached. Copy report for the complete structured evidence."]
    return lines


def handle_key(app, key):
    if app.mode != "operations":
        return False
    state = initialize(app)
    if state["editing"] is not None:
        if key == "esc":
            state["editing"] = None
        elif key == "enter":
            state["values"][state["editing"]] = state["edit"]
            state["editing"] = None
        elif key in ("left", "right", "home", "end"):
            state["edit_cursor"] = (0 if key == "home" else len(state["edit"]) if key == "end" else
                max(0, min(len(state["edit"]), state["edit_cursor"] + (1 if key == "right" else -1))))
        elif key in ("backspace", "delete"):
            pos = state["edit_cursor"]
            if key == "backspace" and pos:
                state["edit"] = state["edit"][:pos - 1] + state["edit"][pos:]
                state["edit_cursor"] -= 1
            elif key == "delete":
                state["edit"] = state["edit"][:pos] + state["edit"][pos + 1:]
        else:
            text = " " if key == "space" else key
            if isinstance(text, str) and len(text) == 1 and text.isprintable() and len(state["edit"]) < MAX_FIELD:
                pos = state["edit_cursor"]
                state["edit"] = state["edit"][:pos] + text + state["edit"][pos:]
                state["edit_cursor"] += 1
        return True
    if key in ("esc", "q"):
        close(app)
    elif key == ":":
        return False
    elif key in ("tab", "btab"):
        state["focus"] = "buttons" if state["focus"] == "content" else "content"
    elif key in ("left", "right"):
        state["focus"] = "buttons"
        state["button"] = (state["button"] + (1 if key == "right" else -1)) % max(1, len(_controls(state)))
    elif key in ("enter", "space"):
        if state["focus"] == "buttons" and _controls(state):
            action = _controls(state)[state["button"] % len(_controls(state))][2]
            run_command(app, ["ops", action])
        elif state["view"] == "catalog":
            specs = O.catalog()
            if specs:
                run_command(app, ["ops", "open", specs[state["index"] % len(specs)]["key"]])
        elif state["view"] == "form":
            fields = O.specification(state["feature"]).get("fields", [])
            if fields:
                run_command(app, ["ops", "field", fields[state["index"] % len(fields)]["key"]])
    elif key == "v" and state["view"] in ("report", "review"):
        state["anchor"] = state["index"] if state["anchor"] is None else None
    elif key == "y":
        _copy(app)
    elif key == "r" and state["feature"]:
        run_command(app, ["ops", "inspect"])
    elif key in ("up", "down", "pgup", "pgdn", "home", "end"):
        from . import scrollbars, scrolling
        scrolling.note_input(app, "key")
        scrollbars.resume(app, "modal:operations")
        count = len(O.catalog()) if state["view"] == "catalog" else len(O.specification(state["feature"]).get("fields", [])) if state["view"] == "form" else len(_lines(state))
        delta = {"up": -1, "down": 1, "pgup": -state["page"], "pgdn": state["page"]}
        state["index"] = (0 if key == "home" else max(0, count - 1) if key == "end" else max(0, min(count - 1, state["index"] + delta[key])))
        state["focus"] = "content"
    return True


def handle_mouse(app, y, x, button="left", shift=False):
    if app.mode != "operations":
        return False
    state = initialize(app)
    if button == "right":
        state["anchor"] = None
        return True
    if state["render_generation"] != state["generation"]:
        return True
    if button in ("wheel-up", "wheel-down"):
        from . import scrolling
        scrolling.note_input(app, "wheel")
        state["top"] = max(0, state["top"] + (3 if button == "wheel-down" else -3))
        return True
    if button not in ("left", "press"):
        return True
    for hy, kind, value in state["control_hits"]:
        if hy == y and value["left"] <= x < value["right"]:
            # Activations use this frame's exact semantic command; a release
            # from an earlier view can never confirm its replacement.
            run_command(app, shlex.split(value["action"][1]))
            return True
    for hy, left, right, index in state["line_hits"]:
        if y == hy and left <= x < right:
            if shift and state["anchor"] is None:
                state["anchor"] = state["index"]
            elif not shift:
                state["anchor"] = None
            state["index"], state["focus"] = index, "content"
            return True
    return True


def _field_editor_row(label, value, cursor, width, ascii_mode=False):
    """Keep the insertion point visible using display cells, including wide text."""
    from .research import clean
    width = max(1, width)
    prefix_width = min(24, width // 3) if width >= 6 else 0
    prefix = L.truncate(clean(label, ascii_mode), max(0, prefix_width - 2)) + ": " if prefix_width else ""
    available = max(1, width - L.vlen(prefix))
    markers = available >= 3
    content = available - 2 if markers else available
    cursor = max(0, min(cursor, len(value)))
    current = clean(value[cursor:cursor + 1] or " ", ascii_mode)
    if L.vlen(current) == 0:
        current = " " + current
    if L.vlen(current) > content:
        current = "?"
    room = content - L.vlen(current)
    before, used, start = [], 0, cursor
    left_room = room * 2 // 3 if cursor < len(value) - 1 else room
    while start > 0:
        char = clean(value[start - 1], ascii_mode)
        cells = L.vlen(char)
        if used + cells > left_room:
            break
        before.append(char)
        used += cells
        start -= 1
    before = "".join(reversed(before))
    after, finish = [], min(len(value), cursor + 1)
    while finish < len(value):
        char = clean(value[finish], ascii_mode)
        cells = L.vlen(char)
        if used + cells > room:
            break
        after.append(char)
        used += cells
        finish += 1
    row = [(prefix, "muted")]
    if markers:
        row.append(("<" if start else " ", "muted"))
    row.extend([(before, "text"), (current, "accent+rev+bold"), ("".join(after), "text")])
    if markers:
        row.append((">" if finish < len(value) else " ", "muted"))
    return row


def overlay(views, snap, app, width, height):
    if app.mode != "operations":
        return None
    from . import modal_scrollbars as B
    from .research import clean
    state = initialize(app)
    state.update(control_hits=[], line_hits=[], render_generation=None, confirm_digest=None)
    inner = max(1, width - 8)
    spec = _presentation_specs()[state["feature"]] if state["feature"] else None
    if state["view"] == "review":
        # JSON review text is ASCII, so wrapped cell count is exact without
        # constructing an unbounded second document on each frame.
        state["review_truncated"] = _review_is_truncated(state, inner)
    controls = _controls(state)
    chosen = controls[state["button"] % len(controls)][0] if controls and state["focus"] == "buttons" else None
    rows, hits = buttons(views.g, inner, [(key, label, ("command", "ops " + action)) for key, label, action in controls],
                         selected=chosen, group="operations", prefix="ops:")
    if state["running"]:
        rows += [[("Applying the reviewed action; collecting its result..." if state["applying"] else "Inspecting in the background...", "accent")]]
    if state["error"]:
        rows += [[(clean(state["error"], views.g.ascii), "warning")]]
    if state["review_truncated"]:
        rows += [[("Review exceeds the display limit. Apply is disabled; reduce the action scope.", "warning")]]
    if spec:
        rows += [[(clean(spec["summary"], views.g.ascii), "dim")]]
    entries, edit_rows = [], {}
    if state["view"] == "catalog":
        for index, item in enumerate(_presentation_specs().values()):
            label = f"{item.get('proposal', '')}  {item['title']}  / {item['group']}"
            entries.append((index, label, "ops open " + item["key"]))
    elif state["view"] == "form":
        for index, item in enumerate(spec.get("fields", ())):
            key = item["key"]
            value = state["edit"] if state["editing"] == key else state["values"].get(key, "")
            if state["editing"] == key:
                edit_rows[index] = _field_editor_row(item["label"], value, state["edit_cursor"], inner, views.g.ascii)
                text = L.row_text(edit_rows[index])
            else:
                text = item["label"] + ": " + (value or "(empty)")
            entries.append((index, text, "ops field " + key))
        if not entries:
            entries = [(0, "No inputs needed. Select Inspect / prepare.", "")]
    else:
        key = (id(state["result"]), state["view"], inner, views.g.ascii)
        if state["wrapped"] is None or state["wrapped"][0] != key:
            entries = []
            for index, text in enumerate(_lines(state)):
                if len(entries) >= MAX_LINES:
                    break
                if state["view"] == "review":
                    # This exact JSON is already escaped ASCII. Do not apply
                    # report-string truncation or repeatedly copy its tail.
                    if not text:
                        entries.append((index, "", ""))
                    else:
                        stop = min(len(text), (MAX_LINES - len(entries)) * inner)
                        entries.extend((index, text[offset:offset + inner], "")
                                       for offset in range(0, stop, inner))
                    continue
                text = clean(text, views.g.ascii, limit=16384)
                if not text:
                    entries.append((index, "", ""))
                while text and len(entries) < MAX_LINES:
                    part = L.truncate(text, inner) or "?"
                    entries.append((index, part, ""))
                    text = text[len(part):]
            if state["review_truncated"] and entries:
                entries[-1] = (entries[-1][0], "Review truncated. Copy full review; reduce the action scope to apply.", "")
            state["wrapped"] = (key, entries)
        entries = state["wrapped"][1]
    page = state["page"] = max(1, height - len(rows) - 6)
    focus = next((i for i, (index, _, _) in enumerate(entries) if index == state["index"]), 0)
    target = state["top"]
    identity = (state["generation"], state["view"], width)
    if state.get("focus_seen") != (identity, state["index"]):
        target = min(target, focus) if focus < target else max(target, focus - page + 1)
        state["focus_seen"] = (identity, state["index"])
    logical, painted = B.window(app, "modal:operations", target, len(entries), page, context=identity, focus=state["index"])
    state["top"] = logical
    start, line_rows = len(rows), []
    selection = sorted((state["anchor"], state["index"])) if state["anchor"] is not None else None
    for index, text, action in entries[painted:painted + page]:
        style = "sel" if (index == state["index"] and state["focus"] == "content") or selection and selection[0] <= index <= selection[1] else "text"
        row = len(rows)
        rows.append(edit_rows.get(index, [(text, style)]))
        if action:
            hits.append((row, "control", {"id": "ops-item:" + action, "label": text,
                "left": 0, "right": inner, "action": ("command", action), "group": "ops-items"}))
        else:
            line_rows.append((row, index))
    hint = ("Left/Right/Home/End move caret | Paste inserts | Enter saves | Esc discards"
            if state["editing"] is not None else "Arrows scroll | Enter selects | Tab actions | v select | y copy")
    rows += [[(hint, "dim")]]
    rendered = L.box(views.g, rows, width, height, spec["title"] if spec else "Research and cluster operations")
    state["control_hits"] = place_hits(hits, rendered[1:-1])
    for row, index in line_rows:
        if row + 1 < len(rendered) - 1:
            y, x, segments = rendered[row + 1]
            state["line_hits"].append((y, x + 1, x + L.vlen(L.row_text(segments)) - 2, index))
    state["render_generation"] = state["generation"]
    plan = (state["result"] or {}).get("plan")
    if state["view"] == "review" and plan and any(value["id"] == "ops:apply" for _, _, value in state["control_hits"]):
        state["confirm_digest"] = plan["digest"]
    return B.boxed(app, "modal:operations", rendered, start=start, count=len(entries), page=page,
                   target=logical, painted=painted, setter=lambda value: state.update(top=value),
                   context=identity, header=-1)


CONTEXT_TOOLS = {
    "experiment": ("acceptance", "statistics", "energy"),
    "arrays": ("array-throttle", "search", "packing"),
    "evidence": ("bottlenecks", "placement", "incidents"),
    "artifacts": ("storage", "staging", "reuse"),
    "passport": ("environment",),
    "submit": ("pending-edit", "batch-script", "heterogeneous"),
    "workflow": ("dependency-repair", "workflow-engine", "checkpoint", "supervisor", "dask"),
    "forecast": ("reservations", "licenses"),
    "blockers": ("slurm-doctor", "pending-edit", "licenses"),
    "scaling": ("bottlenecks", "placement", "dask"),
}


def contextual_controls(g, width, keys, *, selected_job=None):
    items = []
    for key in keys:
        spec = _presentation_specs()[key]
        items.append((key, spec["title"], ("command", "ops " + key)))
    return buttons(g, width, items, group="operation-tools", prefix="operation-tools:")


def catalog_rows(g, width):
    rows, hits = [], []
    previous = None
    for spec in _presentation_specs().values():
        if previous != spec["group"]:
            rows.append(L.rule(g, width, spec["group"]))
            previous = spec["group"]
        content, actions = contextual_controls(g, width, (spec["key"],))
        hits.extend((y + len(rows), kind, item) for y, kind, item in actions)
        rows.extend(content)
        rows.append([(spec["summary"], "dim")])
    return rows, hits
