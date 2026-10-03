"""A shared terminal palette, with true colour and deliberate portable fallbacks.

Styles remain compact ``+``-joined strings. In addition to the traditional names,
``fg:#rrggbb`` and ``bg:#rrggbb`` let charts colour individual character cells.
The module never emits cursor controls or imports curses.
"""
from __future__ import annotations

import colorsys
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

RGB = tuple[int, int, int]

# Light ink on the user's terminal background. Semantic names let views describe
# meaning rather than bind themselves to one terminal's ANSI colour definitions.
PALETTE = {
    "green": "#6ee7b7", "yellow": "#fbbf24", "red": "#fb7185",
    "cyan": "#67e8f9", "magenta": "#c4b5fd", "blue": "#93c5fd",
    "white": "#e2e8f0", "black": "#0b1020", "muted": "#94a3b8",
    "faint": "#475569", "surface": "#172033", "border": "#334155",
}
ALIASES = {
    "accent": "cyan", "success": "green", "warning": "yellow", "warn": "yellow",
    "danger": "red", "error": "red", "text": "white", "info": "blue",
    "cool": "blue", "hot": "red",
}
CB_MAP = {"green": "blue", "red": "yellow", "yellow": "magenta"}
FLAGS = {"bold": "1", "dim": "2", "rev": "7", "under": "4"}

# Indexed ANSI colours, used both by ANSI output and curses quantisation.
BASIC: tuple[RGB, ...] = ((0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0),
                          (0, 0, 238), (205, 0, 205), (0, 205, 205), (229, 229, 229))
BRIGHT: tuple[RGB, ...] = ((127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0),
                           (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255))
_LEVELS = (0, 95, 135, 175, 215, 255)
INDEXED: tuple[RGB, ...] = BASIC + BRIGHT + tuple((r, g, b) for r in _LEVELS for g in _LEVELS for b in _LEVELS) + tuple((v, v, v) for v in range(8, 239, 10))


def rgb(value: str) -> RGB:
    """Parse exactly a six-digit RGB colour, rejecting terminal control text."""
    if len(value) != 7 or not value.startswith("#"):
        raise ValueError("colour must be #rrggbb")
    try:
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]
    except ValueError as exc:
        raise ValueError("colour must be #rrggbb") from exc


def gradient(start: str, end: str, fraction: float) -> str:
    """Interpolate a bounded RGB gradient for foreground and background cells."""
    a, b = rgb(start), rgb(end)
    t = max(0.0, min(1.0, fraction))
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def colors_disabled() -> bool:
    return bool(os.environ.get("NO_COLOR")) or os.environ.get("TERM", "").lower() == "dumb"


def detect_color_depth() -> int:
    """Return 24, 256, 8 or 0 without probing the terminal or running a command."""
    if colors_disabled():
        return 0
    term = os.environ.get("TERM", "").lower()
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit") or "direct" in term:
        return 24
    return 256 if "256color" in term else 8


color_depth = detect_color_depth


@lru_cache(maxsize=4096)
def color_index(value: RGB, count: int = 256) -> int:
    """Quantise colours, keeping semantic hues in the eight-colour fallback."""
    if count < 256:
        hue, light, saturation = colorsys.rgb_to_hls(*(v / 255 for v in value))
        if saturation <= .25:
            return 0 if light < .3 else 7
        hue *= 360
        return 1 if hue < 30 or hue >= 330 else (3 if hue < 90 else (2 if hue < 165 else (6 if hue < 205 else (4 if hue < 265 else 5))))
    return min(range(len(INDEXED)), key=lambda i: sum((a - b) ** 2 for a, b in zip(value, INDEXED[i])))


def _cb_rgb(value: RGB) -> RGB:
    """Keep luminance structure while moving ambiguous green/red chart gradients."""
    h, light, sat = colorsys.rgb_to_hls(*(v / 255 for v in value))
    if sat < .2:
        return value
    degrees = h * 360
    target = 215 if 75 <= degrees <= 165 else (40 if degrees <= 25 or degrees >= 335 else (275 if 25 < degrees < 75 else degrees))
    return tuple(round(v * 255) for v in colorsys.hls_to_rgb(target / 360, light, sat))  # type: ignore[return-value]


@dataclass(frozen=True)
class Style:
    flags: tuple[str, ...] = ()
    foreground: Optional[RGB] = None
    background: Optional[RGB] = None


@lru_cache(maxsize=4096)
def resolve(style: str, theme: str = "default") -> Style:
    """Resolve semantic, custom and accessibility styles once for both painters."""
    flags: list[str] = []
    foreground = background = None
    plain = theme in ("mono", "reader")
    colored = False
    for token in style.split("+"):
        if token in FLAGS:
            flags.append(token)
            continue
        if token == "sel":
            flags.append("bold")
            if plain:
                flags.append("rev")
            else:
                foreground, background = rgb(PALETTE["white"]), rgb("#1e3a5f")
                colored = True
            continue
        token = ALIASES.get(token, token)
        if plain:
            if token in ("red", "yellow", "magenta"):
                flags.append("bold")
            continue
        background_token = token.startswith("bg:")
        if token.startswith(("fg:", "bg:")):
            value = token[3:]
            try:
                value_rgb = rgb(PALETTE.get(value, value))
            except ValueError:
                continue
            if theme == "cb":
                value_rgb = _cb_rgb(value_rgb)
        else:
            token = CB_MAP.get(token, token) if theme == "cb" else token
            if token not in PALETTE:
                continue
            value_rgb = rgb(PALETTE[token])
        if background_token:
            background = value_rgb
        else:
            foreground = value_rgb
        colored = True
    if theme == "high" and colored:
        flags.append("bold")
    return Style(tuple(dict.fromkeys(flags)), foreground, background)


def ansi_codes(style: str, color_depth: Optional[int] = None, theme: str = "default") -> str:
    """Return SGR codes only; the painter owns escape delimiters and resets.

    A depth of zero disables attributes too. Explicit depths make exported ANSI
    output reproducible; NO_COLOR and TERM=dumb still take precedence.
    """
    depth = detect_color_depth() if color_depth is None else color_depth
    if not depth or colors_disabled():
        return ""
    return _ansi_codes(style, depth, theme)


@lru_cache(maxsize=4096)
def _ansi_codes(style: str, depth: int, theme: str) -> str:
    parsed = resolve(style, theme)
    codes = [FLAGS[flag] for flag in parsed.flags]
    for value, foreground in ((parsed.foreground, True), (parsed.background, False)):
        if value is None:
            continue
        if depth == 24:
            codes.extend(("38" if foreground else "48", "2", *(str(v) for v in value)))
        elif depth >= 256:
            codes.extend(("38" if foreground else "48", "5", str(color_index(value))))
        else:
            codes.append(str((30 if foreground else 40) + color_index(value, 8)))
    return ";".join(codes)
