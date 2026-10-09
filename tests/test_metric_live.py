"""Live windows affect only displays, with bounded exact-source controls."""

import math
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tower import (
    chart_interaction as C,
    clock,
    interaction as I,
    layout as L,
    metric_live as M,
)
from tower.model import Job
from tower.config import Config
from tower.controller import App
from tower.model import Store
from tower.views import Views


@pytest.fixture
def app():
    value = SimpleNamespace(
        mode="main",
        tab="analytics",
        width=120,
        height=40,
        selected_id="101",
        analytics_job="101",
        analytics_view="job",
        toolbar_state={},
        project_state={},
        job_panel_state={},
        analysis_state={},
        research=SimpleNamespace(generation=3),
        messages=[],
    )
    value.say = value.messages.append
    value.run_command = lambda command: M.run_command(value, command.split())
    C.begin_frame(value, 120, 40)
    return value


def key(jid="101", metric="cpu", attempt=None, scope="resource-series"):
    return (scope, jid, metric, "%", attempt, None, None, 3)


def draw(app, identity=None, *, width=70, row=2, column=4, running=True, ascii_=False):
    identity = identity or key()
    rows, hits = M.controls(
        L.Glyphs(ascii_), app, identity, width, running=running, row=row, column=column
    )
    C.publish(app, app.width, app.height)
    return rows, hits


def current(app):
    return M.initialize(app)["records"][0]


def enable(app, identity=None):
    identity = identity or key()
    draw(app, identity)
    assert M.set_enabled(app, identity, True)
    return current(app)


@pytest.mark.parametrize("value", [5.0, 1.0, 0.1, 0.01, 0.001])
def test_log_mapping_is_reversible_and_endpoints_exact(value):
    assert M.delta_at(M.fraction(value)) == pytest.approx(value)
    assert 0 <= M.fraction(value) <= 1
    assert M.delta_at(0) == 5.0 and M.delta_at(1) == 0.001
    assert M.delta_at(0.5) == pytest.approx(math.sqrt(5 * 0.001))


@pytest.mark.parametrize("ascii_", [False, True])
@pytest.mark.parametrize("width", [24, 25, 32, 35, 36, 50, 120])
def test_controls_always_fit_one_row_with_two_labeled_ends(app, ascii_, width):
    rows, hits = draw(app, width=width, ascii_=ascii_, column=0)
    assert len(rows) == 1 and L.vlen(L.row_text(rows[0])) == width
    assert "5s" in L.row_text(rows[0]) and "1ms" in L.row_text(rows[0])
    assert len(hits) == 2
    if ascii_:
        assert L.row_text(rows[0]).isascii()
    assert all(0 <= hit[2]["left"] < hit[2]["right"] <= width for hit in hits)
    geometry = current(app)
    M.set_enabled(app, key(), True)
    C.begin_frame(app, 120, 40)
    draw(app, width=width, ascii_=ascii_, column=0)
    assert current(app).slider_full == geometry.slider_full


def test_slider_state_is_independent_for_metrics_jobs_and_attempts(app):
    one = key()
    two = key(metric="memory")
    otherjob = key("102")
    attempt = key(attempt="new-start")
    draw(app, one)
    M.set_delta(app, one, 0.1)
    M.set_enabled(app, one, True)
    draw(app, two, row=4)
    M.set_delta(app, two, 1.0)
    draw(app, otherjob, row=6)
    M.set_delta(app, otherjob, 0.01)
    assert M.window(app, one, now=100.0) == (99.9, 100.0)
    assert M.window(app, two, now=100.0) is None
    draw(app, attempt, row=8)
    assert not M.enabled(app, one)
    assert M.initialize(app)["entries"][one]["delta"] == 0.1
    assert not M.enabled(app, attempt)
    assert M.initialize(app)["entries"][otherjob]["delta"] == 0.01


def test_area_companion_reads_exact_same_canonical_window_with_one_control_row(app):
    curve = key()
    area = key(scope="resource-area")
    enable(app, curve)
    M.set_delta(app, curve, 0.001)
    assert M.canonical(area) == curve
    assert M.window(app, area, now=100.0) == M.window(app, curve, now=100.0)
    assert len(M.initialize(app)["records"]) == 1


@pytest.mark.parametrize("status", [False, None, "RUNNING", 1])
def test_only_explicit_current_running_eligibility_creates_controls(app, status):
    enable(app)
    C.begin_frame(app, 120, 40)
    rows, hits = draw(app, running=status)
    assert rows == hits == []
    assert M.window(app, key(), now=100.0) is None
    assert M.initialize(app)["records"] == ()


def test_finished_removed_and_mutated_jobs_disable_live_without_full_snapshot(app):
    job = Job("101", "running", "cpu", "RUNNING", submit="s", start="r")
    app.store = SimpleNamespace(
        jobs=[job], snapshot=lambda: pytest.fail("live took a full snapshot")
    )
    identity = key(attempt="s|r")
    enable(app, identity)
    assert M.window(app, identity, now=100.0) == (95.0, 100.0)
    job.state = "COMPLETED"
    M.tick(app)
    assert not M.enabled(app, identity) and M.window(app, identity, now=100.0) is None
    job.state = "RUNNING"
    M.set_running(app, identity, True)
    M.set_enabled(app, identity, True)
    app.store.jobs = []
    M.tick(app)
    assert M.window(app, identity, now=100.0) is None


def test_old_native_attempt_cannot_be_enabled_again_after_inplace_restart(app):
    job = Job("101", "same job ID", "cpu", "RUNNING", submit="s", start="r")
    app.store = SimpleNamespace(jobs=[job])
    old = key(attempt="s|r")
    enable(app, old)
    job.start = "new"
    assert M.window(app, old, now=100.0) is None
    assert not M.set_enabled(app, old, True)
    new = key(attempt="s|new")
    draw(app, new)
    assert M.set_enabled(app, new, True)
    assert M.window(app, new, now=100.0) == (95.0, 100.0)


def test_clock_anchored_window_never_requests_sampler_or_source_io(app, monkeypatch):
    app.store = SimpleNamespace(
        snapshot=lambda: pytest.fail("live took a full snapshot")
    )
    app.research.request = lambda *args: pytest.fail("live requested metrics")
    app.research.current = lambda *args: pytest.fail("live read a source cache")
    app.sampler = SimpleNamespace(
        refresh_all=lambda: pytest.fail("live refreshed scheduler")
    )
    enable(app)
    M.set_delta(app, key(), 0.001)
    monkeypatch.setattr(clock, "now", lambda: 100.0)
    assert M.window(app, key()) == (99.999, 100.0)
    for i in range(1000):
        assert M.window(app, key(), now=100.0 + i) == (99.999 + i, 100.0 + i)
    assert M.window(app, key(), now=float("nan")) is None
    assert M.window(app, key(), now=float("inf")) is None


def test_raw_slider_drag_clamps_log_endpoints_and_keyboard_adjusts_same_metric(app):
    control = enable(app)
    y = control.slider.top
    left = control.slider_full.left
    right = control.slider_full.right - 1
    assert M.handle_mouse(app, y, left, button="press")
    assert M.active(app)
    assert M.handle_mouse(app, y, right, button="motion")
    assert M.initialize(app)["entries"][key()]["delta"] == 0.001
    assert M.handle_mouse(app, y, right + 50, button="release")
    assert not M.active(app) and M.initialize(app)["entries"][key()]["delta"] == 0.001
    assert M.handle_key(app, "home")
    assert M.initialize(app)["entries"][key()]["delta"] == 5.0
    assert M.handle_key(app, "right")
    assert 0.001 < M.initialize(app)["entries"][key()]["delta"] < 5.0
    assert M.handle_key(app, "end")
    assert M.initialize(app)["entries"][key()]["delta"] == 0.001
    assert not M.handle_key(app, "down") and M.initialize(app)["focus"] is None


@pytest.mark.parametrize(
    "change",
    ["width", "height", "tab", "mode", "job", "menu", "project", "run", "source"],
)
def test_slider_stale_context_cancels_restores_preview_and_consumes_release(
    app, change
):
    control = enable(app)
    M.handle_mouse(app, control.slider.top, control.slider.right - 1, button="press")
    assert M.initialize(app)["entries"][key()]["delta"] != 5.0
    if change == "width":
        app.width += 1
    elif change == "height":
        app.height += 1
    elif change == "tab":
        app.tab = "research"
    elif change == "mode":
        app.mode = "confirm"
    elif change == "job":
        app.selected_id = "102"
    elif change == "menu":
        app.toolbar_state["menu"] = "View"
    elif change == "project":
        app.project_state["root"] = "/new"
    elif change == "run":
        app.project_state["binding"] = {"job_id": "101", "run_id": "new"}
    else:
        C.begin_frame(app, 120, 40)
        draw(app, key(metric="other"))
    assert M.handle_mouse(
        app, control.slider.top, control.slider.right - 1, button="release"
    )
    assert not M.active(app) and M.initialize(app)["entries"][key()]["delta"] == 5.0


def test_slider_geometry_change_timeout_vertical_outside_and_escape_cancel(app):
    control = enable(app)
    M.handle_mouse(app, control.slider.top, control.slider.right - 1, button="press")
    C.begin_frame(app, 120, 40)
    draw(app, width=60)
    assert not M.active(app) and M.initialize(app)["entries"][key()]["delta"] == 5.0
    for mode in ("timeout", "outside", "escape"):
        control = current(app)
        M.handle_mouse(
            app, control.slider.top, control.slider.right - 1, button="press"
        )
        if mode == "timeout":
            M.tick(
                app,
                now=M.initialize(app)["capture"]["last"] + M.CAPTURE_TIMEOUT + 0.001,
            )
        elif mode == "outside":
            M.handle_mouse(
                app, control.slider.top + 3, control.slider.right - 1, button="release"
            )
        else:
            assert M.handle_key(app, "esc")
        assert not M.active(app) and M.initialize(app)["entries"][key()]["delta"] == 5.0


def test_layout_pipeline_maps_live_controls_and_clips_them_with_source_document(app):
    marker = C.mark(app)
    rows, _ = M.controls(L.Glyphs(False), app, key(), 60, row=8, column=2)
    records = C.take_since(app, marker)
    assert records[0].kind == "live-controls"
    mapped = C.map_records(records, {8: 15}, dx=10, dy=3, clip=(18, 12, 19, 72))
    C.put_records(app, mapped)
    C.publish(app, 120, 40)
    control = current(app)
    assert control.rect == I.Rect(18, 12, 19, 72)
    assert M.descriptors(app)[0]["rect"].top == 18
    assert M.descriptors(app)[1]["rect"].right <= 72
    C.begin_frame(app, 120, 40)
    C.put_records(app, C.map_records(records, {8: 100}, clip=(0, 0, 40, 120)))
    C.publish(app, 120, 40)
    assert M.descriptors(app) == ()


def test_xy_capture_temporarily_freezes_clock_mapping_then_commit_stops_live(app):
    enable(app)
    metadata = {
        "plot_rect": (5, 10, 13, 60),
        "x_bounds": (95.0, 100.0),
        "y_bounds": (0.0, 100.0),
        "valid": True,
        "has_data": True,
    }
    C.record(app, key(), metadata)
    C.publish(app, 120, 40)
    assert C.handle_mouse(app, 6, 15, button="press")
    assert M.window(app, key(), now=999.0) == (95.0, 100.0)
    assert M.document_interval(app) is None
    C.cancel(app)
    assert M.window(app, key(), now=999.0) == (994.0, 999.0) and M.enabled(app, key())
    C.handle_mouse(app, 6, 15, button="press")
    C.handle_mouse(app, 11, 45, button="release")
    assert not M.enabled(app, key()) and M.window(app, key(), now=999.0) is None
    assert C.bounds(app, key())
    assert C.undo(app, key()) and C.bounds(app, key()) is None


def test_enabling_live_removes_line_and_area_boxes_only_for_this_metric(app):
    draw(app)
    area = key(scope="resource-area")
    other = key(metric="memory")
    C.initialize(app)["zoom"][key()] = {
        "x": (1.0, 2.0),
        "y": (3.0, 4.0),
        "scale": "linear",
        "undo": [],
    }
    C.initialize(app)["zoom"][area] = {
        "x": (1.0, 2.0),
        "y": (3.0, 4.0),
        "scale": "linear",
        "undo": [],
    }
    C.initialize(app)["zoom"][other] = {
        "x": (1.0, 2.0),
        "y": (3.0, 4.0),
        "scale": "linear",
        "undo": [],
    }
    M.set_enabled(app, key(), True)
    assert (
        C.bounds(app, key()) is None
        and C.bounds(app, area) is None
        and C.bounds(app, other)
    )
    M.set_enabled(app, key(), False)
    assert M.window(app, key(), now=100.0) is None


def test_empty_one_millisecond_graph_still_gets_bounded_document_deadline(app):
    enable(app)
    M.set_delta(app, key(), 0.001)
    assert C.initialize(app)["plots"] == ()
    assert M.document_interval(app) == 0.1
    assert M.document_revision(app) > 0
    C.begin_frame(app, 120, 40)
    C.publish(app, 120, 40)
    assert M.document_interval(app) is None


def test_cached_feedback_keeps_pointer_and_arrow_focus_without_activating_twice(app):
    draw(app)
    canvas = [[(" " * 120, "")] for _ in range(40)]
    I.publish(app, canvas, [], 120, 40, extra_controls=M.descriptors(app))
    control = current(app)
    I.handle_mouse(app, control.toggle.top, control.toggle.left, button="motion")
    assert M.handle_mouse(app, control.toggle.top, control.toggle.left, button="left")
    assert M.enabled(app, key())
    state = I.initialize(app)
    assert state["focused"] == "metric-live:" + control.token and state["active"]
    painted = M.feedback(app, L.Glyphs(False))
    assert any(
        "under" in style and "bg:track" in style
        for _, _, row in painted
        for _, style in row
    )
    assert I.handle_key(app, "right")
    assert state["focused"] == "metric-window:" + control.token
    assert I.handle_key(app, "enter")
    assert M.initialize(app)["focus"] == control.token
    assert M.handle_key(app, "right")
    assert M.initialize(app)["entries"][key()]["delta"] < 5.0


def test_commands_only_target_visible_exact_running_source(app):
    draw(app)
    token = current(app).token
    assert M.run_command(app, ["metric-live", token, "on"])
    assert M.enabled(app, key())
    assert M.run_command(app, ["metric-window", token, "0.001"])
    assert M.initialize(app)["entries"][key()]["delta"] == 0.001
    for invalid in ("nan", "inf", "0", "6", "bad"):
        assert M.run_command(app, ["metric-window", token, invalid])
        assert M.initialize(app)["entries"][key()]["delta"] == 0.001
    assert M.run_command(app, ["metric-live", "old-token", "on"])
    C.begin_frame(app, 120, 40)
    draw(app, running=False)
    assert M.run_command(app, ["metric-live", token, "on"]) and not M.enabled(
        app, key()
    )
    assert not M.run_command(app, ["unrelated"])


@pytest.fixture
def palette_dashboard(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: 200.0)
    cfg = Config({"animations": False, "startup": {"enabled": False}, "log_lines": 0})
    store = Store(persist=False)
    store.jobs = [
        Job(
            str(jid),
            "train-" + str(jid),
            "cpu",
            "RUNNING",
            cpus=4,
            mem_req="8G",
            submit="submit",
            start="start",
        )
        for jid in (7, 8)
    ]
    for job in store.jobs:
        for index in range(20):
            store.record(
                job.id,
                {
                    "k": "live",
                    "t": 180.0 + index,
                    "cpu": index / 25,
                    "rss": (1 + index / 20) * 1024**3,
                },
            )
    app = App(store, None, None, cfg, "test", interactive=False)
    views = Views(L.Glyphs(False), cfg)
    app.views_ref = views
    app.tab, app.selected_id, app.analytics_job = "analytics", "7", "7"
    return SimpleNamespace(app=app, store=store, views=views)


def palette_frame(dashboard, *, width=160, height=52):
    snapshot = dashboard.store.snapshot()
    rows, hits = dashboard.views.compose(snapshot, dashboard.app, width, height)
    dashboard.views.overlay(snapshot, dashboard.app, width, height)
    return rows, hits


def type_palette_command(dashboard, command, *, before_enter=None):
    app = dashboard.app
    origin = app.mode
    app.handle(":")
    assert app.mode == "palette"
    palette_frame(dashboard)
    assert M.initialize(app)["records"] == ()
    assert M.descriptors(app) == ()
    assert not M.handle_mouse(app, 0, 0, button="left")
    assert not M.handle_key(app, "right")
    for char in command:
        app.handle("space" if char == " " else char)
    assert app.palette_edit == command
    palette_frame(dashboard)
    if before_enter:
        before_enter(dashboard)
    app.handle("enter")
    assert app.mode == origin


def test_actual_app_palette_live_commands_restore_main_without_a_redraw(
    palette_dashboard,
):
    dashboard = palette_dashboard
    palette_frame(dashboard)
    control = current(dashboard.app)
    type_palette_command(dashboard, "metric-live " + control.token + " on")
    assert M.enabled(dashboard.app, control.key)
    assert M.initialize(dashboard.app)["records"] == ()
    palette_frame(dashboard)
    type_palette_command(dashboard, "metric-window " + control.token + " 0.001")
    assert M.initialize(dashboard.app)["entries"][control.key]["delta"] == 0.001
    palette_frame(dashboard)
    type_palette_command(dashboard, "metric-live " + control.token + " off")
    assert not M.enabled(dashboard.app, control.key)


@pytest.mark.parametrize(
    "change", ["page", "job", "attempt", "finished", "resize", "scroll", "split"]
)
def test_actual_palette_rejects_a_token_after_document_change(
    palette_dashboard, change
):
    dashboard = palette_dashboard
    palette_frame(dashboard)
    control = current(dashboard.app)

    def change_document(value):
        app = value.app
        if change == "page":
            app.tab = "jobs"
        elif change == "job":
            app.selected_id = app.analytics_job = "8"
        elif change == "attempt":
            value.store.jobs[0].start = "new-start"
        elif change == "finished":
            value.store.jobs[0].state = "COMPLETED"
        elif change == "resize":
            palette_frame(value, width=130)
        elif change == "scroll":
            app.analytics_document_state["top"] += 3
        else:
            app.layout_state.ratio += 5

    type_palette_command(
        dashboard, "metric-live " + control.token + " on", before_enter=change_document
    )
    assert not M.enabled(dashboard.app, control.key)
    assert "visible Live control" in dashboard.app.message


def open_reported_modal(dashboard):
    app = dashboard.app
    app.analysis_result_job = "7"
    app.analysis_result_generation = None
    app.analysis_result = {
        "path": "/run/metrics.jsonl",
        "series": {"loss": [{"t": 196.0, "value": 2.0}, {"t": 199.0, "value": 1.0}]},
    }
    app.run_command("chart loss")
    assert app.mode == "analysis"
    palette_frame(dashboard)
    return current(app)


def test_actual_app_palette_commands_restore_exact_chart_modal(palette_dashboard):
    dashboard = palette_dashboard
    control = open_reported_modal(dashboard)
    assert control.layer == 1
    type_palette_command(dashboard, "metric-live " + control.token + " on")
    assert dashboard.app.mode == "analysis" and M.enabled(dashboard.app, control.key)
    palette_frame(dashboard)
    type_palette_command(dashboard, "metric-window " + control.token + " 0.1")
    assert M.initialize(dashboard.app)["entries"][control.key]["delta"] == 0.1


@pytest.mark.parametrize("modal", [False, True])
def test_palette_slider_focus_survives_tick_and_first_restored_frame(
    palette_dashboard, modal
):
    dashboard = palette_dashboard
    if modal:
        control = open_reported_modal(dashboard)
    else:
        palette_frame(dashboard)
        control = current(dashboard.app)
    type_palette_command(dashboard, "metric-window " + control.token + " focus")
    state = M.initialize(dashboard.app)
    assert state["focus"] == control.token and state["pending_focus"]
    dashboard.app.tick()
    dashboard.app.tick()
    assert state["focus"] == control.token and state["pending_focus"]
    assert M.descriptors(dashboard.app) == ()
    palette_frame(dashboard)
    assert state["focus"] == control.token and state["pending_focus"] is None
    dashboard.app.handle("right")
    assert state["entries"][control.key]["delta"] < M.MAX_DELTA
    dashboard.app.handle("down")
    assert state["focus"] is None


@pytest.mark.parametrize(
    "change", ["page", "job", "attempt", "finished", "resize", "scroll", "menu"]
)
def test_palette_pending_focus_rejects_stale_context_before_first_frame(
    palette_dashboard, change
):
    dashboard = palette_dashboard
    palette_frame(dashboard)
    control = current(dashboard.app)
    type_palette_command(dashboard, "metric-window " + control.token + " focus")
    app = dashboard.app
    if change == "page":
        app.tab = "jobs"
    elif change == "job":
        app.selected_id = app.analytics_job = "8"
    elif change == "attempt":
        dashboard.store.jobs[0].start = "new-start"
    elif change == "finished":
        dashboard.store.jobs[0].state = "COMPLETED"
    elif change == "resize":
        app.width = 130
    elif change == "scroll":
        app.analytics_document_state["top"] += 3
    else:
        app.toolbar_state["menu"] = "view"
    app.tick()
    state = M.initialize(app)
    assert state["focus"] is None and state["pending_focus"] is None
    assert state["entries"][control.key]["delta"] == M.MAX_DELTA


def test_palette_pending_focus_clears_when_fresh_main_publication_hides_control(
    palette_dashboard,
):
    dashboard = palette_dashboard
    palette_frame(dashboard)
    control = current(dashboard.app)
    type_palette_command(dashboard, "metric-window " + control.token + " focus")
    C.begin_frame(dashboard.app, dashboard.app.width, dashboard.app.height)
    C.publish(dashboard.app)
    state = M.initialize(dashboard.app)
    assert state["focus"] is None and state["pending_focus"] is None


@pytest.mark.parametrize("change", ["source", "metric", "modal", "hidden"])
def test_actual_palette_modal_token_rejects_changed_or_hidden_chart(
    palette_dashboard, change
):
    dashboard = palette_dashboard
    control = open_reported_modal(dashboard)

    def change_document(value):
        app = value.app
        if change == "source":
            app.analysis_result["path"] = "/other/metrics.jsonl"
        elif change == "metric":
            app.analysis_state["metric"] = "accuracy"
        elif change == "modal":
            app.analysis_state["modal"] = "inspect"
        else:
            app.command_state["origin_mode"] = "main"

    if change == "hidden":
        app = dashboard.app
        app.handle(":")
        palette_frame(dashboard)
        for char in "metric-live " + control.token + " on":
            app.handle("space" if char == " " else char)
        change_document(dashboard)
        app.handle("enter")
        assert app.mode == "main"
    else:
        type_palette_command(
            dashboard,
            "metric-live " + control.token + " on",
            before_enter=change_document,
        )
    assert not M.enabled(dashboard.app, control.key)


def test_transient_state_caches_and_registry_remain_bounded(app):
    for n in range(M.MAX_METRICS + 20):
        M.set_running(app, key(jid=str(n)), True)
    state = M.initialize(app)
    assert len(state["entries"]) == len(state["current"]) == M.MAX_METRICS
    assert "save" not in dir(M) and "restore" not in dir(M)
    assert state["counter"] == M.MAX_METRICS + 20


def test_ascii_default_crosshair_uses_real_views_ref(app):
    app.views_ref = SimpleNamespace(g=L.Glyphs(True))
    C.begin_frame(app, 120, 40)
    C.record(
        app,
        key(),
        {
            "plot_rect": (5, 10, 13, 60),
            "x_bounds": (0.0, 10.0),
            "y_bounds": (0.0, 100.0),
        },
    )
    C.publish(app, 120, 40)
    C.hover(app, 8, 30)
    assert any(row == [(".", "accent")] for _, _, row in C.feedback(app))


def test_running_job_beyond_ten_thousand_rows_stays_eligible_with_bounded_index(app):
    wanted = Job("10001", "visible far row", "cpu", "RUNNING", submit="s", start="r")
    app.store = SimpleNamespace(
        jobs=[Job(str(n), "earlier", "cpu", "PENDING") for n in range(10001)] + [wanted]
    )
    identity = key(jid="10001", attempt="s|r")
    draw(app, identity)
    assert M.set_enabled(app, identity, True)
    assert M.window(app, identity, now=100.0) == (95.0, 100.0)
    assert M.initialize(app)["job_map"] == {"10001": wanted}
    # Adding a second metric for this ID reuses the same bounded Job index.
    existing = M.initialize(app)["job_map"]
    second = key(jid="10001", metric="memory", attempt="s|r")
    draw(app, second)
    assert M.set_enabled(app, second, True)
    assert M.initialize(app)["job_map"] is existing
    wanted.state = "FAILED"
    assert M.window(app, second, now=100.0) is None


def test_inplace_job_append_refreshes_only_wanted_id_index(app):
    first = Job("101", "first", "cpu", "RUNNING")
    app.store = SimpleNamespace(jobs=[first])
    draw(app)
    assert M.set_enabled(app, key(), True)
    second = Job("102", "appended", "cpu", "RUNNING")
    app.store.jobs.append(second)
    identity = key(jid="102")
    draw(app, identity)
    assert M.set_enabled(app, identity, True)
    assert M.window(app, identity, now=100.0) == (95.0, 100.0)
    assert len(M.initialize(app)["job_map"]) == 2


def test_reported_scheduler_attempt_fallback_rejects_previous_requeue(app):
    job = Job("101", "reported", "cpu", "RUNNING", submit="S", start="StartA")
    app.store = SimpleNamespace(jobs=[job])
    old = (
        "reported-metric",
        "101",
        "loss",
        "metrics.jsonl",
        "scheduler:S|StartA",
        None,
        None,
        3,
    )
    draw(app, old)
    assert M.set_enabled(app, old, True)
    assert M.window(app, old, now=100.0) == (95.0, 100.0)
    job.start = "StartB"
    assert M.window(app, old, now=100.0) is None
    assert not M.set_enabled(app, old, True)
    new = (*old[:4], "scheduler:S|StartB", *old[5:])
    draw(app, new)
    assert M.set_enabled(app, new, True)
    assert M.window(app, new, now=100.0) == (95.0, 100.0)


def test_project_declared_attempt_stays_opaque_to_scheduler_start_labels(app):
    job = Job("101", "project reported", "cpu", "RUNNING", submit="S", start="StartA")
    app.store = SimpleNamespace(jobs=[job])
    identity = (
        "reported-metric",
        "101",
        "loss",
        "metrics.jsonl",
        4,
        "/project",
        "run-4",
        3,
    )
    draw(app, identity)
    assert M.set_enabled(app, identity, True)
    assert M.window(app, identity, now=100.0) == (95.0, 100.0)


def test_stale_running_snapshot_cannot_show_controls_for_finished_actual_job(app):
    actual = Job(
        "101", "finished behind frozen view", "cpu", "COMPLETED", submit="s", start="r"
    )
    app.store = SimpleNamespace(jobs=[actual])
    identity = key(attempt="s|r")
    rows, hits = draw(app, identity, running=True)
    assert rows == hits == []
    assert M.descriptors(app) == () and M.window(app, identity, now=100.0) is None


def test_stale_native_attempt_controls_are_hidden_even_if_snapshot_says_running(app):
    actual = Job("101", "new attempt", "cpu", "RUNNING", submit="s", start="new")
    app.store = SimpleNamespace(jobs=[actual])
    rows, hits = draw(app, key(attempt="s|old"), running=True)
    assert rows == hits == []
    assert M.descriptors(app) == ()


def test_same_length_inplace_job_slot_replacement_uses_new_actual_attempt(app):
    old_job = Job("101", "old slot", "cpu", "RUNNING", submit="S", start="A")
    app.store = SimpleNamespace(jobs=[old_job])
    old = key(attempt="S|A")
    enable(app, old)
    fresh_job = Job("101", "new slot", "cpu", "RUNNING", submit="S", start="B")
    app.store.jobs[0] = fresh_job
    assert M.window(app, old, now=100.0) is None
    fresh = key(attempt="S|B")
    C.begin_frame(app, 120, 40)
    rows, _ = draw(app, fresh)
    assert len(rows) == 1 and M.set_enabled(app, fresh, True)
    assert M.window(app, fresh, now=100.0) == (95.0, 100.0)
    assert M.initialize(app)["job_map"]["101"] is fresh_job
