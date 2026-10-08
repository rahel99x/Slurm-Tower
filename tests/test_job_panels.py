"""Exact-job Details tabs stay live, bounded and independent from full Logs."""
from __future__ import annotations

import copy
import json
from threading import Event, current_thread
from types import SimpleNamespace

import pytest

from tower import job_panels as J, layout as L, workspace_layout as W
from tower.config import Config
from tower.controller import App
from tower.model import Finished, Job, Live, Step, Store
from tower.remote import LocalFiles
from tower.research import ResearchHub
from tower.views import Views


@pytest.fixture
def dashboard(tmp_path):
    cfg = Config()
    cfg.set("workspace", {"density": "compact", "split": 50})
    cfg.set("log_lines", 0)
    store = Store(persist=False)
    store.jobs = [Job("900", "active-only", "cpu", "RUNNING", cpus=4, mem_req="4G")]
    store.finished = [Finished("700", "failed-only", "FAILED", cpus=2, exit="1:0", elapsed="00:00:20")]
    store.live["900"] = Live(rss=1024 ** 3, rate=.5)
    paths = {}
    for job in store.jobs + store.finished:
        root = tmp_path / job.id
        root.mkdir()
        out, err, extra = root / "stdout.log", root / "stderr.log", root / "application.log"
        out.write_text(f"AB_OUTPUT_{job.id}\n")
        err.write_text(f"CD_ERROR_{job.id}: RuntimeError failed\n")
        extra.write_text(f"EXTRA_{job.id}\n")
        manifest = root / "logs.json"
        manifest.write_text(json.dumps({"schema": "tower.logs/v1", "job_id": job.id,
            "logs": [{"id": "app", "path": "application.log", "label": "Application"}]}))
        store.details[job.id] = {"StdOut": str(out), "StdErr": str(err), "WorkDir": str(root)}
        paths[job.id] = (out, err, extra)
    cfg.set("logs", {"manifest_file": "logs.json"})
    app = App(store, None, None, cfg, "test", interactive=False)
    views = Views(L.Glyphs(False), cfg, files=LocalFiles())
    app.views_ref, app.logs.files = views, views.files
    result = SimpleNamespace(app=app, views=views, store=store, paths=paths)
    def render(width=160, height=32):
        rows, hits = views.compose(store.snapshot(), app, width, height)
        return L.to_text(rows, width), rows, hits
    result.render = render
    yield result
    if app.research:
        app.research.close()


def button(hits, name):
    return next((y, value) for y, kind, value in hits if kind == "job_panel_tab" and value[0] == name)


def test_default_compact_jobs_uses_second_column_and_exact_bounded_buttons(dashboard):
    text, _, hits = dashboard.render()
    assert "Main" in text and "Details" in text
    assert "Allocation  4 CPUs" in text
    assert "Overview" in text and "Resources" in text
    rect = dashboard.app.job_panel_rect
    assert rect.x > 0
    for name in J.MODES:
        y, (_, left, right) = button(hits, name)
        assert rect.x <= left < right <= rect.x + rect.width
        assert rect.y <= y < rect.y + rect.height
    jobs = [(y, value) for y, kind, value in hits if kind == "job"]
    assert jobs and jobs[0][1] == "900"


def test_clicked_tab_arrow_cycle_keeps_job_and_esc_returns_to_rows(dashboard):
    app = dashboard.app
    _, _, hits = dashboard.render()
    y, (_, left, _) = button(hits, "logs")
    before = copy.deepcopy(app.cursor)
    assert J.handle_mouse(app, y, left)
    assert J.initialize(app)["mode"] == "logs"
    assert J.handle_key(app, "right")
    assert J.initialize(app)["mode"] == "investigate"
    assert J.handle_key(app, "down")
    assert J.initialize(app)["mode"] == "off"
    assert J.handle_key(app, "left")
    assert J.initialize(app)["mode"] == "investigate"
    assert app.cursor == before and app.tab == "jobs" and app.mode == "main"
    assert J.handle_key(app, "esc")
    assert not J.handle_key(app, "down")
    assert app.layout_state.focus == "main"


def test_off_shows_buttons_without_content_or_file_worker_io(dashboard, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Off started a reader")
    monkeypatch.setattr(J, "_worker", forbidden)
    monkeypatch.setattr(dashboard.views.files, "stat", forbidden)
    monkeypatch.setattr(dashboard.views.files, "tail", forbidden)
    assert J.run_command(dashboard.app, ["jobpanel", "off"])
    text, rows, hits = dashboard.render()
    assert all(button(hits, name) for name in J.MODES)
    right = dashboard.app.job_panel_rect
    panel = "\n".join(L.row_text(row)[right.x:] for row in rows[right.y:right.y + right.height])
    assert "Allocation" not in panel and "active-only" not in panel
    assert "Logs" in panel and "Off" in panel
    assert dashboard.app.research is None


def test_live_and_recent_selection_update_without_changing_details_mode(dashboard):
    app, store = dashboard.app, dashboard.store
    J.run_command(app, ["jobpanel", "inspector"])
    text, _, _ = dashboard.render()
    assert "Job 900" in text
    app.cursor["jobs"] = 1
    text, _, _ = dashboard.render()
    assert app.selected_id == "700" and "Job 700" in text
    assert J.initialize(app)["mode"] == "inspector"
    assert "Exit" in text and "1:0" in text
    # Existing identity remains selected when a new active job arrives.
    store.jobs.insert(0, Job("901", "new-job", "cpu", "PENDING"))
    text, _, _ = dashboard.render()
    assert app.selected_id == "700" and "Job 700" in text
    assert app.tab == "jobs" and app.mode == "main"


def test_inspector_does_not_change_full_modal_or_log_selections(dashboard):
    app = dashboard.app
    app.analysis_state.update(job="other", section=3, modal="inspect", scroll=17)
    app.log_job = "other"
    app.logs.path, app.logs.top = "/other/log", 13
    before = copy.deepcopy(app.analysis_state)
    dashboard.render()
    assert app.analysis_state == before
    assert (app.log_job, app.logs.path, app.logs.top) == ("other", "/other/log", 13)


def test_inspector_retains_live_rank_diagnostics_dependencies_tags_and_notes(dashboard):
    store = dashboard.store
    store.tags["900"] = {"tags": ["urgent", "paper"], "note": "rerun with 32 cores"}
    store.jobs.append(Job("901", "follow-up", "cpu", "PENDING", dependency="afterok:900"))
    store.steps["900"] = [Step("900.0", name="0", ntasks=8, cpu_time=3000,
        rss=2 * 1024 ** 3, rss_task="3", rss_node="node-b", min_cpu=1200,
        min_cpu_task="3", min_cpu_node="node-b")]
    text, _, _ = dashboard.render(width=150, height=60)
    assert "step 0        8 tasks" in text
    assert "peak 2.0 GB on task 3@node-b" in text
    assert "slowest rank 3@node-b at 40% of the mean" in text
    assert "1 job wait for this one: 901(follow-up)" in text
    assert "tags #urgent #paper" in text and "Tags urgent paper" in text
    assert "rerun with 32 cores" in text


def test_inline_logs_exact_recent_sources_preserve_first_chars_and_full_log_state(dashboard):
    app = dashboard.app
    app.cursor["jobs"] = 1
    app.log_job = "900"
    app.logs.path, app.logs.top, app.logs.search = str(dashboard.paths["900"][0]), 13, "old search"
    original = (app.log_job, app.logs.path, app.logs.top, app.logs.search)
    J.run_command(app, ["jobpanel", "logs"])
    text, _, hits = dashboard.render()
    assert "AB_OUTPUT_700" in text and "AB_OUTPUT_900" not in text
    state = J.initialize(app)
    assert len(state["entries"]) == 3
    file_hit = next((y, value) for y, kind, value in hits if kind == "job_panel_file" and value[0] == "scheduler.stderr")
    assert J.handle_mouse(app, file_hit[0], file_hit[1][1])
    text, _, _ = dashboard.render()
    assert "CD_ERROR_700" in text and "AB_OUTPUT_700" not in text
    assert J.handle_key(app, "right")
    text, _, _ = dashboard.render()
    assert "EXTRA_700" in text
    assert (app.log_job, app.logs.path, app.logs.top, app.logs.search) == original
    assert app.tab == "jobs" and app.mode == "main"
    assert state["session"].max_bytes == J.MAX_LOG_BYTES


def test_log_content_scroll_and_end_follow_do_not_move_job_cursor(dashboard):
    out = dashboard.paths["900"][0]
    out.write_text("".join(f"LINE_{i:04}\n" for i in range(100)))
    J.run_command(dashboard.app, ["jobpanel", "logs"])
    dashboard.render()
    state = J.initialize(dashboard.app)
    assert J.handle_key(dashboard.app, "enter")
    assert J.handle_key(dashboard.app, "home")
    text, _, _ = dashboard.render()
    assert "LINE_0000" in text
    assert dashboard.app.cursor["jobs"] == 0
    assert J.handle_key(dashboard.app, "end")
    text, _, _ = dashboard.render()
    assert "LINE_0099" in text and state["session"].top is None
    with out.open("a") as output:
        output.write("LINE_NEW\n")
    text, _, _ = dashboard.render()
    assert "LINE_NEW" in text


def test_investigate_uses_selected_recent_job_and_leaves_research_selection(dashboard):
    app = dashboard.app
    app.cursor["jobs"] = 1
    app.research_job_id, app.research_view = "900", "experiment"
    J.run_command(app, ["jobpanel", "investigate"])
    text, _, _ = dashboard.render()
    assert "Job 700" in text and "CD_ERROR_700" in text
    state = J.initialize(app)
    assert state["evidence_job"] == "700" and state["evidence"]
    assert app.research_job_id == "900" and app.research_view == "experiment"
    assert app.tab == "jobs" and app.mode == "main"


def test_shared_filesystem_logs_do_not_block_frame_or_start_parallel_workers(dashboard):
    entered, release = Event(), Event()
    class SlowFiles(LocalFiles):
        def listdir(self, path):
            assert current_thread().name.startswith("tower-research")
            entered.set()
            assert release.wait(3)
            return super().listdir(path)
        def stat(self, path):
            assert current_thread().name.startswith("tower-research")
            return super().stat(path)
        def read(self, path, offset, length):
            assert current_thread().name.startswith("tower-research")
            return super().read(path, offset, length)
    app, files = dashboard.app, SlowFiles()
    app.interactive = True
    dashboard.views.files = files
    app.logs.files = files
    app.research = ResearchHub(app.cfg, files)
    J.run_command(app, ["jobpanel", "logs"])
    try:
        text, _, _ = dashboard.render()
        assert "Waiting" in text and entered.wait(1)
        future = app.research.future
        for _ in range(20):
            dashboard.render()
            assert app.research.future is future
        release.set()
        future.result(timeout=3)
        app.research.poll_task()
        dashboard.render()
        app.research.future.result(timeout=3)
        app.research.poll_task()
        text, _, _ = dashboard.render()
        assert "AB_OUTPUT_900" in text
    finally:
        release.set()


def test_details_background_click_does_not_select_same_y_left_job(dashboard):
    _, _, hits = dashboard.render()
    y = next(y for y, kind, _ in hits if kind == "job")
    rect = dashboard.app.job_panel_rect
    assert J.contains(dashboard.app, y, rect.x + rect.width - 1)
    before = dashboard.app.selected_id
    assert J.handle_mouse(dashboard.app, y, rect.x + rect.width - 1)
    assert dashboard.app.selected_id == before


def test_real_app_routes_fresh_mouse_hits_and_arrows_to_details_buttons(dashboard):
    app = dashboard.app
    _, _, hits = dashboard.render()
    y, (_, left, _) = button(hits, "logs")
    app.last_hits = []  # The actual click receives the current renderer map.
    app.click(y, left, hits)
    assert J.initialize(app)["mode"] == "logs"
    assert app.layout_state.focus == "details"
    app.handle("right")
    assert J.initialize(app)["mode"] == "investigate"
    app.handle("end")
    assert J.initialize(app)["mode"] == "off"
    app.handle("esc")
    app.handle("down")
    dashboard.render()
    assert app.selected_id == "700" and app.tab == "jobs"


def test_requested_rate_reaches_independent_log_readers_without_changing_base(dashboard):
    from tower.refresh_rate import set_multiplier
    app = dashboard.app
    set_multiplier(app, 50)
    J.run_command(app, ["jobpanel", "logs"])
    dashboard.render()
    state = J.initialize(app)
    assert state["session"].polling_multiplier == 50
    assert state["catalog"].polling_multiplier == 50
    assert state["catalog"].ttl == 5
    set_multiplier(app, 1)
    dashboard.render()
    assert state["session"].polling_multiplier == state["catalog"].polling_multiplier == 1
    assert state["catalog"].ttl == 5


@pytest.mark.parametrize("width,height,ascii_", [(40, 22, True), (80, 22, False), (110, 28, False),
                                                 (160, 32, False), (1, 1, True), (0, 0, True)])
def test_resize_ascii_and_focus_keep_rows_and_hits_bounded(dashboard, width, height, ascii_):
    dashboard.views.set_ascii(ascii_)
    if ascii_:
        dashboard.app.set_theme("reader")
    text, rows, hits = dashboard.render(width, height)
    assert len(rows) <= height
    assert all(L.vlen(L.row_text(row)) <= width for row in rows)
    assert all(0 <= y < height for y, _, _ in hits)
    for _, kind, value in hits:
        if kind in ("job_panel_tab", "job_panel_file"):
            assert 0 <= value[1] < value[2] <= width
    if ascii_:
        assert text.isascii()
    if width >= 40 and height >= 22:
        assert all(button(hits, name) for name in J.MODES)
    if width:
        W.initialize(dashboard.app).focus = "details"
        W.initialize(dashboard.app).maximized = True
        text, _, hits = dashboard.render(width, height)
        assert all(kind != "job" for _, kind, _ in hits)


def test_restore_accepts_only_known_mode_and_does_not_restore_live_state():
    app = SimpleNamespace()
    J.restore(app, {"mode": "logs", "job": "old", "focus": "tabs", "file_id": "old-file"})
    assert J.save(app) == {"mode": "logs"}
    assert J.initialize(app)["job"] is None and J.initialize(app)["focus"] == ""
    J.restore(app, {"mode": "../bad"})
    assert J.save(app) == {"mode": "logs"}


def test_tick_requests_finished_details_for_recent_selection_and_off_does_not(dashboard):
    selected = []
    dashboard.app.sampler = SimpleNamespace(select_fin=selected.append, select=lambda jid: None,
                                           select_trace=lambda jid: None)
    dashboard.app.selected_id = "700"
    dashboard.app.tick()
    assert selected == ["700"]
    J.initialize(dashboard.app)["mode"] = "off"
    dashboard.app.tick()
    assert selected == ["700", None]
