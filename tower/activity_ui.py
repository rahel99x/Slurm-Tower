"""Durable-in-session notices and bounded, honestly measured task progress."""
from __future__ import annotations

from collections import deque
import threading
import time

from . import layout as L
from .research import clean


class Activity:
    def __init__(self):
        self.notices = deque(maxlen=256)
        self.lock = threading.Lock()
        self.task = None
        self.cursor = 0
        self.expanded = False

    def post(self, text, level="info", path=""):
        with self.lock:
            self.notices.append({"text": clean(text, limit=8192), "level": level,
                                 "path": clean(path), "time": time.time()})

    def start(self, label, source=""):
        with self.lock:
            self.task = {"label": clean(label), "source": clean(source), "start": time.monotonic(),
                         "done": 0, "total": None, "cancel": threading.Event(), "status": "running"}
            return self.task

    def progress(self, task, done, total=None):
        with self.lock:
            if self.task is task:
                task["done"], task["total"] = max(0, int(done)), total

    def finish(self, task, status):
        with self.lock:
            if self.task is task:
                task["status"] = status

    def snapshot(self):
        with self.lock:
            return list(self.notices), dict(self.task) if self.task else None


def initialize(app):
    app.activity = Activity()


def restore(app, data):
    pass


def save(app):
    return {}


def command_names():
    return ["activity", "notifications", "task"]


def run_command(app, args):
    if not args or args[0] not in command_names():
        return False
    if args[0] == "task" and args[1:] == ["cancel"]:
        _, task = app.activity.snapshot()
        if task and task["status"] == "running":
            task["cancel"].set()
            app.say("Cancellation requested; waiting for the next bounded chunk")
        else:
            app.fail("No cancellable export or copy operation is running")
    elif args[1:] == ["clear"]:
        with app.activity.lock:
            app.activity.notices.clear()
        app.say("Activity cleared")
    elif args[1:] and args[1:] != ["show"]:
        app.fail("Usage: activity [show|clear]; task [cancel]")
    else:
        app.mode = "activity"
        app.activity.cursor = 0
    return True


def handle_key(app, key):
    if key == "ctrl-a" and app.mode == "main":
        app.mode = "activity"
        return True
    if app.mode != "activity":
        return False
    if key in ("esc", "q"):
        app.mode = "main"
    elif key in ("up", "down", "pgup", "pgdn", "home", "end"):
        notices, _ = app.activity.snapshot()
        n = len(notices)
        step = {"up": -1, "down": 1, "pgup": -8, "pgdn": 8, "home": -n, "end": n}[key]
        app.activity.cursor = max(0, min(max(0, n - 1), app.activity.cursor + step))
    elif key == "enter":
        app.activity.expanded = not app.activity.expanded
    elif key == "c":
        run_command(app, ["task", "cancel"])
    elif key == "y":
        notices, _ = app.activity.snapshot()
        if notices:
            from . import clipboard
            notice = list(reversed(notices))[min(app.activity.cursor, len(notices) - 1)]
            cb = app.cfg["clipboard"]
            app.say(clipboard.copy(notice["path"] or notice["text"], app.state_dir,
                                   use_osc52=bool(cb.get("osc52", True)), use_tools=bool(cb.get("tools", True))))
    return True


def overlay(views, snap, app, width, height):
    if app.mode != "activity":
        return None
    notices, task = app.activity.snapshot()
    rows = [[(" Notifications and background work", "accent+bold")]]
    if task:
        elapsed = max(0, time.monotonic() - task["start"])
        rows.append([(clean(f" {task['status'].upper()}  {task['label']}  {elapsed:.1f}s", views.g.ascii), "cyan")])
        if task["total"] is not None:
            rows.append([(f" {task['done']:,}/{task['total']:,} bytes ", "dim")] +
                        L.gradient_bar(views.g, task["done"] / max(1, task["total"]), max(1, min(32, width - 10))))
        else:
            rows.append([(" Progress is not reported for this operation", "dim")])
    elif getattr(app, "research", None) and app.research.pending:
        rows.append([(" Background reader busy; progress unavailable", "cyan")])
    ordered = list(reversed(notices))
    cursor = min(app.activity.cursor, max(0, len(ordered) - 1))
    available = max(1, height - len(rows) - 6)
    start = max(0, cursor - available // 2)
    for index, notice in enumerate(ordered[start:start + available], start):
        timestamp = time.strftime("%H:%M:%S", time.localtime(notice["time"]))
        style = "sel" if index == cursor else {"error": "red", "warning": "yellow"}.get(notice["level"], "")
        rows.append([(L.cut(clean(f" {timestamp} {notice['level'].upper():7} {notice['text']}", views.g.ascii), max(0, width - 8), views.g.ascii), style)])
    if not ordered:
        rows.append([(" No notices yet. Copy and export results remain here during this session.", "dim")])
    if ordered and app.activity.expanded:
        value = clean(ordered[cursor]["text"], views.g.ascii)
        w = max(1, width - 10)
        rows = rows[:max(1, height // 3)] + [[(value[i:i+w], "")] for i in range(0, min(len(value), w * max(1, height // 2)), w)]
    rows.append([(" Arrows/PgUp/PgDn browse | Enter expand | y copy path/text | c cancel export/copy | Esc back", "dim")])
    return L.box(views.g, rows, width, height, "Activity")
