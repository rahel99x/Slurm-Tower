"""Real table/document rails preserve source selection and viewport geometry."""
from types import SimpleNamespace

import pytest

from tower import advisor, chart_interaction as C, history_browser as H, layout as L, recent_history as R, scrollbars as S, scrolling
from tower.config import Config
from tower.controller import App
from tower.model import Finished, Health, Job, Store
from tower.remote import LocalFiles
from tower.views import Views


@pytest.fixture
def tower(tmp_path):
    cfg = Config({"animations": False, "smooth_scrolling": False, "startup_animation": False,
                  "log_lines": 0, "workspace": {"density": "compact", "split": 50}})
    store = Store(persist=False)
    store.jobs = [Job(str(i), f"job-{i:03}", "cpu", "RUNNING", cpus=4, user="test")
                  for i in range(1, 61)]
    store.group = list(store.jobs)
    store.finished = [Finished(str(i), f"past-{i:03}", "COMPLETED", cpus=4,
                               elapsed="00:10:00") for i in range(101, 451)]
    store.health = {f"source{i:02}": Health(f"source{i:02}") for i in range(60)}
    app = App(store, None, None, cfg, "test", interactive=False)
    app.files = app.logs.files = LocalFiles()
    views = Views(L.Glyphs(False), cfg, files=app.files)
    app.views_ref = views
    app.table_state["groups"] = False
    value = SimpleNamespace(app=app, store=store, views=views, tmp_path=tmp_path)
    yield value
    if app.research:
        app.research.close()


def draw(tower, width=160, height=42):
    rows, hits = tower.views.compose(tower.store.snapshot(), tower.app, width, height)
    return rows, hits


def pane(tower, key):
    return next(item for item in S.initialize(tower.app)["panes"] if item.key == key)


def forbidden(*args, **kwargs):
    raise AssertionError("Scrollbar input fetched source observations or persisted preferences")


@pytest.mark.parametrize("tab,key", [("jobs", "jobs"), ("history", "history"),
                                     ("group", "group"), ("sources", "sources")])
def test_table_jump_preserves_source_marks_and_reaches_last_visible_row(tower, monkeypatch, tab, key):
    tower.app.enter_tab(tab)
    draw(tower)
    selected, marks = tower.app.selected_id, {"2", "3"}
    tower.app.marks = marks.copy()
    item = pane(tower, key)
    assert item.header and item.rect.top > item.header[0]
    with monkeypatch.context() as patch:
        patch.setattr(tower.store, "snapshot", forbidden)
        patch.setattr(tower.app, "save", forbidden)
        assert S.activate(tower.app, key, "bottom")
    assert tower.app.selected_id == selected and tower.app.marks == marks
    rows, hits = draw(tower)
    item = pane(tower, key)
    assert item.painted == item.limit and item.target == item.limit
    assert tower.app.selected_id == selected and tower.app.marks == marks
    assert all(L.vlen(L.row_text(row)) <= 160 for row in rows)
    identifiers = {value for _, kind, value in hits if kind in ("job", "fin", "group", "source")}
    expected = (tower.app.visible_ids[-1] if key == "jobs" else
                tower.app.history_jobs()[-1].id if key == "history" else
                tower.app.group_ids[-1] if key == "group" else tower.app.source_ids[-1])
    assert expected in identifiers
    assert S.activate(tower.app, key, "top")
    draw(tower)
    assert pane(tower, key).painted == 0


def test_recent_bottom_admits_older_observations_at_render_and_keeps_current_details(tower, monkeypatch):
    draw(tower)
    app, state = tower.app, R.initialize(tower.app)
    source, admitted = app.selected_id, len(app.recent_ids)
    item = pane(tower, "recent")
    assert item.count > admitted
    with monkeypatch.context() as patch:
        patch.setattr(tower.store, "snapshot", forbidden)
        patch.setattr(tower.app, "save", forbidden)
        assert S.activate(app, "recent", "bottom")
    assert len(app.recent_ids) == admitted and state.target > admitted
    _, hits = draw(tower)
    item = pane(tower, "recent")
    assert item.painted == item.limit
    assert "450" in {value for _, kind, value in hits if kind == "recent"}
    assert app.selected_id == source


@pytest.mark.parametrize("dock", ["left", "right", "top", "bottom"])
def test_history_dock_has_independent_smooth_scroll_and_nonoverlapping_jump_handle(tower, dock):
    tower.app.enter_tab("analytics")
    H._view(tower.app)["dock"] = dock
    rows, _ = draw(tower)
    app = tower.app
    selected = app.analytics_job
    item = pane(tower, "history-browser:analytics")
    y, left, _ = item.header
    handle = next(value for _, kind, value in H.initialize(app)["frame"]["hits"]
                  if kind == "control" and value["id"].endswith(":drag"))
    assert handle["left"] >= 4
    assert S.handle_mouse(app, y, left + 2, "left")
    rows, _ = draw(tower)
    item = pane(tower, "history-browser:analytics")
    assert item.painted == item.limit
    assert app.analytics_job == selected
    assert H.initialize(app)["frame"]["page"] == item.page
    assert any(H.initialize(app)["items"][-1].record.id in L.row_text(row) for row in rows)
    assert all(L.vlen(L.row_text(row)) <= 160 for row in rows)


@pytest.mark.parametrize("density", ["comfortable", "focused"])
def test_workspace_history_uses_actual_main_page_once(tower, density):
    tower.app.enter_tab("history")
    tower.app.layout_state.density = density
    _, hits = draw(tower)
    item = pane(tower, "history")
    visible = [hit for hit in hits if hit[1] == "fin"]
    assert len(visible) == item.page
    assert not any(p.key == "workspace:history:main" and p.limit
                   for p in S.initialize(tower.app)["panes"])
    assert S.activate(tower.app, "history", "bottom")
    _, hits = draw(tower)
    assert tower.app.history_jobs()[-1].id in {value for _, kind, value in hits if kind == "fin"}


def test_native_advisor_keeps_all_names_and_running_jobs_reachable_without_changing_source(tower, monkeypatch):
    app = tower.app
    app.enter_tab("analytics")
    app.analytics_view = "advisor"
    derived = []
    original = advisor.advise_running
    def advise(job, *args, **kwargs):
        derived.append(job.id)
        return original(job, *args, **kwargs)
    monkeypatch.setattr(advisor, "advise_running", advise)
    draw(tower, 160, 28)
    assert not derived, "Offscreen running advice must not be derived on the first table page"
    key = "analytics:document:advisor"
    selected = app.analytics_job
    item = pane(tower, key)
    assert item.count > 300
    assert S.activate(app, key, "bottom")
    rows, _ = draw(tower, 160, 28)
    assert pane(tower, key).painted == pane(tower, key).limit
    assert app.analytics_job == selected
    assert "job-060" in L.to_text(rows, 160)
    assert "60" in derived and len(derived) <= pane(tower, key).page + 8
    app.move("home")
    draw(tower, 160, 28)
    assert pane(tower, key).painted == 0


def test_workspace_table_layout_probe_does_not_reset_pid_every_frame(tower, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(scrolling.time, "monotonic", lambda: now[0])
    tower.app.interactive = True
    tower.app.cfg.set("animations", True)
    tower.app.cfg.set("smooth_scrolling", True)
    tower.app.scrolling_state = None
    tower.app.enter_tab("history")
    tower.app.layout_state.density = "comfortable"
    draw(tower)
    assert S.activate(tower.app, "history", "bottom")
    draw(tower)
    now[0] += .03
    draw(tower)
    item = pane(tower, "history")
    assert 0 < item.painted < item.target
    now[0] += .3
    draw(tower)
    item = pane(tower, "history")
    assert item.painted == item.target == item.limit


@pytest.mark.parametrize("width", [120, 200])
@pytest.mark.parametrize("density", ["compact", "comfortable"])
def test_inline_metric_curves_do_not_overlap_the_details_scrollbar_gutter(tower, width, density):
    app = tower.app
    app.layout_state.density = density
    app.run_command("jobpanel analytics job")
    tower.store.jobs[0].gpus = 2
    for index in range(20):
        tower.store.record("1", {"k": "live", "t": index, "cpu": index / 20,
                                  "rss": 1024 ** 3, "eff": .5})
        tower.store.record("1", {"k": "gpu", "t": index,
                                  "gpu": {"nodeA:0": [index * 5, 512, 1024]}})
    draw(tower, width, 70)
    item = pane(tower, "workspace:jobs:details")
    plots = [plot for plot in C.initialize(app)["plots"] if plot.kind == "metric"]
    assert plots
    assert all(plot.visible.right <= item.rect.right - 1 for plot in plots)


def test_inline_advisor_keeps_every_retained_running_job_reachable(tower):
    tower.store.finished = tower.store.finished[:20]
    app = tower.app
    app.run_command("jobpanel analytics advisor")
    draw(tower, 200, 50)
    assert S.activate(app, "workspace:jobs:details", "bottom")
    rows, _ = draw(tower, 200, 50)
    assert "60 / job-060" in L.to_text(rows, 200)


def test_primary_log_scrollbar_keeps_range_and_original_prefixes(tower, monkeypatch):
    path = tower.tmp_path / "source.log"
    path.write_text("".join(f"AB source line {index:03}\n" for index in range(300)))
    tower.store.details["1"] = {"StdOut": str(path), "WorkDir": str(tower.tmp_path)}
    app = tower.app
    app.open_log("1")
    draw(tower)
    app.logs.selection_anchor = 280
    app.logs.selection_end = 282
    selected, log_job = (app.logs.selection_anchor, app.logs.selection_end), app.log_job
    with monkeypatch.context() as patch:
        patch.setattr(tower.store, "snapshot", forbidden)
        assert S.activate(app, "logs:document", "top")
    rows, _ = draw(tower)
    assert pane(tower, "logs:document").painted == 0
    assert selected == (app.logs.selection_anchor, app.logs.selection_end)
    assert app.log_job == log_job
    assert "AB source line 000" in L.to_text(rows, 160)


@pytest.mark.parametrize("width,height", [(1, 1), (2, 8), (10, 14), (40, 18), (80, 24), (160, 42)])
def test_scrollbar_staging_never_leaks_geometry_outside_terminal(tower, width, height):
    rows, _ = draw(tower, width, height)
    assert len(rows) == height
    assert all(L.vlen(L.row_text(row)) <= width for row in rows)
    for item in S.initialize(tower.app)["panes"]:
        assert 0 <= item.rect.top < item.rect.bottom <= height - 1
        assert 0 <= item.rect.left < item.rect.right <= width
        if item.header:
            assert 0 <= item.header[0] < height - 1
            assert 0 <= item.header[1] < item.header[2] <= width
