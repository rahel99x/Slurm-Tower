"""Chart primitives for the analytics tab: vertical bar / area charts with axes (eight sub-levels per row), horizontal
bar rows, histograms, a Gantt timeline and time axes.  Everything returns rows of (text, style) segments."""
from __future__ import annotations

import math
import time
from typing import Callable, List, Optional, Sequence, Tuple

from . import clock
from .layout import Glyphs, Row, clip_row, cut, level, pad, vlen

LEVELS = " ▁▂▃▄▅▆▇█"
LEVELS_ASCII = " ..:::##"


def resample(values: Sequence[Optional[float]], width: int, how: str = "mean") -> List[Optional[float]]:
    """``values`` -> ``width`` buckets (mean or max of each; None where a bucket is empty).  Fewer values than
    columns are right-aligned without stretching."""
    vals = list(values)
    if width <= 0:
        return []
    if len(vals) <= width:
        return [None] * (width - len(vals)) + vals
    out: List[Optional[float]] = []
    n = len(vals)
    for i in range(width):
        a, b = (i * n) // width, max(((i + 1) * n) // width, (i * n) // width + 1)
        chunk = [v for v in vals[a:b] if v is not None]
        out.append(None if not chunk else (sum(chunk) / len(chunk) if how == "mean" else max(chunk)))
    return out


def fmt_num(v: Optional[float], unit: str = "") -> str:
    if v is None:
        return "?"
    a = abs(v)
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


def time_axis(t0: float, t1: float, width: int, indent: str = "") -> Row:
    """One row with time labels spread over ``width`` columns (HH:MM, or MM-DD HH:MM when the span crosses days)."""
    if width <= 8 or t1 <= t0:
        return [(indent + " " * max(0, width), "dim")]
    span = t1 - t0
    fmt = "%H:%M" if span < 36 * 3600 else "%m-%d %H:%M"
    n = max(2, min(8, width // 14))
    if span < 120:                                          # too short for a scale: one label at the end
        label = time.strftime("%H:%M:%S", time.localtime(t1))
        return [(indent + " " * max(0, width - len(label)) + label, "dim")]
    line = [" "] * width
    for i in range(n):
        frac = i / (n - 1)
        label = time.strftime(fmt, time.localtime(t0 + frac * span))
        x = int(round(frac * (width - 1)))
        x = max(0, min(width - len(label), x - len(label) // 2))
        if all(c == " " for c in line[x:x + len(label) + 1]):
            line[x:x + len(label)] = list(label)
    return [(indent + "".join(line), "dim")]


def vbar_chart(g: Glyphs, values: Sequence[Optional[float]], width: int, height: int, lo: float = 0.0, hi: Optional[float] = None,
               unit: str = "", title: str = "", times: Optional[Tuple[float, float]] = None, color: Optional[Callable[[float], str]] = None,
               indent: str = "   ", axis_w: int = 7) -> List[Row]:
    """A vertical bar (area) chart ``height`` rows tall with eight sub-levels per row, a y axis on the left and a
    time axis below.  ``values`` are resampled to the chart width; None leaves a gap."""
    chart_w = max(0, width - vlen(indent) - axis_w)
    height = max(0, height)
    vals = resample(values, chart_w)
    # Summary figures describe the source samples, not the bucket averages used to draw the chart.
    present = [v for v in values if v is not None]
    if hi is None:
        hi = max(present) if present else 1.0
        hi = hi * 1.05 if hi > 0 else 1.0
    if hi <= lo:
        hi = lo + 1.0
    levels = g.spark if not g.ascii else LEVELS_ASCII[1:]
    nlev = len(levels)
    rows: List[Row] = []
    if title:
        stats = ""
        if present:
            stats = f"  last {fmt_num(present[-1], unit)}  mean {fmt_num(sum(present) / len(present), unit)}  max {fmt_num(max(present), unit)}  min {fmt_num(min(present), unit)}"
        rows.append([(cut(indent + title, width, g.ascii), "cyan+bold"), (cut(stats, max(0, width - vlen(indent) - vlen(title)), g.ascii), "dim")])
    col = color or (lambda frac: level(frac))
    for r in range(height):
        label = ""
        if r == 0:
            label = fmt_num(hi, unit)
        elif r == height - 1:
            label = fmt_num(lo, unit)
        elif height >= 5 and r == height // 2:
            label = fmt_num((lo + hi) / 2, unit)
        segs: Row = [(indent + pad(label, axis_w - 1, ">") + (g.box[5] if not g.ascii else "|"), "dim")]
        floor = (height - 1 - r) * nlev                      # sub-levels below this row
        for x, v in enumerate(vals):
            guide = g.dot if not g.ascii and r in (0, height // 2) and x % 8 == 0 else " "
            if v is None:
                segs.append((guide, "dim"))
                continue
            frac = (min(max(v, lo), hi) - lo) / (hi - lo)
            lv = int(round(frac * height * nlev))
            fill = min(nlev, max(0, lv - floor))
            segs.append((levels[fill - 1], col(frac)) if fill > 0 else (guide, "dim"))
        rows.append(segs)
    base = indent + " " * (axis_w - 1) + (g.box[4] if not g.ascii else "-") * (chart_w + 1)
    rows.append([(base, "dim")])
    if times:
        rows.append(time_axis(times[0], times[1], chart_w, indent + " " * axis_w))
    return [clip_row(row, width) for row in rows]


def hbar_rows(g: Glyphs, items: Sequence[Tuple[str, float, str]], width: int, indent: str = "   ", label_w: int = 12, unit: str = "",
              hi: Optional[float] = None, color: Optional[Callable[[str, float], str]] = None) -> List[Row]:
    """One row per (label, value, style): ``label  ████░░░░  value``."""
    if not items:
        return []
    hi = hi if hi is not None else max((v for _, v, _ in items), default=1.0)
    hi = hi if hi > 0 else 1.0
    label_w = min(label_w, max(1, (width - vlen(indent) - 10) // 2))
    bar_w = max(0, width - vlen(indent) - label_w - 12)
    rows: List[Row] = []
    for label, v, style in items:
        n = int(round(max(0.0, min(1.0, v / hi)) * bar_w))
        rows.append([(indent + pad(cut(label, label_w, g.ascii), label_w) + " ", ""), (g.full * n, style or (color(label, v) if color else "cyan")),
                     (g.empty * (bar_w - n), "dim"), (f" {fmt_num(v, unit)}", "")])
    return [clip_row(row, width) for row in rows]


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
        return int(round((min(max(t, t0), t1) - t0) / span * (bar_w - 1)))

    for j in jobs:
        state = j.get("state", "")
        style = {"COMPLETED": "green", "RUNNING": "cyan", "PENDING": "yellow"}.get(state, "yellow" if state.startswith("CANCEL") else "red")
        line = [" "] * bar_w
        sub, start, end = j.get("submit"), j.get("start"), j.get("end")
        now = clock.now()
        if sub is not None and (start is not None or state == "PENDING"):
            a, b = col(sub), col(start if start is not None else min(now, t1))
            for x in range(a, b + 1):
                line[x] = g.dot
        if start is not None:
            a, b = col(start), col(end if end is not None else min(now, t1))
            for x in range(a, b + 1):
                line[x] = g.full
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
