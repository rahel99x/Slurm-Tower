"""Precise menu hits, modal isolation, and live terminal update-slider input."""
from collections import deque
import curses
from types import SimpleNamespace

import pytest

from tower import layout as L, refresh_rate as R, screen, toolbar as T
from tower.config import Config
from tower.controller import App
from tower.model import Job, Store
from tower.views import Views


def instance(**values):
    app = SimpleNamespace(cfg=Config(), mode="main", tab="jobs", quit=False,
                          selected_id="41", marks=set(), sampler=None, research=None,
                          logs=SimpleNamespace(browser=False), commands_seen=[], actions_seen=[],
                          messages=[], failures=[], project_state={}, sel_anchor=None,
                          log_selection_expected=False, **values)
    app.say = app.messages.append
    app.fail = app.failures.append
    app.run_command = app.commands_seen.append
    app.handle_action = app.actions_seen.append
    T.initialize(app)
    return app


def views(ascii_=False):
    return SimpleNamespace(g=L.Glyphs(ascii_))


def target(app, kind, index=0):
    hits = [hit for hit in T.initialize(app)["hits"] if hit[3] == kind]
    return hits[index]


def click(app, hit, button="left"):
    return T.handle_mouse(app, hit[0], hit[1], button=button)


@pytest.mark.parametrize("width", [0, 1, 2, 3, 4, 7, 8, 10, 16, 24, 30, 43, 44, 62, 80, 120, 200])
@pytest.mark.parametrize("rate", [1, 25, 50])
@pytest.mark.parametrize("ascii_", [False, True])
def test_toolbar_fits_every_width_with_nonoverlapping_exact_hits(width, rate, ascii_):
    app = instance()
    R.set_multiplier(app, rate)
    row = T.render_bar(views(ascii_), app, width)
    assert L.vlen(L.row_text(row)) == width
    assert all(0 <= x0 < x1 <= width and y == 0 for y, x0, x1, _, _ in app.toolbar_state["hits"])
    spans = [(x0, x1) for _, x0, x1, _, _ in app.toolbar_state["hits"]]
    assert all(left[1] <= right[0] for left, right in zip(spans, spans[1:]))
    if width >= len(str(rate)) + 2:
        assert str(rate) + "x" in L.row_text(row)
    if width:
        assert target(app, "quit")[1] == 0
    if width >= 8:
        assert any(hit[3] == "menu" for hit in app.toolbar_state["hits"])
    if ascii_:
        assert L.row_text(row).isascii()
    else:
        if any(hit[3] == "track" for hit in app.toolbar_state["hits"]):
            assert "▌" in L.row_text(row)


def test_slider_click_endpoints_and_drag_clamp_without_job_navigation():
    app = instance()
    T.render_bar(views(), app, 120)
    assert click(app, target(app, "track", -1))
    assert R.multiplier(app) == 50 and app.toolbar_state["dragging"]
    assert T.handle_mouse(app, 9, -100, button="motion")
    assert R.multiplier(app) == 1
    assert T.handle_mouse(app, 4, 900, button="drag")
    assert R.multiplier(app) == 50
    assert T.handle_mouse(app, 4, 900, button="release")
    assert not app.toolbar_state["dragging"]
    assert not T.handle_mouse(app, 0, 0, button="motion")
    assert not app.commands_seen and not app.actions_seen


def test_slider_arrows_home_end_wheel_and_return_to_underlying_modal():
    app = instance()
    app.mode = "help"
    T.render_bar(views(), app, 80)
    assert click(app, target(app, "rate"))
    assert T.handle_key(app, "end") and R.multiplier(app) == 50
    assert T.handle_key(app, "right") and R.multiplier(app) == 50
    assert T.handle_key(app, "left") and R.multiplier(app) == 49
    assert click(app, target(app, "rate"), "wheel-down") and R.multiplier(app) == 48
    assert click(app, target(app, "rate"), "wheel-up") and R.multiplier(app) == 49
    assert T.handle_key(app, "home") and R.multiplier(app) == 1
    assert T.handle_key(app, "down") and R.multiplier(app) == 1
    assert T.handle_key(app, "esc")
    assert app.mode == "help" and not app.toolbar_state["focus"]
    assert not T.handle_key(app, "down")


def test_mouse_minus_plus_and_partial_bar_value_remain_keyboard_operable():
    app = instance()
    T.render_bar(views(), app, 80)
    click(app, target(app, "plus"))
    assert R.multiplier(app) == 2
    click(app, target(app, "minus"))
    assert R.multiplier(app) == 1
    T.render_bar(views(True), app, 8)
    assert click(app, target(app, "rate"))
    assert T.handle_key(app, "end") and R.multiplier(app) == 50
    T.render_bar(views(True), app, 8)
    assert "50x" in L.row_text(T.render_bar(views(True), app, 8))
    assert T.handle_key(app, "tab") and not app.toolbar_state["focus"]


@pytest.mark.parametrize("mode", ["main", "help", "details", "palette", "confirm", "terminal_probe"])
def test_keyboard_menu_browsing_retains_every_underlying_mode_and_does_nothing(mode):
    app = instance()
    app.mode = mode
    assert T.handle_key(app, "f10")
    assert app.toolbar_state["menu"] == 0
    for key in ("down", "down", "right", "down", "left", "home", "end"):
        assert T.handle_key(app, key)
    assert app.mode == mode and not app.commands_seen and not app.actions_seen and not app.quit
    assert T.handle_key(app, "esc")
    assert app.mode == mode and app.toolbar_state["menu"] is None
    assert not T.handle_key(app, "down")


@pytest.mark.parametrize("ascii_", [False, True])
@pytest.mark.parametrize("width,height", [(0, 0), (1, 1), (1, 2), (3, 3), (8, 4), (24, 5), (40, 8), (80, 16), (160, 40)])
@pytest.mark.parametrize("menu", range(4))
def test_dropdowns_reserve_toolbar_fit_screen_and_scroll_to_last_item(width, height, ascii_, menu):
    app = instance()
    T.render_bar(views(ascii_), app, width)
    T._open(app, menu)
    T.handle_key(app, "end")
    rows = T.overlay(views(ascii_), {}, app, width, height)
    assert all(1 <= y < height and 0 <= x < width and x + L.vlen(L.row_text(row)) <= width for y, x, row in rows)
    assert all(1 <= y < height and 0 <= left < right <= width for y, left, right, _ in app.toolbar_state["menu_hits"])
    last = T.menu_items(app, menu)[-1]
    if width >= 24 and height >= 4:
        assert any(hit[-1] == last.key for hit in app.toolbar_state["menu_hits"])
    if ascii_:
        assert all(L.row_text(row).isascii() for _, _, row in rows)


def test_mouse_menu_uses_actual_item_and_clears_old_targets_after_change():
    app = instance()
    T.render_bar(views(), app, 120)
    assert click(app, target(app, "menu", 0))
    T.overlay(views(), {}, app, 120, 30)
    first = app.toolbar_state["menu_hits"][0]
    assert first[-1] == "project"
    # Switch menu before the next paint. The old File menu has no live targets.
    assert T.handle_key(app, "right")
    assert not app.toolbar_state["menu_hits"]
    assert T.handle_mouse(app, first[0], first[1])
    assert app.toolbar_state["menu"] is None
    assert not app.commands_seen and not app.actions_seen


def test_mouse_context_change_does_not_execute_stale_dropdown_target():
    app = instance()
    T.render_bar(views(), app, 120)
    T._open(app, 0)
    T.overlay(views(), {}, app, 120, 30)
    hit = app.toolbar_state["menu_hits"][7]
    app.tab = "history"
    assert T.handle_mouse(app, hit[0], hit[1])
    assert not app.commands_seen
    assert app.toolbar_state["menu"] is None


def test_click_outside_menu_only_dismisses_and_never_selects_hidden_job():
    app = instance()
    T.render_bar(views(), app, 120)
    T._open(app, 0)
    T.overlay(views(), {}, app, 120, 30)
    assert T.handle_mouse(app, 28, 119)
    assert app.toolbar_state["menu"] is None
    assert not app.commands_seen and app.selected_id == "41"
    assert not T.handle_mouse(app, 28, 119)


def test_pending_scheduler_and_workflow_reviews_cannot_be_discarded_by_menu_commands():
    app = instance()
    for mode, state in [("confirm", {}), ("execution", {"pending_action": "execute"})]:
        app.mode, app.execution_state = mode, state
        T._open(app, 2)
        T._activate(app, T.menu_items(app, "View")[0])
        assert app.mode == mode and not app.commands_seen
        assert app.toolbar_state["menu"] == 2
        assert "pending job review" in app.messages[-1]
        T._activate(app, T.menu_items(app, "Help")[-1])
        assert app.mode == mode and app.toolbar_state["panel"] == "about"
        T.handle_key(app, "esc")
        assert app.mode == mode


def test_context_entries_remain_visible_but_block_unavailable_operations():
    app = instance()
    app.selected_id = None
    for menu, key, notice in [("File", "runs", "project"), ("File", "outputs", "run"),
                              ("Edit", "pin", "job"), ("Edit", "bookmark", "log")]:
        T._open(app, T.MENUS.index(menu))
        item = next(item for item in T.menu_items(app, menu) if item.key == key)
        T._activate(app, item)
        assert notice in app.messages[-1].lower()
        assert app.toolbar_state["menu"] is not None
    app.tab = "research"
    T._activate(app, next(item for item in T.menu_items(app, "Edit") if item.key == "columns"))
    assert "Jobs or History" in app.messages[-1]
    assert not app.commands_seen


def test_toolbar_quit_is_one_explicit_click_even_when_filter_or_confirmation_open():
    app = instance()
    app.mode, app.filter = "confirm", "filtered"
    T.render_bar(views(), app, 80)
    assert click(app, target(app, "quit"))
    assert app.quit and app.mode == "confirm" and app.filter == "filtered"


def test_all_menu_commands_resolve_to_real_capabilities_with_no_scheduler_mutations():
    app = App(Store(persist=False), None, None, Config(), "tester")
    commands = app.commands()
    for menu in T.MENUS:
        entries = T.menu_items(app, menu)
        assert len({item.key for item in entries}) == len(entries)
        for item in entries:
            if item.command:
                assert item.command.split()[0] in commands
                assert item.command.split()[0] not in ("submit", "cancel", "hold", "release", "requeue", "top", "resubmit", "orchestrate")


def test_parameterized_project_action_opens_editable_prompt_and_never_executes():
    app = App(Store(persist=False), None, None, Config(), "tester")
    app.mode = "help"
    T._activate(app, T.menu_items(app, "File")[0])
    assert app.mode == "palette" and app.palette_edit == "project "
    assert app.command_state["origin_mode"] == "help"
    assert not app.project_state["root"]
    assert not app.research


def test_tab_activation_dismisses_old_modal_and_research_uses_existing_workspace():
    app = App(Store(persist=False), None, None, Config(), "tester")
    app.mode = "help"
    item = next(item for item in T.menu_items(app, "View") if item.key == "tab-sources")
    T._activate(app, item)
    assert app.tab == "sources" and app.mode == "main"
    item = next(item for item in T.menu_items(app, "View") if item.key == "research-artifacts")
    T._activate(app, item)
    assert app.tab == "research" and app.research_view == "artifacts"


def test_real_visual_selection_and_rate_only_change_local_state(tmp_path):
    app = App(Store(persist=False), None, None, Config(), "tester")
    painter = Views(L.Glyphs(False), app.cfg)
    app.views_ref = painter
    app.store.apply_jobs([Job("41", "cpu-run", "cpu", "RUNNING")])
    painter.compose(app.store.snapshot(), app, 120, 30)
    app.mode = "help"
    T._activate(app, next(item for item in T.menu_items(app, "Edit") if item.key == "select"))
    assert app.mode == "main" and app.sel_anchor is not None
    T._activate(app, next(item for item in T.menu_items(app, "View") if item.key == "rate"))
    assert app.toolbar_state["focus"] == "rate"
    T.handle_key(app, "end")
    assert R.multiplier(app) == 50 and app.selected_id == "41"


def test_about_is_bounded_and_reserves_top_row_without_changing_underlying_dialog():
    app = instance()
    app.mode = "confirm"
    T.run_command(app, ["about"])
    for width, height in [(0, 0), (1, 1), (1, 2), (20, 5), (80, 20)]:
        rows = T.overlay(views(True), {}, app, width, height)
        assert all(1 <= y < height and x + L.vlen(L.row_text(row)) <= width for y, x, row in rows)
        assert all(L.row_text(row).isascii() for _, _, row in rows)
    assert app.mode == "confirm"
    assert T.handle_key(app, "end")
    rows = T.overlay(views(True), {}, app, 80, 8)
    assert "previous screen" in "\n".join(L.row_text(row) for _, _, row in rows)
    assert T.handle_key(app, "esc") and app.mode == "confirm"


@pytest.fixture
def terminal_dashboard():
    cfg = Config({"animations": False, "gpu_sampling": False, "log_lines": 0})
    store = Store(persist=False)
    store.apply_jobs([Job(str(index + 1), "cpu-run-" + str(index), "cpu", "RUNNING") for index in range(30)])
    app = App(store, None, None, cfg, "toolbar-tester")
    painter = Views(L.Glyphs(False), cfg)
    app.views_ref = painter
    painter.compose(store.snapshot(), app, 120, 30)
    return app, painter, store


def dispatch_mouse(app, x, y, buttons):
    screen._apply_input(app, ("mouse", (0, x, y, 0, buttons)), app.last_hits, curses)


@pytest.mark.parametrize("mode", ["analysis", "columns", "field_explanation", "log_tools_page"])
def test_global_menu_has_priority_over_underlying_palette_context(terminal_dashboard, mode):
    app, _, _ = terminal_dashboard
    app.mode = mode
    previous_command_input = app.palette_edit
    screen._apply_input(app, ("f10", None), app.last_hits, curses)
    assert app.toolbar_state["menu"] == 0 and app.mode == mode
    screen._apply_input(app, (":", None), app.last_hits, curses)
    assert app.mode == mode and app.palette_edit == previous_command_input
    assert app.toolbar_state["menu"] == 0
    screen._apply_input(app, ("esc", None), app.last_hits, curses)
    assert app.mode == mode and app.toolbar_state["menu"] is None
    # Only after the toolbar closes does ':' reach that dialog's command input.
    screen._apply_input(app, (":", None), app.last_hits, curses)
    assert app.mode == "palette"


def test_dispatcher_slider_wheel_changes_rate_without_scrolling_jobs(terminal_dashboard):
    app, painter, store = terminal_dashboard
    app.cursor["jobs"] = 10
    painter.compose(store.snapshot(), app, 120, 30)
    selected = app.selected_id
    rate = target(app, "rate")
    dispatch_mouse(app, rate[1], rate[0], curses.BUTTON4_PRESSED)
    assert R.multiplier(app) == 2
    assert app.cursor["jobs"] == 10 and app.selected_id == selected
    dispatch_mouse(app, rate[1], rate[0], curses.BUTTON5_PRESSED)
    assert R.multiplier(app) == 1
    assert app.cursor["jobs"] == 10 and app.selected_id == selected
    assert app.toolbar_state["focus"] == "rate"
    # Moving the wheel back into the table releases slider focus and restores
    # normal table navigation; the one event reaches exactly one controller.
    job_row = next(y for y, kind, _ in app.last_hits if kind == "job")
    dispatch_mouse(app, 5, job_row, curses.BUTTON5_PRESSED)
    assert app.cursor["jobs"] == 11 and R.multiplier(app) == 1
    assert app.toolbar_state["focus"] == ""


def test_dispatcher_drags_and_releases_slider_without_job_selection(terminal_dashboard):
    app, _, _ = terminal_dashboard
    first, last = target(app, "track"), target(app, "track", -1)
    selected, cursor = app.selected_id, app.cursor["jobs"]
    dispatch_mouse(app, last[1], 0, curses.BUTTON1_PRESSED)
    assert app.toolbar_state["dragging"] and R.multiplier(app) == 50
    dispatch_mouse(app, first[1], 0, curses.REPORT_MOUSE_POSITION)
    assert R.multiplier(app) == 1
    dispatch_mouse(app, first[1], 0, curses.BUTTON1_RELEASED)
    assert not app.toolbar_state["dragging"]
    dispatch_mouse(app, last[1], 0, curses.REPORT_MOUSE_POSITION)
    assert R.multiplier(app) == 1
    assert app.selected_id == selected and app.cursor["jobs"] == cursor
    assert app.mode == "main" and not app.logs.selection_active


@pytest.mark.parametrize("mode", ["confirm", "terminal_probe"])
def test_dispatcher_quit_button_remains_available_over_reviews_and_input_probe(terminal_dashboard, mode):
    app, _, _ = terminal_dashboard
    app.mode = mode
    app.confirm = {"action": "cancel", "jobs": app.store.jobs[:1]}
    review = app.confirm.copy()
    probe_events = list(app.session_tools_state["probe_events"])
    quit_button = target(app, "quit")
    dispatch_mouse(app, quit_button[1], quit_button[0], curses.BUTTON1_PRESSED)
    assert app.quit and app.mode == mode and app.confirm == review
    assert app.session_tools_state["probe_events"] == probe_events


def test_dispatcher_rejects_stale_menu_target_after_underlying_tab_changes(terminal_dashboard):
    app, painter, store = terminal_dashboard
    screen._apply_input(app, ("f10", None), app.last_hits, curses)
    painter.overlay(store.snapshot(), app, 120, 30)
    project = next(hit for hit in app.toolbar_state["menu_hits"] if hit[-1] == "project")
    app.enter_tab("history")
    dispatch_mouse(app, project[1], project[0], curses.BUTTON1_PRESSED)
    assert app.toolbar_state["menu"] is None and app.tab == "history"
    assert app.mode == "main" and not app.palette_edit
    assert not app.project_state["root"] and not app.research


def test_queued_menu_navigation_repaints_before_next_move_and_activation(terminal_dashboard, monkeypatch):
    app, painter, store = terminal_dashboard
    monkeypatch.setattr(screen.time, "monotonic", lambda: 0)
    app.run_command("menu View")
    painter.overlay(store.snapshot(), app, 120, 12)

    class QueuedWindow:
        def __init__(self):
            self.values = deque([curses.KEY_DOWN, "\n"])

        def timeout(self, value):
            pass

        def get_wch(self):
            if not self.values:
                raise curses.error("empty event queue")
            return self.values.popleft()

    window = QueuedWindow()
    assert screen._consume_input_batch(app, window, curses, app.last_hits, ("down", None)) is None
    assert app.toolbar_state["cursor"] == 1 and app.tab == "jobs"
    assert list(window.values) == [curses.KEY_DOWN, "\n"]
    painter.overlay(store.snapshot(), app, 120, 12)
    # The next event is applied to the newly drawn menu. It must leave Enter
    # queued, because that Enter opens History, rather than stale Cluster.
    event = screen._read_input(window, curses)
    assert event == ("down", None)
    assert screen._consume_input_batch(app, window, curses, app.last_hits, event) is None
    assert app.toolbar_state["cursor"] == 2 and app.tab == "jobs"
    assert list(window.values) == ["\n"]
    painter.overlay(store.snapshot(), app, 120, 12)
    event = screen._read_input(window, curses)
    assert event == ("enter", None)
    screen._consume_input_batch(app, window, curses, app.last_hits, event)
    assert app.tab == "history" and app.toolbar_state["menu"] is None
    assert not window.values and not app.marks


def test_every_width_retains_rate_value_across_responsive_layout_thresholds():
    app = instance()
    for rate in (1, 25, 50):
        R.set_multiplier(app, rate)
        for width in range(0, 201):
            row = T.render_bar(views(True), app, width)
            text = L.row_text(row)
            assert L.vlen(text) == width
            if width >= len(str(rate)) + 2:
                assert str(rate) + "x" in text, (width, rate, text)


def test_actual_curses_paint_keeps_global_bar_visible_above_tiny_confirmation(terminal_dashboard, monkeypatch):
    app, painter, store = terminal_dashboard
    app.mode = "confirm"
    app.confirm = {"action": "cancel", "jobs": store.jobs[:1]}
    for name in ("curs_set", "mousemask", "mouseinterval", "doupdate", "set_escdelay"):
        monkeypatch.setattr(curses, name, lambda *args: None)
    monkeypatch.setattr(curses, "has_colors", lambda: False)

    class PaintedWindow:
        def __init__(self):
            self.values = deque(["\x03"])
            self.rows = []
            self.paint_order = []

        def getmaxyx(self):
            return 2, 40

        def timeout(self, value):
            pass

        def keypad(self, enabled):
            pass

        def erase(self):
            self.rows = [[" "] * 40 for _ in range(2)]

        def addstr(self, y, x, text, attribute):
            self.paint_order.append((y, x, text))
            for character in text:
                cells = L.vlen(character)
                if cells and 0 <= y < 2 and 0 <= x < 40:
                    self.rows[y][x] = character
                x += cells

        def noutrefresh(self):
            pass

        def get_wch(self):
            if not self.values:
                raise curses.error("empty input")
            return self.values.popleft()

    window = PaintedWindow()
    monkeypatch.setattr(curses, "wrapper", lambda callback: callback(window))
    screen.run_curses(app, painter, None, store, None, app.cfg)
    assert app.quit and not window.values
    # The confirmation painter runs after the body, including on row zero in
    # a two-row terminal. The renderer must repaint the actual global controls
    # last; this verifies the final cells, rather than only renderer call order.
    top = "".join(window.rows[0])
    assert "File" in top and "Edit" in top and "1x" in top
    assert top.lstrip().startswith("x")
    assert not app.command_state["confirm_controls_visible"]
