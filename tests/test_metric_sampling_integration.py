"""Per-metric sliders reach real collectors through native and nested layouts."""
from copy import deepcopy
from types import SimpleNamespace
import re

import pytest

from tower import (chart_interaction as charts, clock, layout,
                   metric_live, metric_sampling, refresh_rate, screen,
                   text_selection)
from tower.config import Config
from tower.controller import App
from tower.model import Job, Live, Store
from tower.research import ResearchHub
from tower.sampler import Sampler
from tower.views import Views


MOUSE = SimpleNamespace(BUTTON1_CLICKED=1, BUTTON1_PRESSED=2, BUTTON1_RELEASED=4,
    BUTTON1_DOUBLE_CLICKED=8, BUTTON3_CLICKED=16, BUTTON3_PRESSED=32,
    BUTTON4_PRESSED=64, BUTTON5_PRESSED=128, REPORT_MOUSE_POSITION=256, BUTTON_SHIFT=512)


@pytest.fixture
def dashboard(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: 200.0)
    cfg = Config({"animations": False, "startup": {"enabled": False}, "log_lines": 0})
    store = Store(persist=False)
    store.jobs = [Job(str(jid), "job-" + str(jid), "cpu", "RUNNING", cpus=4,
                      mem_req="8G", submit="submit", start="start") for jid in (7, 8)]
    for job in store.jobs:
        for index in range(20):
            store.record(job.id, {"k": "live", "t": 180.0 + index,
                                  "cpu": (index + 1) / 25, "rss": (1 + index / 20) * 1024**3})
    slurm = SimpleNamespace()
    sampler = Sampler(slurm, store, {"live": 30.0, "gpu": 5.0, "trace": 5.0, "jobs": 2.0}, [])
    # The real scheduler is used for demands and labels without admitting
    # automatic background commands while rendering a test dashboard.
    for health in store.health.values():
        health.enabled = False
    app = App(store, sampler, None, cfg, "tester", interactive=False)
    views = Views(layout.Glyphs(False), cfg)
    app.views_ref = views
    app.selected_id = app.analytics_job = "7"

    def draw(tab="analytics"):
        app.tab = tab
        if tab == "jobs":
            app.job_panel_state.update(mode="analytics", analytics_view="job")
        snap = store.snapshot()
        rows, hits = views.compose(snap, app, 190, 90)
        views.overlay(snap, app, 190, 90)
        return rows, hits

    yield SimpleNamespace(app=app, store=store, sampler=sampler, slurm=slurm, views=views, draw=draw)
    sampler.shutdown()
    if app.research:
        app.research.close()


def controls(app):
    return metric_live.initialize(app)["records"]


def entry(app, control):
    return metric_live.initialize(app)["entries"][control.key]


def point(rect, *, right=False):
    return rect.top, rect.right - 1 if right else rect.left


@pytest.mark.parametrize("tab", ["analytics", "jobs"])
def test_native_and_details_mouse_drags_change_collection_independently_of_display(dashboard, tab):
    d, app = dashboard, dashboard.app
    _, hits = d.draw(tab)
    control = controls(app)[0]
    assert control.rate_slider and control.rate_slider_full
    app.click(*point(control.rate_slider), hits, button="press")
    app.click(*point(control.rate_slider_full, right=True), hits, button="drag")
    app.click(*point(control.rate_slider_full, right=True), hits, button="release")
    assert entry(app, control)["rate"] == 100
    assert d.sampler.sampling_interval("live", "7", control.key[4]) == .5
    assert d.sampler.sampling_interval("live", "8") == 30
    assert entry(app, control)["delta"] == 5.0
    assert not metric_live.enabled(app, control.key)

    app.click(*point(control.slider), hits, button="press")
    app.click(*point(control.slider_full, right=True), hits, button="release")
    assert entry(app, control)["delta"] == .001
    assert entry(app, control)["rate"] == 100
    assert d.sampler.sampling_interval("live", "7", control.key[4]) == .5


@pytest.mark.parametrize("tab", ["analytics", "jobs"])
@pytest.mark.parametrize("kind", ["window", "sampling"])
@pytest.mark.parametrize("route", ["app", "screen_pressed", "screen_clicked", "screen_pressed_motion"])
def test_right_reset_is_consumed_before_any_job_or_line_deselect(dashboard, monkeypatch, tab, kind, route):
    d, app = dashboard, dashboard.app
    _, hits = d.draw(tab)
    control = controls(app)[0]
    metric_live.set_delta(app, control.key, .01)
    metric_live.set_rate(app, control.key, 100)
    refresh_rate.set_multiplier(app, 10)
    app.marks = {"7", "8"}
    app.sel_anchor, app.sel_end = 3, 9
    app.logs.selection_path = "/logs/train.log"
    app.logs.selection_anchor, app.logs.selection_end = 2, 8
    selection = {"key": "existing", "context": "existing", "anchor": 2, "end": 8}
    text_selection.initialize(app).update(selection=deepcopy(selection), explicit=True)
    monkeypatch.setattr(d.store, "snapshot", lambda *a, **k: pytest.fail("reset took a scheduler snapshot"))
    monkeypatch.setattr(d.sampler, "refresh_all", lambda: pytest.fail("reset requested scheduler work"))
    monkeypatch.setattr(d.views, "metric_curve", lambda *a, **k: pytest.fail("reset rendered metrics"))
    if app.research:
        monkeypatch.setattr(app.research, "request", lambda *a, **k: pytest.fail("reset requested file reads"))
    y, x = point(control.slider if kind == "window" else control.rate_slider)
    if route == "app":
        app.click(y, x, hits, button="right")
    else:
        bits = MOUSE.BUTTON3_PRESSED if route.startswith("screen_pressed") else MOUSE.BUTTON3_CLICKED
        if route == "screen_pressed_motion":
            bits |= MOUSE.REPORT_MOUSE_POSITION
        screen._apply_input(app, ("mouse", (0, x, y, 0, bits)), hits, MOUSE)
    assert entry(app, control)["delta"] == (5.0 if kind == "window" else .01)
    assert entry(app, control)["rate"] == (1 if kind == "sampling" else 100)
    assert refresh_rate.multiplier(app) == 10
    assert d.sampler.sampling_interval("live", "7", control.key[4]) == (3.0 if kind == "sampling" else .5)
    assert app.marks == {"7", "8"} and app.selected_id == "7"
    assert (app.sel_anchor, app.sel_end) == (3, 9)
    assert (app.logs.selection_path, app.logs.selection_anchor, app.logs.selection_end) == ("/logs/train.log", 2, 8)
    assert text_selection.initialize(app)["selection"] == selection
    assert text_selection.initialize(app)["explicit"]
    assert not app.quit and app.mode == "main"


@pytest.mark.parametrize("tab", ["analytics", "jobs"])
def test_shared_cpu_memory_labels_follow_effective_collector_and_global_rate(dashboard, tab):
    d, app = dashboard, dashboard.app
    d.draw(tab)
    live_controls = [control for control in controls(app) if metric_sampling.source(control.key) == "live"]
    assert len(live_controls) >= 2
    cpu, memory = live_controls[:2]
    assert metric_live.set_rate(app, cpu.key, 4)
    assert metric_sampling.cadence(app, memory.key) == 7.5
    assert entry(app, memory)["rate"] == 1
    rows, _ = d.draw(tab)
    for control in (cpu, memory):
        assert "7.5s" in layout.row_text(rows[control.rect.top])
    refresh_rate.set_multiplier(app, 10)
    assert metric_sampling.cadence(app, cpu.key) == .75
    assert metric_sampling.cadence(app, memory.key) == .75
    rows, _ = d.draw(tab)
    for control in controls(app):
        text = layout.row_text(rows[control.rect.top])
        assert not re.search(r"\b\d+x\b", text)
        if metric_sampling.source(control.key) == "live":
            assert "750ms" in text
    assert d.sampler.intervals["live"] == 30.0


def test_restarted_attempt_drops_demands_and_old_published_input_cannot_reactivate(dashboard):
    d, app = dashboard, dashboard.app
    _, hits = d.draw()
    old = controls(app)[0]
    assert metric_live.set_rate(app, old.key, 100)
    d.store.jobs[0].start = "restart"
    metric_live.tick(app)
    assert d.sampler.sampling_interval("live", "7") == 30.0
    app.click(*point(old.rate_slider, right=True), hits, button="left")
    assert not metric_live.set_rate(app, old.key, 100)
    d.draw()
    new = controls(app)[0]
    assert new.key[4] != old.key[4]
    assert entry(app, new)["rate"] == 1
    assert d.sampler.sampling_interval("live", "7", new.key[4]) == 30.0


def test_hover_feedback_reads_no_sources_and_never_admits_scheduler_work(dashboard, monkeypatch):
    d, app = dashboard, dashboard.app
    _, hits = d.draw()
    control = controls(app)[0]
    monkeypatch.setattr(d.store, "snapshot", lambda *a, **k: pytest.fail("hover took a scheduler snapshot"))
    monkeypatch.setattr(d.sampler, "round", lambda *a, **k: pytest.fail("hover admitted sampler work"))
    monkeypatch.setattr(d.sampler, "src_live", lambda *a, **k: pytest.fail("hover sampled live counters"))
    monkeypatch.setattr(d.sampler, "src_gpu", lambda *a, **k: pytest.fail("hover sampled GPU counters"))
    monkeypatch.setattr(d.views, "metric_curve", lambda *a, **k: pytest.fail("hover rendered data"))
    for index in range(50):
        y, x = point(control.rate_slider)
        x += index % (control.rate_slider.right - control.rate_slider.left)
        app.click(y, x, hits, button="motion")
        metric_live.feedback(app, d.views.g)
    assert entry(app, control)["rate"] == 1
    assert not d.sampler._metric_requests


def test_accelerated_job_probes_do_not_accelerate_other_jobs(dashboard, monkeypatch):
    d, app = dashboard, dashboard.app
    d.draw()
    control = controls(app)[0]
    now, calls = [100.0], []
    monkeypatch.setattr("tower.sampler.time.monotonic", lambda: now[0])

    def live(job, previous, timestamp):
        calls.append(job.id)
        return Live(rate=.5, rss=1024**3, t=timestamp), previous, []

    d.slurm.live = live
    assert metric_live.set_rate(app, control.key, 60)
    d.sampler.run_source("live")
    assert calls == ["7", "8"]
    now[0] += .5
    d.sampler.run_source("live")
    assert calls == ["7", "8", "7"]
    now[0] += 29.5
    d.sampler.run_source("live")
    assert calls == ["7", "8", "7", "7", "8"]
    assert not d.store.health["live"].errors


@pytest.mark.parametrize("remote,floor", [(False, .25), (True, 1.5)])
def test_reported_metric_demand_changes_reader_cadence_without_rewriting_producer(dashboard, tmp_path, remote, floor):
    d, app = dashboard, dashboard.app
    source = tmp_path / "metrics.jsonl"
    original = b'{"metric":"loss","value":1,"t":199}\n'
    source.write_bytes(original)
    hub = ResearchHub(app.cfg, SimpleNamespace(remote=remote))
    app.research = hub
    binding = {"job_id": "7", "project_root": str(tmp_path), "run_id": "run7", "attempt": "trial1"}
    app.project_state.update(root=str(tmp_path), binding=binding)
    identity = ("reported-metric", "7", "loss", str(source), "trial1", str(tmp_path), "run7", hub.generation)
    context = {"view": "experiment", "jid": "7", "job": d.store.jobs[0], "binding": binding, "generation": hub.generation}
    charts.begin_frame(app, 190, 90)
    metric_live.controls(d.views.g, app, identity, 100, running=True, row=8, column=10)
    charts.publish(app, 190, 90)
    assert metric_live.set_rate(app, identity, 100)
    assert hub.refresh_interval(context) == floor
    assert metric_sampling.cadence(app, identity) == floor
    assert hub.refresh_interval({**context, "jid": "8", "job": d.store.jobs[1]}) == 5.0
    assert hub.refresh_interval({**context, "view": "passport"}) == 5.0
    assert hub.pending is None and hub.future is None
    assert source.read_bytes() == original
    assert not d.sampler._metric_requests
    hub.configure(metrics_file=str(source))
    assert not hub.metric_sampling
    assert hub.refresh_interval(context) == 5.0
