"""Chart primitives for the analytics tab: vertical bar / area charts with axes (eight sub-levels per row), horizontal
bar rows, histograms, a Gantt timeline and time axes.  Everything returns rows of (text, style) segments."""
from __future__ import annotations

import math
import sys
import time
from typing import Callable, List, Optional, Sequence, Tuple

from . import clock
from .layout import Glyphs, Row, clip_row, cut, gradient_bar, level, pad, vlen

LEVELS = " ▁▂▃▄▅▆▇█"
LEVELS_ASCII = " ..:::##"
MAX_COLUMNS = 2048
MAX_HEIGHT = 128


def _finite(v: Optional[float]) -> Optional[float]:
    try:
        return v if v is not None and math.isfinite(v) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _mean(values: Sequence[float]) -> float:
    """Stable finite mean, preserving tiny values and avoiding overflow sums."""
    if not values:
        return 0.0
    try:
        return math.fsum(values) / len(values)
    except OverflowError:
        # Scaling can erase tiny residuals after cancellation of huge terms.
        # Float denominators are powers of two; an exact bounded-size integer
        # accumulator preserves those residuals and rounds only the final mean.
        ratios = [float(value).as_integer_ratio() for value in values]
        denominator = max(pair[1] for pair in ratios)
        shift = denominator.bit_length()
        numerator = sum(number << (shift - divisor.bit_length()) for number, divisor in ratios)
        return numerator / (denominator * len(values))


def _fraction(value: float, lo: float, hi: float) -> float:
    """Clamped chart coordinate without overflowing signed finite ranges."""
    if value <= lo or hi <= lo:
        return 0.0
    if value >= hi:
        return 1.0
    span = hi - lo
    if math.isfinite(span):
        return max(0.0, min(1.0, (value - lo) / span))
    scale = max(abs(lo), abs(hi))
    lower, upper = lo / scale, hi / scale
    return max(0.0, min(1.0, (value / scale - lower) / (upper - lower)))


def _between(lo: float, hi: float, fraction: float) -> float:
    """Finite interpolation, including opposite-sign and subnormal endpoints."""
    if fraction <= 0:
        return lo
    if fraction >= 1:
        return hi
    span = hi - lo
    value = lo + span * fraction if math.isfinite(span) else lo * (1 - fraction) + hi * fraction
    return max(lo, min(hi, value))


def _bounds(values: Sequence[Optional[float]], lo: float, hi: Optional[float]) -> Tuple[float, float]:
    lo = lo if _finite(lo) is not None else 0.0
    if _finite(hi) is None:
        peak = max((v for v in values if v is not None), default=lo)
        if peak > lo:
            span = peak - lo
            padding = span * 0.05 if math.isfinite(span) else peak * 0.05 - lo * 0.05
            hi = peak + padding
            if not math.isfinite(hi):
                hi = sys.float_info.max
        else:
            hi = lo + 1.0
    if hi <= lo or not math.isfinite(hi):
        hi = lo + 1.0
        if not math.isfinite(hi) or hi <= lo:
            hi = math.nextafter(lo, math.inf)
            if not math.isfinite(hi):
                hi, lo = lo, math.nextafter(lo, -math.inf)
    return lo, hi


def _header(g: Glyphs, values: Sequence[Optional[float]], width: int, title: str, unit: str, indent: str) -> Row:
    known = [v for v in values if v is not None]
    # The newest sample can be unknown even when earlier samples exist.
    if known:
        tokens = [f"last {fmt_num(values[-1], unit)}", f"mean {fmt_num(_mean(known), unit)}",
                  f"max {fmt_num(max(known), unit)}", f"min {fmt_num(min(known), unit)}"]
    else:
        tokens = ["awaiting samples"]
    usable = max(0, width - vlen(indent))
    if not known and usable < vlen(tokens[0]):
        tokens = ["no data"]
    first = vlen(tokens[0])
    if usable < first:
        return clip_row([(indent + cut(title, usable, g.ascii), "cyan+bold")], width)
    title_budget = min(max(0, usable - first - 2), max(5, usable // 2))
    short_title = cut(title, title_budget, g.ascii)
    row: Row = [(indent + short_title, "cyan+bold")]
    used = vlen(indent) + vlen(short_title)
    for token in tokens:
        prefix = "  " if short_title or len(row) > 1 else ""
        if used + vlen(prefix + token) > width:
            break
        row.append((prefix + token, "dim"))
        used += vlen(prefix + token)
    return row


def _time_points(values: Sequence[Optional[float]], sample_times: Sequence[float], width: int,
                 times: Optional[Tuple[float, float]], sample_interval: Optional[float]) -> Tuple[List[Tuple[int, Optional[float], bool]], Tuple[float, float]]:
    """Bounded timestamp buckets with enough metadata to break curves across outages."""
    samples = [(timestamp, value) for timestamp, value in zip(sample_times, values) if math.isfinite(timestamp)]
    samples.sort(key=lambda item: item[0])
    if times is None or not all(math.isfinite(t) for t in times) or times[1] < times[0]:
        times = (samples[0][0], samples[-1][0]) if samples else (0.0, 0.0)
    if width <= 0:
        return [], times
    deltas = sorted(b[0] - a[0] for a, b in zip(samples, samples[1:]) if b[0] > a[0] and math.isfinite(b[0] - a[0]))
    cadence = sample_interval if sample_interval is not None and math.isfinite(sample_interval) and sample_interval > 0 else (
              deltas[(len(deltas) - 1) // 2] if deltas else 0.0)
    gap_limit = min(sys.float_info.max, cadence * 2.5)
    t0, t1 = times
    buckets: dict[int, list[Tuple[float, Optional[float], bool]]] = {}
    previous: Optional[Tuple[float, Optional[float]]] = None
    for timestamp, value in samples:
        bridge = previous is not None and value is not None and previous[1] is not None and timestamp - previous[0] <= gap_limit
        previous = (timestamp, value)
        if timestamp < t0 or timestamp > t1:
            continue
        x = min(width - 1, max(0, round(_fraction(timestamp, t0, t1) * (width - 1)))) if t1 > t0 else width - 1
        buckets.setdefault(x, []).append((timestamp, value, bridge))
    points: List[Tuple[int, Optional[float], bool]] = []
    previous_last: Optional[float] = None
    for x, bucket in sorted(buckets.items()):
        known = all(value is not None for _, value, _ in bucket)
        value = _mean([value for _, value, _ in bucket]) if known else None
        bridge = known and bucket[0][2] and previous_last is not None and bucket[0][0] - previous_last <= gap_limit
        points.append((x, value, bridge))
        previous_last = bucket[-1][0] if known else None
    return points, times


def resample(values: Sequence[Optional[float]], width: int, how: str = "mean") -> List[Optional[float]]:
    """``values`` -> ``width`` buckets (mean or max; None if any sample in a bucket is missing).
    Fewer values than columns are right-aligned without stretching."""
    vals = [_finite(v) for v in values]
    if width <= 0:
        return []
    if len(vals) <= width:
        return [None] * (width - len(vals)) + vals
    out: List[Optional[float]] = []
    n = len(vals)
    for i in range(width):
        a, b = (i * n) // width, max(((i + 1) * n) // width, (i * n) // width + 1)
        chunk = vals[a:b]
        # A bucket intersecting an unobserved interval remains a gap. This avoids
        # drawing continuous telemetry across a failed sample or stale connection.
        out.append(None if not chunk or any(v is None for v in chunk) else
                   (_mean(chunk) if how == "mean" else max(chunk)))
    return out


def fmt_num(v: Optional[float], unit: str = "") -> str:
    if v is None or not math.isfinite(v):
        return "?"
    a = abs(v)
    if a >= 1e15 or (0 < a < 0.01):
        return f"{v:.2g}{unit}"
    if unit == "%":
        return f"{v:.0f}%"
    if a >= 1e9:
        return f"{v / 1e9:.1f}G{unit}"
    if a >= 1e6:
        return f"{v / 1e6:.1f}M{unit}"
    if a >= 1e3:
        return f"{v / 1e3:.1f}k{unit}"
    if a >= 10 or v == int(v):
        return f"{v:.0f}{unit}"
    return f"{v:.2f}{unit}"


def time_axis(t0: float, t1: float, width: int, indent: str = "", elapsed: bool = False) -> Row:
    """One row with time labels spread over ``width`` columns (HH:MM, or MM-DD HH:MM when the span crosses days)."""
    width = max(0, min(MAX_COLUMNS, width))
    if width <= 8 or _finite(t0) is None or _finite(t1) is None or t1 <= t0:
        return [(indent + " " * max(0, width), "dim")]
    span = t1 - t0
    fmt = "%H:%M" if span < 36 * 3600 else "%m-%d %H:%M"
    n = max(2, min(8, width // 14))
    if span < 120 and not elapsed:                          # too short for a scale: one label at the end
        try:
            label = time.strftime("%H:%M:%S", time.localtime(t1))
        except (OverflowError, OSError, ValueError):
            label = fmt_num(t1, "s")
        label = cut(label, width, True)
        return [(indent + " " * max(0, width - len(label)) + label, "dim")]
    line = [" "] * width
    for i in range(n):
        frac = i / (n - 1)
        value = _between(t0, t1, frac)
        label = fmt_num(value / 3600, "h") if elapsed and span >= 3600 else (
                fmt_num(value / 60, "m") if elapsed and span >= 120 else (
                fmt_num(value, "s") if elapsed else ""))
        if not elapsed:
            try:
                label = time.strftime(fmt, time.localtime(value))
            except (OverflowError, OSError, ValueError):
                label = fmt_num(value, "s")
        label = cut(label, width, True)
        x = int(round(frac * (width - 1)))
        x = max(0, min(width - len(label), x - len(label) // 2))
        if all(c == " " for c in line[x:x + len(label) + 1]):
            line[x:x + len(label)] = list(label)
    return [(indent + "".join(line), "dim")]


def _trace_axis(times: Tuple[float, float], samples: int, chart_w: int, indent: str, raster: int = 1, elapsed: bool = False) -> Row:
    """Label only the occupied trace extent when a short trace is right-aligned."""
    occupied = min(chart_w, (samples + raster - 1) // raster)
    return time_axis(times[0], times[1], occupied, indent + " " * (chart_w - occupied), elapsed)


def vbar_chart(g: Glyphs, values: Sequence[Optional[float]], width: int, height: int, lo: float = 0.0, hi: Optional[float] = None,
               unit: str = "", title: str = "", times: Optional[Tuple[float, float]] = None, color: Optional[Callable[[float], str]] = None,
               indent: str = "   ", axis_w: int = 7, sample_times: Optional[Sequence[float]] = None,
               sample_interval: Optional[float] = None, elapsed: bool = False) -> List[Row]:
    """A vertical bar (area) chart ``height`` rows tall with eight sub-levels per row, a y axis on the left and a
    time axis below.  ``values`` are resampled to the chart width; None leaves a gap."""
    chart_w = max(0, min(MAX_COLUMNS, width - vlen(indent) - axis_w))
    height = max(0, min(MAX_HEIGHT, height))
    values = [_finite(v) for v in values]
    if sample_times is None:
        vals = resample(values, chart_w)
    else:
        points, times = _time_points(values, sample_times, chart_w, times, sample_interval)
        vals = [None] * chart_w
        for x, value, _ in points:
            vals[x] = value
    # Summary figures describe the source samples, not the bucket averages used to draw the chart.
    lo, hi = _bounds(values, lo, hi)
    levels = g.spark if not g.ascii else LEVELS_ASCII[1:]
    nlev = len(levels)
    rows: List[Row] = []
    if title:
        rows.append(_header(g, values, width, title, unit, indent))
    for r in range(height):
        label = ""
        if r == 0:
            label = fmt_num(hi, unit)
        elif r == height - 1:
            label = fmt_num(lo, unit)
        elif height >= 5 and r == height // 2:
            label = fmt_num(_mean((lo, hi)), unit)
        segs: Row = [(indent + pad(cut(label, max(0, axis_w - 1), g.ascii), axis_w - 1, ">") + (g.box[5] if not g.ascii else "|"), "dim")]
        floor = (height - 1 - r) * nlev                      # sub-levels below this row
        row_style = ""
        if not g.ascii and not color:
            from .palette import gradient
            row_style = "fg:" + gradient("#155e75", "#67e8f9", (height - r) / max(1, height))
        for x, v in enumerate(vals):
            guide = g.dot if not g.ascii and r in (0, height // 2) and x % 8 == 0 else " "
            if v is None:
                segs.append((guide, "dim"))
                continue
            frac = _fraction(v, lo, hi)
            lv = int(round(frac * height * nlev))
            fill = min(nlev, max(0, lv - floor))
            if fill > 0:
                if color:
                    style = color(frac)
                elif g.ascii:
                    style = level(frac)
                else:
                    style = row_style
                segs.append((levels[fill - 1], style))
            else:
                # A measured zero has an anchor; an unobserved sample stays blank.
                segs.append((g.dot if r == height - 1 and v == lo else guide, "dim"))
        rows.append(segs)
    base = indent + " " * (axis_w - 1) + ("+" if g.ascii else "└") + g.rule * chart_w
    rows.append([(base, "dim")])
    if times:
        rows.append(_trace_axis(times, len(values), chart_w, indent + " " * axis_w, elapsed=elapsed) if sample_times is None else
                    time_axis(times[0], times[1], chart_w, indent + " " * axis_w, elapsed))
    return [clip_row(row, width) for row in rows]


def hbar_rows(g: Glyphs, items: Sequence[Tuple[str, float, str]], width: int, indent: str = "   ", label_w: int = 12, unit: str = "",
              hi: Optional[float] = None, color: Optional[Callable[[str, float], str]] = None) -> List[Row]:
    """One row per (label, value, style): ``label  ████░░░░  value``."""
    if not items:
        return []
    hi = hi if _finite(hi) is not None else max((v for _, v, _ in items if _finite(v) is not None), default=1.0)
    hi = hi if hi > 0 else 1.0
    label_w = min(label_w, max(1, (width - vlen(indent) - 10) // 2))
    bar_w = max(0, width - vlen(indent) - label_w - 12)
    rows: List[Row] = []
    for label, v, style in items:
        value = _finite(v)
        frac = None if value is None else _fraction(value, 0.0, hi)
        row: Row = [(indent + pad(cut(label, label_w, g.ascii), label_w) + " ", "")]
        if g.ascii or color:
            from .layout import bar
            text, _ = bar(g, frac, bar_w)
            filled = text.rstrip(g.empty)
            row += [(filled, style or (color(label, v) if color else "cyan")), (g.empty * (bar_w - vlen(filled)), "dim")]
        else:
            shades = {"green": ("#065f46", "#6ee7b7"), "red": ("#881337", "#fb7185"),
                      "yellow": ("#92400e", "#fcd34d"), "magenta": ("#6b21a8", "#d8b4fe"),
                      "blue": ("#1e40af", "#93c5fd"), "cyan": ("#155e75", "#67e8f9")}
            start, end = shades.get(style.split("+")[0], ("#155e75", "#67e8f9"))
            row += gradient_bar(g, frac, bar_w, start, end)
        row += [(f" {fmt_num(v, unit)}", "bold")]
        rows.append(row)
    return [clip_row(row, width) for row in rows]


def braille_chart(g: Glyphs, values: Sequence[Optional[float]], width: int, height: int, lo: float = 0.0,
                  hi: Optional[float] = None, unit: str = "", title: str = "",
                  times: Optional[Tuple[float, float]] = None, color: Optional[Callable[[float], str]] = None,
                  indent: str = "   ", axis_w: int = 7, sample_times: Optional[Sequence[float]] = None,
                  sample_interval: Optional[float] = None, elapsed: bool = False) -> List[Row]:
    """A high-resolution telemetry curve using a 2 x 4 dot raster per terminal cell.

    Adjacent observed samples are connected; missing samples break the curve. Short
    traces stay right-aligned without stretching time. Zero is a real baseline point.
    The explicit ASCII mode uses the equivalent filled area chart.
    """
    if g.ascii:
        return vbar_chart(g, values, width, height, lo, hi, unit, title, times, color, indent, axis_w, sample_times, sample_interval, elapsed)
    from .palette import gradient
    values = [_finite(v) for v in values]
    lo, hi = _bounds(values, lo, hi)
    chart_w = max(0, min(MAX_COLUMNS, width - vlen(indent) - axis_w))
    height = max(0, min(MAX_HEIGHT, height))
    if sample_times is None:
        points = [(x, value, True) for x, value in enumerate(resample(values, chart_w * 2))]
    else:
        points, times = _time_points(values, sample_times, chart_w * 2, times, sample_interval)
    pixels_h = height * 4
    cells = [[0] * chart_w for _ in range(height)]
    dots = ((1, 2, 4, 64), (8, 16, 32, 128))

    def mark(x: int, y: int) -> None:
        if 0 <= x < chart_w * 2 and 0 <= y < pixels_h:
            cells[y // 4][x // 2] |= dots[x % 2][y % 4]

    previous: Optional[Tuple[int, int]] = None
    if pixels_h:
        for x, value, bridge in points:
            if value is None:
                previous = None
                continue
            fraction = _fraction(value, lo, hi)
            y = int(round((1 - fraction) * (pixels_h - 1)))
            mark(x, y)
            if previous is not None and bridge:
                px, py = previous
                # x advances by exactly one observed raster column. A vertical
                # span is rasterized at its nearest side for a continuous curve.
                distance = max(abs(x - px), abs(y - py))
                for step in range(1, distance):
                    t = step / distance
                    mark(int(round(px + (x - px) * t)), int(round(py + (y - py) * t)))
            previous = (x, y)
    rows: List[Row] = []
    if title:
        rows.append(_header(g, values, width, title, unit, indent))
    for r, masks in enumerate(cells):
        label = fmt_num(hi, unit) if r == 0 else (fmt_num(lo, unit) if r == height - 1 else
                (fmt_num(_mean((lo, hi)), unit) if height >= 5 and r == height // 2 else ""))
        row: Row = [(indent + pad(cut(label, max(0, axis_w - 1), g.ascii), axis_w - 1, ">") + "│", "dim")]
        fraction = 1 - r / max(1, height - 1)
        style = color(fraction) if color else "fg:" + gradient("#38bdf8", "#c4b5fd", fraction)
        for x, mask in enumerate(masks):
            guide = "·" if r in (0, height // 2) and x % 8 == 0 else " "
            row.append((chr(0x2800 + mask), style + "+bold") if mask else (guide, "dim"))
        rows.append(row)
    rows.append([(indent + " " * max(0, axis_w - 1) + "└" + "─" * chart_w, "dim")])
    if times:
        rows.append(_trace_axis(times, len(values), chart_w, indent + " " * axis_w, 2, elapsed) if sample_times is None else
                    time_axis(times[0], times[1], chart_w, indent + " " * axis_w, elapsed))
    return [clip_row(row, width) for row in rows]


def heatmap(g: Glyphs, matrix: Sequence[Sequence[Optional[float]]], width: int, labels: Sequence[str] = (),
            title: str = "", lo: float = 0.0, hi: Optional[float] = None, unit: str = "", indent: str = " ",
            temporal: bool = True) -> List[Row]:
    """Measured matrix: opaque two-column cells, missing values marked explicitly.

    Rows share one scale. Each row also prints its newest measurement so the map
    remains useful with colour disabled. At most 128 matrix rows are rendered.
    """
    from .palette import gradient
    source = [[_finite(v) for v in values] for values in matrix[:MAX_HEIGHT]]
    lo, hi = _bounds([v for values in source for v in values], lo, hi)
    label_w = min(16, max(0, (width - vlen(indent) - 12) // 3)) if labels else 0
    cell_w = 1 if g.ascii else 2
    count = max(0, min(MAX_COLUMNS // cell_w, (width - vlen(indent) - label_w - 10) // cell_w))
    out: List[Row] = []
    if title:
        out.append(clip_row([(indent + title, "cyan+bold"), (f"  {fmt_num(lo, unit)} to {fmt_num(hi, unit)}", "dim")], width))
    if not source:
        out.append(clip_row([(indent + "awaiting samples", "dim")], width))
    for i, values in enumerate(source):
        label = labels[i] if i < len(labels) else ""
        row: Row = [(indent + (pad(cut(label, label_w, g.ascii), label_w) + " " if label_w else ""), "dim")]
        for value in resample(values, count):
            if value is None:
                row.append(("?" if g.ascii else "··", "dim"))
            else:
                fraction = _fraction(value, lo, hi)
                if g.ascii:
                    row.append((g.spark[min(7, int(fraction * 7.999))], level(fraction)))
                else:
                    shade = gradient("#164e63", "#22d3ee", fraction * 2) if fraction < 0.5 else gradient("#22d3ee", "#fbbf24", (fraction - 0.5) * 2)
                    row.append(("██", "fg:" + shade))
        latest = values[-1] if values else None
        row.append((" " + fmt_num(latest, unit), "bold"))
        out.append(clip_row(row, width))
    if source:
        out.append(clip_row([(indent + ("?" if g.ascii else "··") + " unobserved" +
                            ("  newest at right" if temporal else ""), "dim")], width))
    return out


def stacked_bar(g: Glyphs, items: Sequence[Tuple[str, Optional[float], str]], width: int,
                indent: str = " ", title: str = "") -> List[Row]:
    """A proportional composition bar with an explicit numeric colour legend.

    Each item's style is respected. Unknown values are labelled '?' and receive no
    inferred allocation; all-zero data is labelled 'total 0'. Returns two rows.
    """
    values = [(label, _finite(value), style) for label, value, style in items]
    scale = max((max(0.0, value) for _, value, _ in values if value is not None), default=0.0)
    proportions = [max(0.0, value) / scale if value is not None and scale else 0.0 for _, value, _ in values]
    total = math.fsum(proportions)
    span = max(0, min(MAX_COLUMNS, width - vlen(indent)))
    prefix = (title + "  ") if title else ""
    bar_w = max(0, span - vlen(prefix))
    row: Row = [(indent + prefix, "cyan+bold")]
    if total > 0:
        # Round cumulative boundaries, so the allocated cells always sum to bar_w.
        positive = sum(value is not None and value > 0 for _, value, _ in values)
        separators = max(0, positive - 1) if bar_w >= positive * 2 - 1 else 0
        fill_w = bar_w - separators
        cumulative, previous, used, groups = 0.0, 0, 0, 0
        for (_, value, style), proportion in zip(values, proportions):
            cumulative += proportion
            boundary = min(fill_w, int(round(cumulative / total * fill_w)))
            length = boundary - previous
            if length:
                if groups and separators:
                    row.append(("|" if g.ascii else "│", "dim"))
                    used += 1
                row.append((g.full * length, style or "cyan"))
                used += length
                groups += 1
            previous = boundary
        row.append((g.empty * max(0, bar_w - used), "dim"))
    else:
        row.append((g.empty * bar_w, "dim"))
    legend: Row = [(indent, "")]
    for i, (label, value, style) in enumerate(values):
        if i:
            legend.append(("  ", ""))
        legend.append(((g.full + " " if not g.ascii else "") + label + " " + fmt_num(value), style or "cyan"))
    if not values or not any(value is not None for _, value, _ in values):
        legend.append(("awaiting samples", "dim"))
    elif total == 0:
        legend.append(("  total 0", "dim"))
    return [clip_row(row, width), clip_row(legend, width)]


def histogram(g: Glyphs, values: Sequence[float], bins: Sequence[float], width: int, indent: str = "   ", unit: str = "",
              fmt: Optional[Callable[[float], str]] = None) -> List[Row]:
    """Counts of ``values`` in the intervals of ``bins`` (edges, ascending; the last interval is open) as hbar rows."""
    vals = [v for v in values if v is not None]
    if not vals or not bins:
        return []
    f = fmt or (lambda x: fmt_num(x, unit))
    counts = [0] * (len(bins))
    for v in vals:
        i = 0
        while i + 1 < len(bins) and v >= bins[i + 1]:
            i += 1
        counts[i] += 1
    items = []
    for i, c in enumerate(counts):
        label = f"{f(bins[i])}-{f(bins[i + 1])}" if i + 1 < len(bins) else f">= {f(bins[i])}"
        items.append((label, float(c), "cyan"))
    return hbar_rows(g, items, width, indent=indent, label_w=max(10, max(vlen(l) for l, _, _ in items)), unit="")


def gantt(g: Glyphs, jobs: Sequence[dict], t0: float, t1: float, width: int, indent: str = "   ", label_w: int = 26) -> List[Row]:
    """A timeline: one row per job dict(name, id, state, submit, start, end) with epoch seconds (None when unknown),
    the queue wait as dots and the run as a bar, coloured by state; a time axis above."""
    label_w = min(label_w, max(1, (width - vlen(indent) - 12) // 2))
    bar_w = max(1, width - vlen(indent) - label_w - 12)    # room for the state after the bar
    rows: List[Row] = [time_axis(t0, t1, bar_w, indent + " " * (label_w + 1))]
    span = max(1.0, t1 - t0)

    def col(t):
        fraction = _fraction(t, t0, t1) if span >= 1.0 else min(max(t, t0), t1) - t0
        return int(round(fraction * (bar_w - 1)))

    for j in jobs:
        state = j.get("state", "")
        style = {"COMPLETED": "green", "RUNNING": "cyan", "PENDING": "yellow"}.get(state, "yellow" if state.startswith("CANCEL") else "red")
        line = [" "] * bar_w
        sub, start, end = j.get("submit"), j.get("start"), j.get("end")
        now = clock.now()
        if sub is not None and (start is not None or state == "PENDING"):
            queue_end = start if start is not None else now
            if sub <= t1 and queue_end >= t0 and queue_end >= sub:
                a, b = col(sub), col(queue_end)
                for x in range(a, b + 1):
                    line[x] = g.dot
        if start is not None:
            run_end = end if end is not None else (now if state in ("RUNNING", "COMPLETING", "SUSPENDED", "CONFIGURING") else None)
            if run_end is not None and start <= t1 and run_end >= t0 and run_end >= start:
                a, b = col(start), col(run_end)
                for x in range(a, b + 1):
                    line[x] = g.full
            elif run_end is None and t0 <= start <= t1:
                line[col(start)] = "?"
        label = cut(f"{j.get('name', '')} {j.get('id', '')}", label_w, g.ascii)
        text = "".join(line)
        rows.append([(indent + pad(label, label_w) + " ", "" if state != "PENDING" else "dim"), (text, style), (f" {state.lower()[:9]}", style)])
    return [clip_row(row, width) for row in rows]


def summary_line(g: Glyphs, parts: Sequence[Tuple[str, str]], indent: str = " ") -> Row:
    row: Row = [(indent, "")]
    for i, (text, style) in enumerate(parts):
        row.append((text, style))
        if i < len(parts) - 1:
            row.append((f"  {g.dot}  ", "dim"))
    return row
