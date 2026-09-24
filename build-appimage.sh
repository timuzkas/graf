#!/usr/bin/env sh
# builds an AppImage.
set -eu

cd "$(dirname "$0")"

appimagetool=${APPIMAGETOOL:-appimagetool}
if ! command -v "$appimagetool" >/dev/null 2>&1 && [ ! -x "$appimagetool" ]; then
    echo "appimagetool is required. Install it or set APPIMAGETOOL to its path." >&2
    exit 1
fi

./build.sh

work_dir=$(mktemp -d "${TMPDIR:-/tmp}/graf-appimage.XXXXXX")
trap 'rm -rf "$work_dir"' EXIT HUP INT TERM
appdir="$work_dir/Graf.AppDir"
mkdir -p "$appdir/usr/bin" "$appdir/usr/share/applications" "$appdir/usr/share/icons/hicolor/256x256/apps"
cp dist/graf "$appdir/usr/bin/graf"
cp packaging/graf.desktop "$appdir/graf.desktop"
cp packaging/graf.desktop "$appdir/usr/share/applications/graf.desktop"
cp packaging/AppRun "$appdir/AppRun"
cp graf.png "$appdir/graf.png"
cp graf.png "$appdir/usr/share/icons/hicolor/256x256/apps/graf.png"
chmod +x "$appdir/AppRun"

output="dist/graf-$(uname -m).AppImage"
"$appimagetool" "$appdir" "$output"
echo "Built: $output"
