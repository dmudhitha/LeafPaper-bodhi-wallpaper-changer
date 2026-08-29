#!/usr/bin/env bash
# ==============================================================================
# Bodhi Linux Wallpaper Changer - Uninstallation Script
# ==============================================================================

set -e

echo "=== Uninstalling Bodhi Wallpaper Changer ==="

# 1. Stop running daemon and tray
echo "-> Stopping active daemon and tray processes..."
python3 -c "
from bodhi_wallpaper_engine import send_ipc_command
send_ipc_command('STOP')
" 2>/dev/null || true
pkill -f "bodhi_wallpaper_daemon.py" || true
pkill -f "bodhi_wallpaper_tray.py" || true

# 2. Remove user files
echo "-> Removing user installations..."
rm -f "$HOME/.local/bin/bodhi-wallpaper"
rm -rf "$HOME/.local/share/bodhi-wallpaper"
rm -f "$HOME/.local/share/applications/bodhi-wallpaper.desktop"
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/bodhi-wallpaper.svg"
rm -f "$HOME/.local/share/icons/hicolor/256x256/apps/bodhi-wallpaper.png"
rm -f "$HOME/.config/autostart/bodhi-wallpaper-autostart.desktop"
rm -f "/tmp/bodhi-wallpaper-*.sock"
rm -f "/tmp/bodhi-wallpaper-daemon-*.lock"

# 3. Remove system files if run as root
if [ "$(id -u)" -eq 0 ]; then
    echo "-> Removing system-wide installations..."
    rm -f "/usr/bin/bodhi-wallpaper"
    rm -rf "/usr/share/bodhi-wallpaper"
    rm -f "/usr/share/applications/bodhi-wallpaper.desktop"
    rm -f "/usr/share/icons/hicolor/scalable/apps/bodhi-wallpaper.svg"
    rm -f "/usr/share/icons/hicolor/256x256/apps/bodhi-wallpaper.png"
    rm -f "/usr/share/pixmaps/bodhi-wallpaper.png"
fi

# 4. Update caches
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

echo ""
echo "=================================================="
echo "✔ Bodhi Wallpaper Changer removed successfully."
echo "Config files retained in ~/.config/bodhi-wallpaper"
echo "(Delete ~/.config/bodhi-wallpaper manually to wipe all settings)"
echo "=================================================="
