"""Mouse-selected ranges retain exact IDs and existing bulk-action review."""
from types import SimpleNamespace

import pytest

from tower import job_selection as drag
from tower.config import Config
from tower.controller import App
from tower.layout import Glyphs
from tower.model import Job, Store
from tower.views import Views


@pytest.fixture
def dashboard():
    store = Store(persist=False)
    store.jobs = [Job(str(i), "task " + str(i), "main", "RUNNING") for i in range(1, 11)]
    app = App(store, None, None, Config({"animations": False}), "tester", ascii_=True)
    app.width = 180
    views = Views(Glyphs(True), app.cfg)
    app.views_ref = views
    views.compose(store.snapshot(), app, app.width, 38)
    yield app, store, views
    if app.research:
        app.research.close()


def point(app, identifier):
    row = next(y for y, kind, value in app.last_hits if kind == "job" and value == identifier)
    return row, 3


def send(app, identifier, button, shift=False):
    y, x = point(app, identifier)
    return drag.handle_mouse(app, y, x, button=button, shift=shift)


def test_plain_press_and_release_retains_marks_and_normal_single_selection(dashboard):
    app, _, _ = dashboard
    app.marks = {"9"}
    assert send(app, "2", "press")
    assert app.selected_id == "2" and app.marks == {"9"}
    assert send(app, "2", "release")
    assert app.marks == {"9"} and not drag.active(app)


@pytest.mark.parametrize("first,last", [("2", "6"), ("6", "2")])
def test_drag_marks_sorted_range_in_both_directions_without_scheduler_work(dashboard, first, last):
    app, _, _ = dashboard
    app.marks = {"10"}
    send(app, first, "press")
    assert send(app, last, "motion")
    assert app.marks == {"2", "3", "4", "5", "6"}
    assert send(app, last, "release")
    assert app.selected_id == last and app.mode == "main" and app.confirm == {}


def test_release_on_another_row_also_completes_range_without_motion_event(dashboard):
    app, _, _ = dashboard
    send(app, "2", "press")
    send(app, "4", "release")
    assert app.marks == {"2", "3", "4"}


def test_shift_drag_extends_marks_and_drag_back_shrinks_only_new_range(dashboard):
    app, _, _ = dashboard
    app.marks = {"10"}
    send(app, "2", "press", shift=True)
    send(app, "6", "drag")
    send(app, "3", "motion")
    send(app, "3", "release")
    assert app.marks == {"2", "3", "10"}


def test_escape_during_drag_restores_original_marks(dashboard):
    app, _, _ = dashboard
    app.marks = {"10"}
    send(app, "2", "press")
    send(app, "6", "motion")
    assert drag.handle_key(app, "esc")
    assert app.marks == {"10"} and not drag.active(app)


def test_capture_stops_on_reordering_and_never_marks_a_replacement_row(dashboard):
    app, _, _ = dashboard
    send(app, "2", "press")
    app.visible_ids.reverse()
    assert send(app, "6", "motion")
    assert app.marks == set() and not drag.active(app)


def test_tab_or_modal_change_cancels_pending_gesture(dashboard):
    app, _, _ = dashboard
    send(app, "2", "press")
    app.mode = "confirm"
    drag.tick(app)
    assert not drag.active(app) and not send(app, "6", "motion")
    assert app.marks == set()


def test_release_outside_window_ends_capture_without_extending_range(dashboard):
    app, _, _ = dashboard
    send(app, "2", "press")
    send(app, "4", "motion")
    assert drag.handle_mouse(app, -200, 500, button="release")
    assert app.marks == {"2", "3", "4"} and not drag.active(app)


def test_details_buttons_never_start_a_job_range(dashboard):
    app, _, _ = dashboard
    rect = app.job_panel_rect
    assert not drag.handle_mouse(app, rect.y + 1, rect.x + 1, button="press")
    assert not drag.active(app) and not app.marks


def test_bulk_cancel_review_uses_exact_range_and_drag_executes_nothing(dashboard):
    app, _, _ = dashboard
    calls = []
    app.actions = SimpleNamespace(applicable=lambda action, job: (True, ""),
                                  perform=lambda *args, **kwargs: calls.append((args, kwargs)))
    send(app, "2", "press")
    send(app, "4", "motion")
    send(app, "4", "release")
    assert calls == []
    app.start_confirm("cancel")
    assert app.mode == "confirm" and app.confirm["action"] == "cancel"
    assert [job.id for job in app.confirm["jobs"]] == ["2", "3", "4"]
    assert calls == []
