"""Shared terminal-workbench extension points, without a second event loop."""
from __future__ import annotations

import importlib
from functools import lru_cache

FEATURES = ("workspace_layout", "navigation_ui", "command_ui", "table_ui",
            "activity_ui", "project_ui", "log_workbench", "analysis_ui", "execution_ui")


@lru_cache(maxsize=1)
def modules():
    return tuple(importlib.import_module("tower." + name) for name in FEATURES)


def initialize(app):
    for feature in modules():
        feature.initialize(app)


def restore(app, data):
    data = data if isinstance(data, dict) else {}
    for feature in modules():
        callback = getattr(feature, "restore", None)
        if callback:
            callback(app, data.get(feature.__name__.rsplit(".", 1)[-1], {}))


def save(app):
    return {feature.__name__.rsplit(".", 1)[-1]: feature.save(app)
            for feature in modules() if hasattr(feature, "save")}


def command_names():
    return sorted({name for feature in modules() for name in feature.command_names()})


def handle_key(app, key):
    return any(feature.handle_key(app, key) for feature in modules())


def handle_mouse(app, y, x, button="left", shift=False):
    for feature in modules():
        callback = getattr(feature, "handle_mouse", None)
        if callback and callback(app, y, x, button=button, shift=shift):
            return True
    # Modal overlays never click through into a hidden table or job action.
    return app.mode not in ("main",)


def run_command(app, args):
    return any(feature.run_command(app, args) for feature in modules())


def overlay(views, snap, app, width, height):
    for feature in modules():
        rows = feature.overlay(views, snap, app, width, height)
        if rows is not None:
            return rows
    return None
