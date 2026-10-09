"""Bounded native chart rasters; controls, geometry and source age stay live."""
from __future__ import annotations

from collections import OrderedDict
from array import array
import copy
import os
import time

from . import charts, layout as L

MAX_ENTRIES = 64
MAX_SERIES_POINTS = 64000
MAX_POINTS = 512000
MAX_CELLS = 65536
_UNCACHEABLE = object()


def coalesce_row(row):
    """Join adjacent equal styles without changing any glyph or style byte."""
    result, fragments, previous = [], [], None
    for text, style in row:
        if (fragments and type(style) is str and type(previous) is str
                and style == previous):
            fragments.append(text)
        else:
            if fragments:
                result.append(("".join(fragments), previous))
            fragments, previous = [text], style
    if fragments:
        result.append(("".join(fragments), previous))
    return result


def _freeze(value, depth=0):
    """Keep exact numeric representations and detect in-place corrections."""
    if depth > 4:
        return _UNCACHEABLE
    kind = type(value)
    if kind in (type(None), bool, int, str):
        return kind, value
    if kind is float:
        return kind, value.hex()
    if kind in (list, tuple) and len(value) <= MAX_SERIES_POINTS:
        # Native series normally contain plain floats. A C-level packed copy
        # retains every bit (including signed zero and NaN) without allocating
        # a Python type/value tuple for each point on every maintenance frame.
        if value and all(type(item) is float for item in value):
            return kind, float, array("d", value).tobytes()
        if value and all(type(item) is int for item in value):
            return kind, int, tuple(value)
        parts = tuple(_freeze(item, depth + 1) for item in value)
        return _UNCACHEABLE if any(item is _UNCACHEABLE for item in parts) else (kind, parts)
    if kind is dict and len(value) <= 64 and all(type(key) is str for key in value):
        parts = tuple((key, _freeze(item, depth + 1)) for key, item in sorted(value.items()))
        return _UNCACHEABLE if any(item is _UNCACHEABLE for _, item in parts) else (kind, parts)
    return _UNCACHEABLE


class MetricRasterCache:
    def __init__(self):
        self.entries = OrderedDict()
        self.points = self.cells = 0

    def render(self, glyphs, values, width, height, *, filled=False, theme="", compact_rows=False, **options):
        painter = charts.vbar_chart if filled else charts.braille_chart
        metadata = {}
        # Unknown extension options use the original painter. The cache must
        # never impose a new limit on data that a renderer already supports.
        data = _freeze(values)
        settings = _freeze(options)
        zone = (os.environ.get("TZ"), time.tzname, time.timezone, time.daylight)
        key = (filled, compact_rows, width, height, glyphs.ascii, glyphs.spark, glyphs.box,
               glyphs.full, glyphs.dot, glyphs.rule, theme, zone, data, settings)
        cacheable = data is not _UNCACHEABLE and settings is not _UNCACHEABLE
        entry = self.entries.get(key) if cacheable else None
        if entry is not None:
            self.entries.move_to_end(key)
            return [list(row) for row in entry["rows"]], copy.deepcopy(entry["metadata"])
        rows = painter(glyphs, values, width, height, metadata=metadata, **options)
        if compact_rows:
            rows = [coalesce_row(row) for row in rows]
        if not cacheable:
            return rows, metadata
        count = len(values) + len(options.get("sample_times") or ())
        cells = sum(L.vlen(L.row_text(row)) for row in rows)
        if cacheable and count <= MAX_POINTS and cells <= MAX_CELLS:
            self.entries[key] = {"rows": tuple(tuple(row) for row in rows),
                                 "metadata": copy.deepcopy(metadata), "points": count, "cells": cells}
            self.points += count
            self.cells += cells
            while (len(self.entries) > MAX_ENTRIES or self.points > MAX_POINTS or self.cells > MAX_CELLS):
                _, old = self.entries.popitem(last=False)
                self.points -= old["points"]
                self.cells -= old["cells"]
        return rows, metadata
