#!/usr/bin/env bash
# ==============================================================================
# Bodhi Linux Wallpaper Changer - Installation Script
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if installing system-wide or user-local
if [ "$1" = "--system" ] || [ "$(id -u)" -eq 0 ]; then
    INSTALL_MODE="system"
    BIN_DIR="/usr/bin"
    SHARE_DIR="/usr/share/bodhi-wallpaper"
    APP_DIR="/usr/share/applications"
    ICON_DIR="/usr/share/icons/hicolor"
    PIXMAP_DIR="/usr/share/pixmaps"
else
    INSTALL_MODE="user"
    BIN_DIR="$HOME/.local/bin"
    SHARE_DIR="$HOME/.local/share/bodhi-wallpaper"
    APP_DIR="$HOME/.local/share/applications"
    ICON_DIR="$HOME/.local/share/icons/hicolor"
    PIXMAP_DIR="$HOME/.local/share/pixmaps"
fi

echo "=== Installing Bodhi Wallpaper Changer (${INSTALL_MODE} mode) ==="

# 1. Create target directories
mkdir -p "$BIN_DIR"
mkdir -p "$SHARE_DIR/assets"
mkdir -p "$APP_DIR"
mkdir -p "$ICON_DIR/scalable/apps"
mkdir -p "$ICON_DIR/256x256/apps"
mkdir -p "$PIXMAP_DIR"

# 2. Copy application scripts to share directory
echo "-> Copying core modules..."
cp "$SCRIPT_DIR/bodhi_wallpaper_engine.py" "$SHARE_DIR/bodhi_wallpaper_engine.py"
cp "$SCRIPT_DIR/bodhi_wallpaper_online.py" "$SHARE_DIR/bodhi_wallpaper_online.py"
cp "$SCRIPT_DIR/bodhi_wallpaper_gui.py" "$SHARE_DIR/bodhi_wallpaper_gui.py"
cp "$SCRIPT_DIR/bodhi_wallpaper_daemon.py" "$SHARE_DIR/bodhi_wallpaper_daemon.py"
cp "$SCRIPT_DIR/bodhi_wallpaper_tray.py" "$SHARE_DIR/bodhi_wallpaper_tray.py"
chmod 755 "$SHARE_DIR"/*.py

# 3. Copy assets
echo "-> Copying visual assets..."
cp -r "$SCRIPT_DIR/assets/"* "$SHARE_DIR/assets/"
chmod -R 644 "$SHARE_DIR/assets/"*

# 4. Install binary launcher
echo "-> Installing executable launcher..."
cat <<EOF > "$BIN_DIR/bodhi-wallpaper"
#!/usr/bin/env bash
export PYTHONPATH="$SHARE_DIR:\$PYTHONPATH"
exec python3 "$SHARE_DIR/bodhi_wallpaper_gui.py" "\$@"
EOF

# If CLI arguments require daemon or helper scripts, handle wrapper:
cat <<'EOF' > "$BIN_DIR/bodhi-wallpaper"
#!/usr/bin/env python3
import os
import sys
SHARE_DIR = "__SHARE_DIR__"
if os.path.exists(SHARE_DIR):
    sys.path.insert(0, SHARE_DIR)
    launcher = os.path.join(SHARE_DIR, "bodhi-wallpaper")
    if not os.path.exists(launcher):
        import bodhi_wallpaper_engine
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bodhi-wallpaper import main
EOF
# Actually simpler and cleaner: copy main bodhi-wallpaper directly and replace APP_DIR with SHARE_DIR!
sed "s|APP_DIR = .*|APP_DIR = '$SHARE_DIR'|g" "$SCRIPT_DIR/bodhi-wallpaper" > "$BIN_DIR/bodhi-wallpaper"
chmod 755 "$BIN_DIR/bodhi-wallpaper"

# Also copy bodhi-wallpaper itself to SHARE_DIR
cp "$SCRIPT_DIR/bodhi-wallpaper" "$SHARE_DIR/bodhi-wallpaper"
chmod 755 "$SHARE_DIR/bodhi-wallpaper"

# 5. Install Desktop entry
echo "-> Installing desktop application shortcut..."
sed "s|Exec=.*|Exec=$BIN_DIR/bodhi-wallpaper --gui|g" "$SCRIPT_DIR/bodhi-wallpaper.desktop" > "$APP_DIR/bodhi-wallpaper.desktop"
chmod 644 "$APP_DIR/bodhi-wallpaper.desktop"

# 5b. Install shortcut on ~/Desktop if present
if [ -d "$HOME/Desktop" ] && [ "$INSTALL_MODE" = "user" ]; then
    echo "-> Creating desktop shortcut on ~/Desktop..."
    cat <<EOF > "$HOME/Desktop/bodhi-wallpaper.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=Bodhi Wallpaper Changer
GenericName=Wallpaper Manager
Comment=Change desktop wallpapers, download online wallpapers, and configure automated slideshows
Exec=$BIN_DIR/bodhi-wallpaper --gui
Icon=$SHARE_DIR/assets/bodhi-wallpaper.png
Path=$SCRIPT_DIR
Terminal=false
Categories=Settings;DesktopSettings;GTK;Graphics;Utility;
StartupNotify=true
Actions=Next;Random;BingDaily;Preferences;

[Desktop Action Next]
Name=Next Wallpaper
Exec=$BIN_DIR/bodhi-wallpaper --next

[Desktop Action Random]
Name=Random Wallpaper
Exec=$BIN_DIR/bodhi-wallpaper --random

[Desktop Action BingDaily]
Name=Today's Bing Daily
Exec=$BIN_DIR/bodhi-wallpaper --bing-daily

[Desktop Action Preferences]
Name=Slideshow Preferences
Exec=$BIN_DIR/bodhi-wallpaper --preferences
EOF
    chmod +x "$HOME/Desktop/bodhi-wallpaper.desktop"
    gio set "$HOME/Desktop/bodhi-wallpaper.desktop" metadata::trusted true 2>/dev/null || true
fi

# 6. Install Icons
echo "-> Installing icons..."
if [ -f "$SCRIPT_DIR/assets/bodhi-wallpaper.svg" ]; then
    cp "$SCRIPT_DIR/assets/bodhi-wallpaper.svg" "$ICON_DIR/scalable/apps/bodhi-wallpaper.svg"
fi
if [ -f "$SCRIPT_DIR/assets/bodhi-wallpaper.png" ]; then
    cp "$SCRIPT_DIR/assets/bodhi-wallpaper.png" "$ICON_DIR/256x256/apps/bodhi-wallpaper.png"
    cp "$SCRIPT_DIR/assets/bodhi-wallpaper.png" "$PIXMAP_DIR/bodhi-wallpaper.png"
fi

# 7. Update icon and desktop databases if available
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$ICON_DIR" 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_DIR" 2>/dev/null || true
fi

echo ""
echo "=================================================="
echo "✔ Bodhi Wallpaper Changer installed successfully!"
echo "Binary: $BIN_DIR/bodhi-wallpaper"
echo "Launch GUI: bodhi-wallpaper"
echo "Next Wallpaper: bodhi-wallpaper --next"
echo "Background Daemon: bodhi-wallpaper --daemon"
echo "=================================================="
