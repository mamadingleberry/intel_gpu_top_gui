#!/bin/sh
# Install (or uninstall) intel-gpu-top-gui without pip or make.
#
#   packaging/install.sh                       # -> /usr/local (needs sudo)
#   PREFIX=/usr packaging/install.sh           # -> /usr
#   DESTDIR=/tmp/root PREFIX=/usr packaging/install.sh   # staged (packaging)
#   packaging/install.sh --uninstall
set -eu

refresh_caches() {
    [ -z "$DESTDIR" ] || return 0
    # Only refresh an existing icon cache: creating one in e.g. ~/.local
    # would hide icons added there later.
    if [ -f "$SHARE/icons/hicolor/icon-theme.cache" ]; then
        gtk-update-icon-cache -qf "$SHARE/icons/hicolor" 2>/dev/null || true
    fi
    update-desktop-database -q "$SHARE/applications" 2>/dev/null || true
}

cd "$(dirname "$0")/.."
NAME=intel-gpu-top-gui
APP_ID=io.github.IntelGpuTopGui
PREFIX=${PREFIX:-/usr/local}
DESTDIR=${DESTDIR:-}
SHARE="$PREFIX/share"
APPDIR="$SHARE/$NAME"
D="$DESTDIR"

if [ "${1:-}" = "--uninstall" ]; then
    rm -rf "$D$APPDIR"
    rm -f "$D$PREFIX/bin/$NAME" \
          "$D$SHARE/applications/$APP_ID.desktop" \
          "$D$SHARE/icons/hicolor/scalable/apps/$APP_ID.svg" \
          "$D$SHARE"/icons/hicolor/*/apps/$APP_ID.png \
          "$D$SHARE/metainfo/$APP_ID.metainfo.xml" \
          "$D$SHARE/polkit-1/actions/$APP_ID.policy"
    refresh_caches
    echo "Uninstalled $NAME from $D$PREFIX"
    exit 0
fi

install -d "$D$APPDIR/intel_gpu_top_gui"
install -m 644 src/intel_gpu_top_gui/*.py "$D$APPDIR/intel_gpu_top_gui/"

install -d "$D$PREFIX/bin"
cat > "$D$PREFIX/bin/$NAME" <<LAUNCHER
#!/usr/bin/python3
import sys
sys.path.insert(0, "$APPDIR")
from intel_gpu_top_gui.app import main
sys.exit(main())
LAUNCHER
chmod 755 "$D$PREFIX/bin/$NAME"

install -Dm 644 data/$APP_ID.desktop      "$D$SHARE/applications/$APP_ID.desktop"
install -Dm 644 data/$APP_ID.svg          "$D$SHARE/icons/hicolor/scalable/apps/$APP_ID.svg"
for png in data/icons/*/$APP_ID.png; do
    size=$(basename "$(dirname "$png")")
    install -Dm 644 "$png" "$D$SHARE/icons/hicolor/$size/apps/$APP_ID.png"
done
install -Dm 644 data/$APP_ID.metainfo.xml "$D$SHARE/metainfo/$APP_ID.metainfo.xml"
# polkit only reads /usr/share/polkit-1/actions; harmless elsewhere.
install -Dm 644 data/$APP_ID.policy       "$D$SHARE/polkit-1/actions/$APP_ID.policy"

refresh_caches
echo "Installed $NAME to $D$PREFIX"
