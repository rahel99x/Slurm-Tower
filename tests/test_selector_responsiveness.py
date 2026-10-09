"""Latest-event selectors retain source ink without reopening metric sources."""
from copy import deepcopy
import math
from types import SimpleNamespace

import pytest

from tower import chart_interaction as C, charts, layout as L, palette as P, selector_glyphs as G
from tower.interaction import Rect


@pytest.fixture
def clock(monkeypatch):
    value = SimpleNamespace(now=0.)
    monkeypatch.setattr(C.time, "monotonic", lambda: value.now)
    return value


@pytest.fixture
def app(clock):
    value = SimpleNamespace(mode="main", tab="analytics", width=120, height=40,
                            selected_id="101", analytics_job="101", analytics_view="job",
                            toolbar_state={}, project_state={}, job_panel_state={}, analysis_state={},
                            research=SimpleNamespace(generation=3), theme="default", animations_enabled=True,
                            cfg={"animations": True}, messages=[], views_ref=SimpleNamespace(g=L.Glyphs(False)))
    value.say = value.messages.append
    C.begin_frame(value, value.width, value.height)
    C.record(value, ("job", "101", "CPU"),
             {"plot_rect": (2, 10, 12, 70), "x_bounds": (0., 100.), "y_bounds": (0., 200.)})
    C.publish(value, value.width, value.height)
    return value


def marks(app, rows=None, overlays=()):
    return {(y, x): tuple(row) for y, x, row in C.feedback(app, rows=rows, overlays=overlays)}


@pytest.mark.parametrize("target", [(5, 29), (5, 31), (4, 30), (6, 30), (4, 29), (4, 31),
                                    (6, 29), (6, 31), (2, 10), (11, 69)])
@pytest.mark.parametrize("elapsed", [0., .001, .012, .025])
def test_latest_received_cell_is_visible_immediately_in_every_direction(app, clock, target, elapsed):
    item = C.initialize(app)["plots"][0]
    C.hover(app, 5, 30)
    C.hover(app, *target)
    clock.now = elapsed
    cursor = C._visual_pointer(app, item)
    assert (cursor.row, cursor.column) == target
    result = marks(app)
    # No phantom cursor line remains in the event's previous row or column.
    expected = {(target[0], x) for x in range(item.visible.left, item.visible.right)}
    expected |= {(y, target[1]) for y in range(item.visible.top, item.visible.bottom)}
    assert set(result) == expected
    assert result[target][0][0] == G.glyph(cursor.y_slot, cursor.x_slot, horizontal=True, vertical=True)


def test_bursts_and_reversals_follow_each_latest_cell_without_a_replay_queue(app, clock):
    item = C.initialize(app)["plots"][0]
    C.hover(app, 5, 30)
    for index in range(2000):
        target = (2 + index % 10, 10 + (index * 47) % 60)
        clock.now = index / 1_000_000
        C.hover(app, *target)
        cursor = C._visual_pointer(app, item)
        assert (cursor.row, cursor.column) == target
    state = C.initialize(app)
    started = state["visual"]["started"]
    clock.now += .010
    C.hover(app, *target)
    assert state["visual"]["started"] == started
    clock.now = started + .025
    assert C._visual_pointer(app, item) == G.Cell(*target, 2, 1)
    assert math.isinf(C.next_deadline(app))
    assert state["revision"] == 0 and not state["zoom"] and not state["capture"]


def test_latest_raw_cell_is_stable_even_when_visual_state_or_clock_is_stale(app, clock):
    item = C.initialize(app)["plots"][0]
    C.hover(app, 5, 30)
    C.hover(app, 9, 60)
    state = C.initialize(app)
    state["visual"]["start"] = (3.25, 12.25)
    state["visual"]["started"] = 10.
    clock.now = -1.
    cursor = C._visual_pointer(app, item)
    assert (cursor.row, cursor.column) == (9, 60)


@pytest.mark.parametrize("disabled", ["ascii", "reader", "animations"])
def test_accessibility_and_static_modes_track_events_without_phase_wakeups(app, disabled):
    if disabled == "ascii":
        C.initialize(app)["ascii"] = True
    elif disabled == "reader":
        app.theme = "reader"
    else:
        app.animations_enabled = False
    item = C.initialize(app)["plots"][0]
    C.hover(app, 5, 30)
    C.hover(app, 9, 60)
    assert C._visual_pointer(app, item) == G.Cell(9, 60, 2, 1)
    assert math.isinf(C.next_deadline(app))


@pytest.mark.parametrize("glyph", ["⠁", "⠒", "⣷", "⣿", "▘", "▟", "█", "▁", "▇", "-", "/", "\\", ":", "+", ".", "·", "?", "│"])
@pytest.mark.parametrize("source_style", ["chart-2+bold+bg:surface-sunken", "#fb7185+bg:#192530",
                                         "grad:chart-1:chart-3:0.5+bg:surface", "chart-3+rev"])
def test_crosshair_keeps_measured_strokes_and_annotations_exactly(app, glyph, source_style):
    C.hover(app, 5, 30)
    rows = [[(" " * 120, "bg:surface")] for _ in range(40)]
    rows[5] = [(" " * 30, "bg:surface"), (glyph, source_style), (" " * 89, "bg:surface")]
    before = deepcopy(rows)
    result = marks(app, rows)
    # Retaining the actual character avoids inventing extra measurement dots
    # and preserves the series' colour even when it intersects the cursor head.
    assert result[(5, 30)] == ((glyph, source_style),)
    assert rows == before
    blank = result[(5, 31)][0]
    assert blank[0] == G.HORIZONTAL_GLYPHS[2]
    assert P.resolve(P.cell_style(blank[1], app.theme), app.theme).foreground == P.resolve("accent", app.theme).foreground
    assert "bold" not in blank[1] and "rev" not in blank[1]


@pytest.mark.parametrize("theme", P.THEME_NAMES + ("monokai", "Gruvbox Dark", "Modnokai"))
def test_runtime_theme_switch_preserves_series_colours_and_the_exact_blank_canvas(app, theme):
    C.hover(app, 5, 30)
    rows = [[(" " * 120, "chart-3+rev")] for _ in range(40)]
    rows[5] = [(" " * 30, "chart-3+rev"), ("⠒", "chart-2+bold+bg:surface-sunken"),
               (" " * 89, "chart-3+rev")]
    marks(app, rows)  # Populate the cached row before changing its active theme.
    app.theme = theme
    result = marks(app, rows)
    assert result[(5, 30)] == (("⠒", "chart-2+bold+bg:surface-sunken"),)
    blank = P.resolve(P.cell_style(result[(5, 31)][0][1], theme), theme)
    assert blank.foreground == P.resolve("accent", theme).foreground
    assert blank.background == P.resolve("chart-3+rev", theme).foreground


@pytest.mark.parametrize("ascii_,curve_style", [(False, "fine"), (False, "blocks"), (True, "fine")])
def test_actual_curve_rasters_survive_all_selector_row_intersections(app, ascii_, curve_style, monkeypatch):
    metadata = {}
    rows = charts.braille_chart(L.Glyphs(ascii_), [0., .3, .9, .6, None, .7, .2, .5],
                                90, 10, lo=0., hi=1., indent="", axis_w=5,
                                sample_times=list(range(8)), color=lambda _: "chart-2",
                                curve_style=curve_style, metadata=metadata)
    C.begin_frame(app, app.width, app.height)
    C.initialize(app)["ascii"] = ascii_
    C.record(app, ("job", "101", "actual-raster"), metadata)
    item = C.publish(app, app.width, app.height)[0]
    pristine = deepcopy(rows)

    def forbidden(*args, **kwargs):
        pytest.fail("A cursor intersection reopened a metric source or rebuilt its raster")

    app.store = SimpleNamespace(snapshot=forbidden)
    app.research.current = app.research.request = forbidden
    monkeypatch.setattr(C.charts, "braille_chart", forbidden)
    monkeypatch.setattr(C.charts, "vbar_chart", forbidden)
    measured = 0
    for y in range(item.visible.top, item.visible.bottom):
        C.hover(app, y, item.visible.left + 20)
        result = marks(app, rows)
        x = 0
        for text, style in rows[y]:
            for glyph in text:
                if item.visible.contains(y, x) and not glyph.isspace():
                    assert result[(y, x)] == ((glyph, style),)
                    if "chart-2" in style:
                        measured += 1
                x += L.vlen(glyph)
    assert measured > 15
    assert rows == pristine


def test_topmost_blank_overlay_hides_old_curve_but_new_overlay_ink_is_preserved(app):
    C.hover(app, 5, 30)
    rows = [[(" " * 120, "bg:surface")] for _ in range(40)]
    rows[5] = [(" " * 30, "bg:surface"), ("⣿", "chart-1+bold"), (" " * 89, "bg:surface")]
    overlays = [(5, 29, [("   ", "bg:surface-raised")]),
                (5, 31, [("/", "chart-3+bg:surface-sunken")])]
    before = deepcopy(overlays)
    result = marks(app, rows, overlays)
    assert result[(5, 30)][0][0] == G.glyph(horizontal=True, vertical=True)
    resolved = P.resolve(P.cell_style(result[(5, 30)][0][1], app.theme), app.theme)
    assert resolved.background == P.resolve("bg:surface-raised", app.theme).background
    assert result[(5, 31)] == (("/", "chart-3+bg:surface-sunken"),)
    assert overlays == before


def test_wide_and_combining_annotations_are_never_split_or_replaced(app):
    C.hover(app, 5, 30)
    rows = [[(" " * 120, "bg:surface")] for _ in range(40)]
    rows[5] = [(" " * 20, "bg:surface"), ("界", "chart-2"), (" ", "dim"),
               ("e", "chart-3"), ("\u0301", "chart-3"), (" " * 96, "bg:surface")]
    result = marks(app, rows)
    assert (5, 20) not in result and (5, 21) not in result
    assert result[(5, 23)] == (("e\u0301", "chart-3"),)
    assert L.vlen(result[(5, 23)][0][0]) == 1
    assert result[(5, 22)][0][0] == G.HORIZONTAL_GLYPHS[2]


def test_same_row_mutations_refresh_cached_ink_and_unchanged_rows_reuse_it(app, monkeypatch):
    C.hover(app, 5, 30)
    rows = [[(" " * 120, "bg:surface")] for _ in range(40)]
    rows[5] = [(" " * 30, "bg:surface"), ("⠒", "chart-2"), (" " * 89, "bg:surface")]
    assert marks(app, rows)[(5, 30)] == (("⠒", "chart-2"),)
    cached = C.initialize(app)["ink_rows"][(5, 10, 70)][1]
    marks(app, rows)
    assert C.initialize(app)["ink_rows"][(5, 10, 70)][1] is cached
    rows[5][1] = ("/", "chart-3")
    assert marks(app, rows)[(5, 30)] == (("/", "chart-3"),)
    assert C.initialize(app)["ink_rows"][(5, 10, 70)][1] is not cached


def test_cached_source_ink_is_bounded_and_oversized_embedding_rows_are_not_retained(app):
    visible = Rect(0, 0, 200, 20)
    for y in range(200):
        C._painted_cells(app, visible, y, [(0, [(" " * 20, "bg:surface")])])
    cache = C.initialize(app)["ink_rows"]
    assert len(cache) == C.MAX_FEEDBACK_ROWS and (0, 0, 20) not in cache
    C._painted_cells(app, visible, 201, [(0, [("⠒" * 20000, "chart-2")])])
    assert (201, 0, 20) not in cache and len(cache) == C.MAX_FEEDBACK_ROWS


def test_release_zoom_uses_latest_raw_bounds_when_curve_ink_covers_the_preview(app, clock):
    item = C.initialize(app)["plots"][0]
    rows = [[("⣿" * 120, "chart-3+bold")] for _ in range(40)]
    C.handle_mouse(app, 4, 18, button="press")
    C.handle_mouse(app, 9, 56, button="drag")
    result = marks(app, rows)
    assert all(row == (("⣿", "chart-3+bold"),) for row in result.values())
    assert C.initialize(app)["capture"]["current"] == (9, 56)
    clock.now = .001
    C.handle_mouse(app, 9, 56, button="release")
    assert C.bounds(app, item.key)["x"] == pytest.approx((100 * 8 / 59, 100 * 46 / 59))
    assert C.autofit(app, item.key) and not C.active(app)
