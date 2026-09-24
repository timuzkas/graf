<table>
  <tr>
    <td><img src="graf.png" alt="graf logo" width="72"></td>
    <td><h1>graf</h1></td>
  </tr>
</table>

A lightweight graphing calculator built with Python and Tkinter.

[Wiki](https://github.com/timuzkas/graf/wiki)

## Dependencies

- Python 3+
- Tkinter and the Python standard library
- ( PyInstaller for standalone builds )

## Build

```text
graf.spec           PyInstaller build definition
build.sh            Linux build script
build.ps1           Windows build script
```

## Otter math engine

Install the engine separately with `python -m pip install ./otter`, then import it from `otter`:

```python
from otter import parse_relation

curve = parse_relation("y = x^2")
print(curve.evaluate(3, 0))  # 9.0
```

## Configuration

Graf reads `~/.config/graf/graf.json` on Linux and macOS. Set `XDG_CONFIG_HOME` to use a different config directory. The file selects a built-in theme (`light`, `dark`, or `amoled`) and can override colors:

```json
{
  "theme": "dark",
  "colors": {
    "graph_background": "#101216",
    "grid": "#252a32",
    "axis": "#727b89",
    "text": "#e8edf2",
    "muted": "#8f9aa8",
    "curves": ["#72a7ff", "#ff8f82", "#72d39a"]
  }
}
```

Projects use a JSON `.graf.json` files to persist them. They store expression rows, row visibility, slider values and ranges, row order, and the graph viewport.
