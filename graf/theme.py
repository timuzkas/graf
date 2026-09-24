from __future__ import annotations

import json
import os
import colorsys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any


CONFIG_PATH = Path.home() / ".config" / "graf" / "graf.json"


@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    graph_background: str
    text: str
    muted: str
    divider: str
    grid: str
    axis: str
    button: str
    button_active: str
    trough: str
    error: str
    hidden_dot: str
    curves: tuple[str, ...]


THEMES: dict[str, Theme] = {
    "light": Theme(
        "light", "#fbfbfa", "#ffffff", "#414141", "#a3a3a3", "#e5e5e3",
        "#eeeeec", "#a9aaa7", "#f3f3f1", "#e8e8e5", "#e7e7e5", "#d9a7a2",
        "#c3c3c0", ("#477fc1", "#d57568", "#4d9b79", "#a377bd", "#cb9a3c", "#4e9ca4"),
    ),
    "dark": Theme(
        "dark", "#242424", "#1c1c1c", "#eeeeec", "#969692", "#3b3b39",
        "#30302e", "#8e8e88", "#353533", "#454541", "#444440", "#a95e5e",
        "#777773", ("#73a7e3", "#e48b7e", "#70c19a", "#b996d2", "#e0b867", "#72c2c7"),
    ),
    "amoled": Theme(
        "amoled", "#000000", "#000000", "#eeeeee", "#858585", "#242424",
        "#181818", "#707070", "#151515", "#292929", "#292929", "#9b5757",
        "#666666", ("#68a5ee", "#ed8174", "#6bc996", "#b98fdb", "#e5b65e", "#6bc5cb"),
    ),
}

COLOR_FIELDS = {field.name for field in fields(Theme)} - {"name", "curves"}


def _valid_color(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if len(value) not in (4, 7) or not value.startswith("#"):
        return False
    return all(character in "0123456789abcdefABCDEF" for character in value[1:])


def _rgb(value: str) -> tuple[float, float, float]:
    value = value[1:]
    if len(value) == 3:
        value = "".join(character * 2 for character in value)
    return tuple(int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))  # type: ignore[return-value]


def _luminance(value: str) -> float:
    channels = []
    for channel in _rgb(value):
        channels.append(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: str, second: str) -> float:
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def generated_curve_palette(background: str, count: int = 6) -> tuple[str, ...]:
    """geenrates a color set for graphs with a contrast treshold"""
    background_luminance = _luminance(background)
    lightnesses = (0.30, 0.37, 0.44, 0.51, 0.58) if background_luminance > 0.5 else (0.57, 0.64, 0.71, 0.78, 0.85)
    hues = [((index * 360 / count) + 7) % 360 for index in range(count)]
    colors: list[str] = []
    for hue in hues:
        candidates: list[tuple[float, str]] = []
        for lightness in lightnesses:
            red, green, blue = colorsys.hls_to_rgb(hue / 360, lightness, 0.62)
            color = "#%02x%02x%02x" % (round(red * 255), round(green * 255), round(blue * 255))
            candidates.append((contrast_ratio(color, background), color))
        readable = [candidate for candidate in candidates if candidate[0] >= 3.0]
        colors.append(max(readable or candidates)[1])
    return tuple(colors)


def config_path() -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    return Path(configured) / "graf" / "graf.json" if configured else CONFIG_PATH


def _with_overrides(base: Theme, overrides: dict[str, Any], name: str | None = None) -> Theme:
    values: dict[str, Any] = {field.name: getattr(base, field.name) for field in fields(Theme)}
    for key in COLOR_FIELDS:
        value = overrides.get(key)
        if _valid_color(value):
            values[key] = value
    curves = overrides.get("curves")
    if isinstance(curves, list) and curves and all(_valid_color(value) for value in curves):
        generated = generated_curve_palette(values["graph_background"], len(curves))
        values["curves"] = tuple(
            value if contrast_ratio(value, values["graph_background"]) >= 3.0 else generated[index]
            for index, value in enumerate(curves)
        )
    else:
        values["curves"] = generated_curve_palette(values["graph_background"])
    values["name"] = name or base.name
    return Theme(**values)


def load_theme(path: Path | None = None) -> Theme:
    """load a named or custom theme, falling back to light."""
    path = path or config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return _with_overrides(THEMES["light"], {}, "light")
    if not isinstance(raw, dict):
        return _with_overrides(THEMES["light"], {}, "light")
    selected = raw.get("theme", "light")
    if isinstance(selected, dict):
        base_name = "light"
        overrides = selected
    else:
        base_name = str(selected).lower()
        overrides = raw.get("colors", {})
    base = THEMES.get(base_name, THEMES["light"])
    if not isinstance(overrides, dict):
        overrides = {}
    return _with_overrides(base, overrides, "custom" if overrides else base.name)


def theme_mtime(path: Path | None = None) -> int | None:
    try:
        return (path or config_path()).stat().st_mtime_ns
    except OSError:
        return None
