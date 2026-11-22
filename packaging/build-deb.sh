#!/bin/sh
# Build a .deb with nothing but dpkg-deb (no debhelper needed).
# For a "proper" Debian source build use: dpkg-buildpackage -us -uc -b
set -eu

cd "$(dirname "$0")/.."
NAME=intel-gpu-top-gui
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/intel_gpu_top_gui/__init__.py)
ROOT=build/deb-root
OUT=dist/${NAME}_${VERSION}_all.deb

# Depends: taken from debian/control so there is a single source of truth.
DEPENDS=$(awk '
    /^Package:/ { inpkg = 1 }
    inpkg && /^Depends:/ { sub(/^Depends:/, ""); collecting = 1 }
    collecting && /^[A-Z][A-Za-z-]*:/ && !/^Depends:/ { collecting = 0 }
    collecting { printf "%s", $0 }
' debian/control | tr -s ' \t' ' ' | sed 's/\${misc:Depends},*//; s/^ *//; s/ *$//')

rm -rf "$ROOT"
DESTDIR="$PWD/$ROOT" PREFIX=/usr packaging/install.sh >/dev/null

install -Dm 644 debian/copyright "$ROOT/usr/share/doc/$NAME/copyright"
gzip -9n -c debian/changelog > "$ROOT/usr/share/doc/$NAME/changelog.gz"
chmod 644 "$ROOT/usr/share/doc/$NAME/changelog.gz"

SIZE=$(du -sk "$ROOT/usr" | cut -f1)
mkdir -p "$ROOT/DEBIAN"
cat > "$ROOT/DEBIAN/control" <<CONTROL
Package: $NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Installed-Size: $SIZE
Maintainer: intel-gpu-top-gui maintainers <maintainers@example.invalid>
Depends: $DEPENDS
Description: graphical time-series monitor for Intel GPUs
 A GTK 4 / libadwaita front-end for intel_gpu_top, in the style of GNOME
 System Monitor. It plots engine utilisation, GPU frequency, power draw,
 RC6 residency, memory bandwidth and interrupts as scrolling graphs and
 lists the processes that use the GPU.
CONTROL

mkdir -p dist
dpkg-deb --root-owner-group --build "$ROOT" "$OUT" >/dev/null
echo "Built $OUT"
echo "Install with:  sudo apt install ./$OUT"
