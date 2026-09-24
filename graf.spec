# -*- mode: python ; coding: utf-8 -*-
"""pyinstaller build definition for graf."""

import os

from PyInstaller.depend import bindepend


def _import_closure(paths):
    """shared-library dependencies of the given files."""
    seen = set()
    stack = [path for path in paths if path]
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        for dependency in bindepend.get_imports(path) or []:
            resolved = dependency[1] if isinstance(dependency, tuple) else dependency
            if resolved and os.path.isabs(resolved) and resolved not in seen:
                stack.append(resolved)
    return seen


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("graf.png", ".")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests"],
    noarchive=False,
    optimize=0,
)

# drop graphviz plugins bundled in tcl's data dir; graf never loads them and
# their deps drag in ~16 MB. keep what tk/tcl/cpython actually need.
def _is_graphviz(entry):
    return "graphviz" in entry[0].replace("\\", "/")


_graphviz = [entry for entry in a.binaries + a.datas if _is_graphviz(entry)]
if _graphviz:
    _graphviz_closure = _import_closure([entry[1] for entry in _graphviz])
    _core_closure = _import_closure([
        entry[1] for entry in a.binaries
        if not _is_graphviz(entry)
        and (entry[0].startswith(("libtk", "libtcl", "libpython")) or "lib-dynload" in entry[0])
    ])
    a.binaries = [
        entry for entry in a.binaries
        if not _is_graphviz(entry)
        and (entry[1] not in _graphviz_closure or entry[1] in _core_closure)
    ]
    a.datas = [entry for entry in a.datas if not _is_graphviz(entry)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="graf",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
