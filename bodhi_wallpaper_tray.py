#!/usr/bin/env python3
"""
Bodhi Wallpaper Tray - System Tray Applet for Moksha Desktop
Provides quick wallpaper navigation, slideshow pause/resume, and settings access.
"""

import os
import sys
import subprocess
import json
import gi

gi.require_version("Gtk", "3.0")
try:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as appindicator
    HAVE_APPINDICATOR = True
except Exception:
    HAVE_APPINDICATOR = False

from gi.repository import Gtk, GLib

from bodhi_wallpaper_engine import (
    BodhiWallpaperEngine,
    send_ipc_command
)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
TRAY_ICON_PATH = os.path.join(APP_DIR, "assets", "bodhi-wallpaper-tray.png")
GUI_PATH = os.path.join(APP_DIR, "bodhi_wallpaper_gui.py")


class BodhiWallpaperTray:
    def __init__(self):
        self.engine = BodhiWallpaperEngine()
        self.paused = False

        if HAVE_APPINDICATOR:
            icon_name = TRAY_ICON_PATH if os.path.exists(TRAY_ICON_PATH) else "preferences-desktop-wallpaper"
            self.indicator = appindicator.Indicator.new(
                "bodhi-wallpaper-tray",
                icon_name,
                appindicator.IndicatorCategory.APPLICATION_STATUS
            )
            self.indicator.set_status(appindicator.IndicatorStatus.ACTIVE)
            self.menu = self._create_menu()
            self.indicator.set_menu(self.menu)
        else:
            self.status_icon = Gtk.StatusIcon()
            if os.path.exists(TRAY_ICON_PATH):
                self.status_icon.set_from_file(TRAY_ICON_PATH)
            else:
                self.status_icon.set_from_icon_name("preferences-desktop-wallpaper")
            self.status_icon.set_tooltip_text("Bodhi Wallpaper Changer")
            self.status_icon.connect("popup-menu", self._on_status_icon_popup)
            self.status_icon.connect("activate", self._on_open_gui)
            self.menu = self._create_menu()

        # Update initial status
        self._refresh_status()

    def _create_menu(self):
        menu = Gtk.Menu()

        # Current wallpaper label
        self.item_current = Gtk.MenuItem(label="Current Wallpaper")
        self.item_current.set_sensitive(False)
        menu.append(self.item_current)

        menu.append(Gtk.SeparatorMenuItem())

        # Next Wallpaper
        item_next = Gtk.MenuItem(label="Next Wallpaper")
        item_next.connect("activate", self._on_next)
        menu.append(item_next)

        # Previous Wallpaper
        item_prev = Gtk.MenuItem(label="Previous Wallpaper")
        item_prev.connect("activate", self._on_prev)
        menu.append(item_prev)

        # Random Wallpaper
        item_random = Gtk.MenuItem(label="Random Wallpaper")
        item_random.connect("activate", self._on_random)
        menu.append(item_random)

        # Pause / Resume Slideshow
        self.item_pause = Gtk.MenuItem(label="Pause Slideshow")
        self.item_pause.connect("activate", self._on_toggle_pause)
        menu.append(self.item_pause)

        menu.append(Gtk.SeparatorMenuItem())

        # Open GUI
        item_gui = Gtk.MenuItem(label="Open Wallpaper Changer...")
        item_gui.connect("activate", self._on_open_gui)
        menu.append(item_gui)

        # Preferences
        item_prefs = Gtk.MenuItem(label="Preferences...")
        item_prefs.connect("activate", self._on_open_prefs)
        menu.append(item_prefs)

        menu.append(Gtk.SeparatorMenuItem())

        # Quit
        item_quit = Gtk.MenuItem(label="Quit")
        item_quit.connect("activate", self._on_quit)
        menu.append(item_quit)

        menu.show_all()
        return menu

    def _on_status_icon_popup(self, icon, button, time):
        self._refresh_status()
        self.menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, time)

    def _refresh_status(self):
        resp = send_ipc_command("STATUS")
        if resp:
            try:
                data = json.loads(resp)
                curr = data.get("current", "")
                self.paused = data.get("paused", False)
                name = os.path.splitext(os.path.basename(curr))[0].replace("-", " ") if curr else "None"
                self.item_current.set_label(f"Wallpaper: {name[:24]}")
                self.item_pause.set_label("Resume Slideshow" if self.paused else "Pause Slideshow")
                return
            except Exception:
                pass

        # Fallback to local config if daemon is not running
        self.engine.config = self.engine.load_config()
        curr = self.engine.config.get("current_wallpaper", "")
        name = os.path.splitext(os.path.basename(curr))[0].replace("-", " ") if curr else "None"
        self.item_current.set_label(f"Wallpaper: {name[:24]}")
        self.item_pause.set_label("Start Slideshow" if not self.engine.config.get("auto_change") else "Pause Slideshow")

    def _on_next(self, widget):
        if send_ipc_command("NEXT") is None:
            nxt = self.engine.get_next_wallpaper(forward=True)
            if nxt:
                self.engine.apply_wallpaper(nxt)
        self._refresh_status()

    def _on_prev(self, widget):
        if send_ipc_command("PREV") is None:
            prev = self.engine.get_next_wallpaper(forward=False)
            if prev:
                self.engine.apply_wallpaper(prev)
        self._refresh_status()

    def _on_random(self, widget):
        if send_ipc_command("RANDOM") is None:
            rnd = self.engine.get_random_wallpaper()
            if rnd:
                self.engine.apply_wallpaper(rnd)
        self._refresh_status()

    def _on_toggle_pause(self, widget):
        if send_ipc_command("TOGGLE_PAUSE") is None:
            auto = not self.engine.config.get("auto_change", False)
            self.engine.config["auto_change"] = auto
            self.engine.save_config()
        self._refresh_status()

    def _on_open_gui(self, widget=None):
        cmd = ["python3", GUI_PATH]
        subprocess.Popen(cmd)

    def _on_open_prefs(self, widget):
        cmd = ["python3", GUI_PATH, "--preferences"]
        subprocess.Popen(cmd)

    def _on_quit(self, widget):
        Gtk.main_quit()

    def run(self):
        Gtk.main()


if __name__ == "__main__":
    tray = BodhiWallpaperTray()
    tray.run()
