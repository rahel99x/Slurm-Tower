"""Rendered document selections are pane-local, bounded and source-aware."""
from types import SimpleNamespace
import time

import pytest

from tower import clipboard, interaction, layout as L, scrollbars as S, text_selection as T


def instance(**kw):
    data = dict(cfg={"clipboard": {}}, mode="main", tab="analytics", analytics_view="advisor",
                width=40, height=15, body_origin=2, selected_id=None, job_panel_state={},
                project_state={}, toolbar_state={}, keymap={}, sel_anchor=None, last_hits=[],
                messages=[], failures=[], state_dir=None, cursor={}, interaction_state={})
    data.update(kw)
    app = SimpleNamespace(**data)
    app.say = app.messages.append
    app.fail = app.failures.append
    return app


def paint(app, lines, *, top=0, count=None, context="source", rect=(3, 0, 8, 30), key="advisor", setter=None):
    rows = [[("", "")] for _ in range(app.height)]
    for y, text in zip(range(rect[0], rect[2]), lines):
        rows[y] = [(text, "text")]
    S.begin_frame(app)
    S.register(app, key, rect, len(lines) if count is None else count, rect[2] - rect[0],
               top, top, setter or (lambda value: None), context=context)
    S.publish(app, app.width, app.height)
    T.publish(app, rows, app.width, app.height)
    return rows


def test_advisor_drag_copies_multiple_lines_without_job_or_source_action(monkeypatch):
    app = instance()
    paint(app, ["  memory peak 8 G", "  CPU efficiency 45%", "  recommended CPUs 4"], count=10)
    seen = []
    monkeypatch.setattr(clipboard, "copy", lambda text, *a, **kw: seen.append((text, kw)) or "copied")
    assert T.handle_mouse(app, 3, 5, button="press")
    assert T.active(app)
    assert T.handle_mouse(app, 5, 5, button="drag")
    assert T.handle_mouse(app, 5, 5, button="release")
    assert not T.active(app)
    assert T.copy_selection(app)
    assert seen == [("  memory peak 8 G\n  CPU efficiency 45%\n  recommended CPUs 4\n",
                     dict(use_osc52=True, use_tools=True, destination="copy"))]
    assert not T.selected(app)


def test_keyboard_v_arrow_selection_uses_cursor_row_without_mouse(monkeypatch):
    app = instance()
    app.cursor_row = lambda: 4
    paint(app, ["first", "second", "third", "fourth", "fifth"], count=10)
    assert T.handle_key(app, "v")
    assert T.handle_key(app, "down")
    assert T.handle_key(app, "down")
    assert T.selection_text(app) == "second\nthird\nfourth\n"


def test_plain_arrows_do_not_capture_job_navigation():
    app = instance(tab="jobs")
    paint(app, ["41 running", "42 waiting"], count=10)
    for key in ("up", "down", "pgup", "pgdn", "home", "end"):
        assert not T.handle_key(app, key)


@pytest.mark.parametrize("kind", sorted(T.PROTECTED_KINDS))
def test_job_and_original_log_row_drag_owners_have_priority_until_v(kind):
    app = instance(tab="jobs", last_hits=[(3, kind, "41")])
    paint(app, ["41 running", "42 waiting"], count=10)
    assert not T.handle_mouse(app, 3, 3, button="press")
    assert T.handle_key(app, "v")
    assert T.handle_mouse(app, 3, 3, button="press")
    assert T.active(app)


def test_original_logs_keep_their_exact_byte_visual_selection():
    app = instance(tab="log", logs=SimpleNamespace(browser=False))
    paint(app, ["rendered log"], count=10)
    assert not T.handle_key(app, "v")
    assert not T.handle_key(app, "V")
    assert not T.handle_mouse(app, 3, 1, button="press")


def test_explicit_pane_selection_does_not_cover_other_column():
    app = instance()
    paint(app, ["Main text  Details text", "Main two   Details two"], count=10, rect=(3, 11, 8, 30))
    app.interaction_state["pointer"] = (3, 12)
    assert T.handle_key(app, "v")
    assert T.handle_key(app, "down")
    assert T.selection_text(app) == "Details text\nDetails two\n"
    overlays = T.feedback(app)
    assert all(x == 11 and L.vlen(L.row_text(row)) == 18 for y, x, row in overlays)


def test_cross_page_keyboard_selection_scrolls_published_source_only():
    app = instance()
    offsets = []
    paint(app, [f"line {i}" for i in range(5)], count=20, setter=offsets.append)
    assert T.handle_key(app, "v")
    for _ in range(5):
        assert T.handle_key(app, "down")
    assert offsets == [1]
    assert T.initialize(app)["frame_required"]
    assert S.manual(app, "advisor", context="source") == 1
    # The unseen row is never fabricated or copied as a truncated range.
    assert T.selection_text(app) is None
    paint(app, [f"line {i}" for i in range(1, 6)], top=1, count=20, setter=offsets.append)
    assert T.selection_text(app) == "\n".join(f"line {i}" for i in range(6)) + "\n"


def test_source_updates_cannot_replace_already_selected_text():
    app = instance()
    paint(app, ["memory 8 G", "cpu 40%"], count=10)
    assert T.handle_mouse(app, 3, 2, button="press")
    assert T.handle_mouse(app, 4, 2, button="release")
    paint(app, ["memory 9 G", "cpu 50%"], count=10)
    assert T.selection_text(app) == "memory 8 G\ncpu 40%\n"


def test_source_switch_cancels_capture_and_consumes_late_release():
    app = instance()
    paint(app, ["first job"], context="job1", count=10)
    assert T.handle_mouse(app, 3, 2, button="press")
    paint(app, ["other job"], context="job2", count=10)
    assert not T.selected(app) and not T.active(app)
    assert T.handle_mouse(app, 3, 2, button="release")
    assert not T.handle_mouse(app, 3, 2, button="release")


def test_geometry_change_preserves_pinned_text_but_ends_pointer_capture():
    app = instance()
    paint(app, ["first"], count=10)
    assert T.handle_mouse(app, 3, 2, button="press")
    paint(app, ["first"], count=10, rect=(3, 0, 9, 30))
    assert T.selected(app) and not T.active(app)
    assert T.handle_mouse(app, 5, 2, button="release")


def test_right_click_clears_without_copy_or_click_action():
    app = instance()
    paint(app, ["first", "second"], count=10)
    assert T.handle_mouse(app, 3, 2, button="press")
    assert T.handle_mouse(app, 12, 35, button="right")
    assert not T.selected(app) and not T.active(app)
    assert not T.handle_key(app, "down")


def test_visible_control_is_not_intercepted_by_text_drag():
    app = instance()
    rows = paint(app, ["toggle metrics"], count=10)
    interaction.publish(app, rows, [], app.width, app.height,
                        extra_controls=[dict(id="toggle", label="Toggle", rect=(3, 0, 4, 20), action=("key", "x"))])
    assert not T.handle_mouse(app, 3, 3, button="press")


def test_overlay_selection_uses_modal_text_and_preserves_surrounding_source():
    app = instance(mode="help")
    rows = [[("underlying jobs", "text")] for _ in range(app.height)]
    overlays = [(3, 5, [("+------------+", "dim")]),
                (4, 5, [("| First help |", "text")]),
                (5, 5, [("| Next help  |", "text")]),
                (6, 5, [("+------------+", "dim")])]
    T.publish(app, rows, app.width, app.height, overlays=overlays)
    assert T.handle_mouse(app, 4, 8, button="press")
    assert T.handle_mouse(app, 5, 8, button="release")
    assert T.selection_text(app) == " First help\n Next help\n"


@pytest.mark.parametrize("mode", sorted(T.EDIT_MODES))
def test_edit_and_confirmation_modes_do_not_capture_text(mode):
    app = instance(mode=mode)
    paint(app, ["editor input"], count=10)
    assert not T.handle_mouse(app, 3, 2, button="press")
    assert not T.handle_key(app, "v")


def test_copy_refuses_missing_lines_and_does_not_send_partial_text(monkeypatch):
    app = instance()
    paint(app, ["first", "second"], count=100)
    assert T.handle_key(app, "v")
    assert T.handle_key(app, "end")
    monkeypatch.setattr(clipboard, "copy", lambda *a, **kw: pytest.fail("copied an unseen range"))
    assert T.copy_selection(app) and T.selected(app)
    assert "no partial copy" in app.failures[-1]


def test_wide_and_combining_characters_use_cell_boundaries():
    assert T._slice([("a界e\u0301z", "text")], 1, 5) == "界e\u0301z"
    assert T._slice([("a界e\u0301z", "text")], 2, 5) == " e\u0301z"
    assert T._slice([("a界e\u0301z", "text")], 0, 2) == "a"


def test_full_width_selected_text_remains_visible_without_marker_overwrite():
    app = instance()
    paint(app, ["X" * 29], count=10)
    assert T.handle_key(app, "v")
    assert L.row_text(T.feedback(app)[0][2]) == "X" * 29


def test_pointer_feedback_and_selection_updates_never_read_source(monkeypatch):
    app = instance()
    paint(app, ["first", "second"], count=10)
    monkeypatch.setattr("builtins.open", lambda *a, **kw: pytest.fail("pointer read a file"))
    assert T.handle_mouse(app, 3, 2, button="press")
    started = time.perf_counter()
    for i in range(1000):
        assert T.handle_mouse(app, 3 + i % 2, 2, button="drag")
        assert T.feedback(app)
    assert time.perf_counter() - started < 1.5


def test_nonoverflow_pane_is_selectable_without_rail_crop():
    app = instance()
    paint(app, ["one", "two"], count=2)
    assert any(p.key == "advisor" for p in T.initialize(app)["panes"])
    assert T.handle_mouse(app, 3, 1, button="press")
    assert T.handle_mouse(app, 4, 1, button="release")
    assert T.selection_text(app) == "one\ntwo\n"


def test_left_job_hit_does_not_suppress_details_advisor_selection():
    app = instance(tab="jobs", last_hits=[(3, "job", "41")],
                   job_panel_rect=interaction.Rect(3, 20, 8, 40),
                   workspace_main_rect=interaction.Rect(3, 0, 8, 19))
    paint(app, ["job left            Advisor memory 8 G"], count=10, rect=(3, 20, 8, 40),
          key="workspace:jobs:details")
    assert T.handle_mouse(app, 3, 24, button="press")
    assert "Advisor memory" in T.selection_text(app)


@pytest.mark.parametrize("action", [("row", 3, 2), ("click", 3, 2)])
@pytest.mark.parametrize("mode", ["main", "exports"])
def test_semantic_row_actions_keep_priority_even_without_old_hit_kind(action, mode):
    app = instance(mode=mode)
    rows = paint(app, ["open this source"], count=10)
    if mode != "main":
        T.publish(app, rows, app.width, app.height,
                  overlays=[(2, 0, [("+--------------------+", "dim")]),
                            (3, 0, [("|open this source    |", "text")]),
                            (4, 0, [("+--------------------+", "dim")])])
    interaction.publish(app, rows, [], app.width, app.height,
                        extra_controls=[dict(id="source-row", label="Source", rect=(3, 0, 4, 20),
                                             action=action, button=False)])
    assert not T.handle_mouse(app, 3, 2, button="press")
    assert T.handle_key(app, "v")
    assert T.handle_mouse(app, 3, 2, button="press")


def test_modal_does_not_select_main_document_outside_box():
    app = instance(mode="help")
    S.begin_frame(app)
    S.register(app, "jobs", (2, 0, 14, 40), 100, 12, 0, 0, lambda top: None, layer=0)
    S.publish(app, 40, 15)
    rows = [[("underlying job line", "text")] for _ in range(15)]
    overlays = [(4, 8, [("+----------------+", "dim")]),
                (5, 8, [("| Help text      |", "text")]),
                (6, 8, [("+----------------+", "dim")])]
    T.publish(app, rows, 40, 15, overlays=overlays)
    assert all(p.layer > 0 for p in T.initialize(app)["panes"])
    assert not T.handle_mouse(app, 10, 1, button="press")
    assert T.handle_mouse(app, 5, 10, button="press")
    assert "Help text" in T.selection_text(app)


def test_selected_feedback_renders_same_pinned_text_that_copy_delivers():
    app = instance()
    paint(app, ["memory 8 G", "cpu 40%"], count=10)
    assert T.handle_mouse(app, 3, 2, button="press")
    assert T.handle_mouse(app, 4, 2, button="release")
    paint(app, ["memory 9 G", "cpu 50%"], count=10)
    text = "\n".join(L.row_text(row) for y, x, row in T.feedback(app))
    assert "memory 8 G" in text and "cpu 40%" in text
    assert "memory 9 G" not in text and "cpu 50%" not in text


def test_default_keyboard_job_selection_prefers_main_not_one_row_recents():
    from tower.config import Config
    from tower.controller import App
    from tower.model import Job, Store
    from tower.screen import _FrameCache
    from tower.views import Views
    cfg = Config({"animations": False, "gpu_sampling": False})
    store = Store(persist=False)
    store.apply_jobs([Job("41", "one", "cpu", "RUNNING"), Job("42", "two", "cpu", "RUNNING")])
    app = App(store, None, None, cfg, "test")
    views = Views(L.Glyphs(False), cfg)
    app.views_ref = views
    cache = _FrameCache()
    cache.rebuild(app, views, store, None, 120, 30)
    app.handle("v")
    app.handle("down")
    text = T.selection_text(app)
    assert text is not None and text.count("\n") == 2
    assert "one" in text and "two" in text
    assert T.initialize(app)["selection"]["key"] in ("jobs", "workspace:jobs:main")


def test_copy_all_visible_pane_replaces_active_subset(monkeypatch):
    app = instance()
    paint(app, ["first", "second", "third", "fourth", "fifth"], count=10)
    assert T.handle_mouse(app, 4, 2, button="left")
    assert T.selection_text(app) == "second\n"
    captured = []
    monkeypatch.setattr(clipboard, "copy", lambda text, *a, **kw: captured.append(text) or "copied")
    assert T.copy_visible_pane(app)
    assert captured == ["first\nsecond\nthird\nfourth\nfifth\n"]


def test_inline_log_marker_is_in_original_last_column_and_leaves_rail_clear():
    app = instance()
    paint(app, ["log text"], count=10, rect=(3, 0, 8, 29), key="inline-log")
    assert T.handle_key(app, "v")
    output = T.feedback(app)
    assert any(x == 29 and L.row_text(row) == "▏" for y, x, row in output)
    assert all(x + L.vlen(L.row_text(row)) <= 28 or x == 29 for y, x, row in output)
