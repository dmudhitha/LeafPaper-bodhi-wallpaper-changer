#!/usr/bin/env bash
# ==============================================================================
# Bodhi Linux Wallpaper Changer - Debian Package Builder
# ==============================================================================

set -e

PKG_NAME="bodhi-wallpaper-changer"
VERSION="1.0"
RELEASE="1"
ARCH="all"
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$BASE_DIR/build-deb/${PKG_NAME}_${VERSION}-${RELEASE}_${ARCH}"
OUTPUT_DEB="$BASE_DIR/${PKG_NAME}_${VERSION}-${RELEASE}_${ARCH}.deb"

echo "=== Starting Debian Package Build for ${PKG_NAME} ==="

# 1. Clean previous build directory
rm -rf "$BASE_DIR/build-deb"
mkdir -p "$BUILD_DIR/DEBIAN"
mkdir -p "$BUILD_DIR/usr/bin"
mkdir -p "$BUILD_DIR/usr/share/bodhi-wallpaper/assets"
mkdir -p "$BUILD_DIR/usr/share/applications"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$BUILD_DIR/usr/share/pixmaps"

# 2. Copy scripts to share directory
echo "-> Copying application files..."
cp "$BASE_DIR/bodhi_wallpaper_engine.py" "$BUILD_DIR/usr/share/bodhi-wallpaper/"
cp "$BASE_DIR/bodhi_wallpaper_online.py" "$BUILD_DIR/usr/share/bodhi-wallpaper/"
cp "$BASE_DIR/bodhi_wallpaper_gui.py" "$BUILD_DIR/usr/share/bodhi-wallpaper/"
cp "$BASE_DIR/bodhi_wallpaper_daemon.py" "$BUILD_DIR/usr/share/bodhi-wallpaper/"
cp "$BASE_DIR/bodhi_wallpaper_tray.py" "$BUILD_DIR/usr/share/bodhi-wallpaper/"
cp "$BASE_DIR/bodhi-wallpaper" "$BUILD_DIR/usr/share/bodhi-wallpaper/"
cp -r "$BASE_DIR/assets/"* "$BUILD_DIR/usr/share/bodhi-wallpaper/assets/"

chmod 755 "$BUILD_DIR/usr/share/bodhi-wallpaper"/*.py
chmod 755 "$BUILD_DIR/usr/share/bodhi-wallpaper/bodhi-wallpaper"
chmod 644 "$BUILD_DIR/usr/share/bodhi-wallpaper/assets/"*

# 3. Create launcher in /usr/bin
echo "-> Generating /usr/bin/bodhi-wallpaper launcher..."
sed "s|APP_DIR = .*|APP_DIR = '/usr/share/bodhi-wallpaper'|g" "$BASE_DIR/bodhi-wallpaper" > "$BUILD_DIR/usr/bin/bodhi-wallpaper"
chmod 755 "$BUILD_DIR/usr/bin/bodhi-wallpaper"

# 4. Copy Desktop launcher
echo "-> Installing desktop launcher..."
cp "$BASE_DIR/bodhi-wallpaper.desktop" "$BUILD_DIR/usr/share/applications/"
chmod 644 "$BUILD_DIR/usr/share/applications/bodhi-wallpaper.desktop"

# 5. Copy Icons
echo "-> Installing icon assets..."
if [ -f "$BASE_DIR/assets/bodhi-wallpaper.svg" ]; then
    cp "$BASE_DIR/assets/bodhi-wallpaper.svg" "$BUILD_DIR/usr/share/icons/hicolor/scalable/apps/bodhi-wallpaper.svg"
fi
if [ -f "$BASE_DIR/assets/bodhi-wallpaper.png" ]; then
    cp "$BASE_DIR/assets/bodhi-wallpaper.png" "$BUILD_DIR/usr/share/icons/hicolor/256x256/apps/bodhi-wallpaper.png"
    cp "$BASE_DIR/assets/bodhi-wallpaper.png" "$BUILD_DIR/usr/share/pixmaps/bodhi-wallpaper.png"
fi

# 6. Generate DEBIAN/control
echo "-> Creating DEBIAN/control file..."
cat <<EOF > "$BUILD_DIR/DEBIAN/control"
Package: $PKG_NAME
Version: $VERSION-$RELEASE
Section: graphics
Priority: optional
Architecture: $ARCH
Depends: python3, python3-gi, python3-pil, gir1.2-gtk-3.0, gir1.2-notify-0.7, libnotify-bin
Recommends: gir1.2-appindicator3-0.1, moksha | enlightenment
Maintainer: Mudhitha <mudhitha@bodhilinux.com>
Description: LeafPaper - Bodhi Wallpaper Changer
 Modern GTK3 wallpaper manager, multi-source online downloader, and automated
 rotator designed specifically for Bodhi Linux and the Moksha desktop environment.
 Seamlessly supports Moksha EDJ themes, 6 online wallpaper sources (Wallhaven,
 Bing Daily, NASA APOD, Picsum 5K, Wikimedia 8K, Openverse), system tray applet,
 and multi-monitor configurations.
EOF

# 7. Generate DEBIAN/postinst
echo "-> Creating DEBIAN/postinst..."
cat <<EOF > "$BUILD_DIR/DEBIAN/postinst"
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
EOF
chmod 755 "$BUILD_DIR/DEBIAN/postinst"

# 8. Generate DEBIAN/prerm
echo "-> Creating DEBIAN/prerm..."
cat <<EOF > "$BUILD_DIR/DEBIAN/prerm"
#!/bin/sh
set -e
pkill -f "bodhi_wallpaper_daemon.py" || true
pkill -f "bodhi_wallpaper_tray.py" || true
exit 0
EOF
chmod 755 "$BUILD_DIR/DEBIAN/prerm"

# 9. Build Debian package using dpkg-deb
echo "-> Compiling files into .deb package with dpkg-deb..."
dpkg-deb --build "$BUILD_DIR" "$OUTPUT_DEB"

# 10. Clean up temporary build tree
rm -rf "$BASE_DIR/build-deb"

echo ""
echo "=================================================="
echo "✔ DEB Package built successfully!"
echo "Package File: $OUTPUT_DEB"
echo "Install via:  sudo dpkg -i $(basename "$OUTPUT_DEB")"
echo "=================================================="
