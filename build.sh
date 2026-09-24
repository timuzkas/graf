#!/usr/bin/env sh
# builds a linux executable
set -eu

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi

.venv/bin/python -m pip install --quiet --upgrade pip pyinstaller
.venv/bin/python -m PyInstaller --noconfirm --clean graf.spec

echo "Built: dist/graf"
