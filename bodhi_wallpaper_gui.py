#!/usr/bin/env python3
"""
Bodhi Wallpaper Changer - Graphical User Interface
Modern GTK3 desktop interface tailored for Bodhi Linux / Moksha Desktop.
Features:
- Integrated System Tray Icon with quick actions (Next, Prev, Random, Bing Daily, Preferences, Quit)
- Minimize-to-tray on window close
- Responsive multi-pane layout with collapsible sidebar and preview inspector (Gtk.Paned)
- Debounced, non-blocking search and asynchronous thumbnail loading with cancellation tokens
- Internet wallpaper downloader (Wallhaven, Bing Daily, NASA Space APOD)
- Multi-category filtering and scaling configuration
- Keyboard shortcuts and low-resolution display adaptability (down to 660x440)
"""

import os
import sys
import time
import shutil
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urlparse

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")

try:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3
    HAVE_APPINDICATOR = True
except Exception:
    HAVE_APPINDICATOR = False

from gi.repository import Gtk, Gdk, GdkPixbuf, GLib

from bodhi_wallpaper_engine import (
    BodhiWallpaperEngine,
    CONFIG_DIR,
    send_ipc_command,
    is_daemon_running,
    start_daemon,
    stop_daemon,
    restart_daemon,
    get_launcher_path
)
from bodhi_wallpaper_online import (
    OnlineWallpaperManager,
    CATEGORY_PRESETS,
    DOWNLOADS_DIR
)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ICON_PATH = os.path.join(APP_DIR, "assets", "bodhi-wallpaper.png")
TRAY_ICON_PATH = os.path.join(APP_DIR, "assets", "bodhi-wallpaper-tray.png")
AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, "bodhi-wallpaper-autostart.desktop")


def _has_status_notifier_watcher():
    """Checks if a modern StatusNotifierWatcher daemon is running on DBus."""
    try:
        cmd = ["dbus-send", "--session", "--dest=org.freedesktop.DBus", "--type=method_call",
               "--print-reply", "/org/freedesktop/DBus", "org.freedesktop.DBus.ListNames"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=1)
        return "org.kde.StatusNotifierWatcher" in res.stdout
    except Exception:
        return False


# Custom CSS for Bodhi Moksha aesthetic (Leaf Green accents)
CUSTOM_CSS = b"""
/* Bodhi Moksha Palette & Elements */
@define-color bodhi_green #779933;
@define-color bodhi_green_hover #8cb33e;
@define-color bodhi_green_active #5c7c22;
@define-color card_bg rgba(128, 128, 128, 0.08);
@define-color card_border rgba(128, 128, 128, 0.2);

.bodhi-apply-btn {
    background-color: @bodhi_green;
    color: #ffffff;
    font-weight: bold;
    border-radius: 6px;
    padding: 6px 14px;
    border: none;
    transition: background-color 150ms ease;
}
.bodhi-apply-btn:hover {
    background-color: @bodhi_green_hover;
}
.bodhi-apply-btn:active {
    background-color: @bodhi_green_active;
}

.wallpaper-card {
    background: @card_bg;
    border: 1px solid @card_border;
    border-radius: 8px;
    padding: 4px;
    margin: 3px;
    transition: all 150ms ease;
}
.wallpaper-card:hover {
    border-color: @bodhi_green;
    background: rgba(119, 153, 51, 0.12);
}
.wallpaper-card:selected {
    border-color: @bodhi_green;
    background: rgba(119, 153, 51, 0.25);
}

.badge-pill {
    background-color: rgba(0, 0, 0, 0.68);
    color: #f7fafc;
    border-radius: 4px;
    padding: 2px 5px;
    font-size: 8.5px;
    font-weight: bold;
}

.badge-provider {
    background-color: #276749;
    color: #ffffff;
    border-radius: 4px;
    padding: 2px 5px;
    font-size: 8.5px;
    font-weight: bold;
}

.sidebar-category {
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 12.5px;
}
.sidebar-category:selected {
    background-color: rgba(119, 153, 51, 0.25);
    color: inherit;
    font-weight: bold;
}

.preview-box {
    padding: 10px;
    background: rgba(0, 0, 0, 0.02);
}

.stat-label {
    font-size: 11px;
    opacity: 0.7;
}
.stat-value {
    font-size: 11.5px;
    font-weight: bold;
}

paned separator {
    background-color: rgba(128, 128, 128, 0.2);
    min-width: 2px;
}
paned separator:hover {
    background-color: @bodhi_green;
}
"""


class WallpaperCard(Gtk.FlowBoxChild):
    """FlowBox card widget displaying local wallpaper thumbnail, title, and badges."""
    def __init__(self, wallpaper_path, engine):
        super().__init__()
        self.wallpaper_path = wallpaper_path
        self.engine = engine
        self.filename = os.path.basename(wallpaper_path)
        self.clean_name = os.path.splitext(self.filename)[0].replace("-", " ").replace("_", " ")
        self.is_online = False

        self.get_style_context().add_class("wallpaper-card")
        self.set_tooltip_text(f"{self.clean_name}\n{wallpaper_path}")

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.box.set_size_request(185, 145)
        self.add(self.box)

        self.overlay = Gtk.Overlay()
        self.box.pack_start(self.overlay, False, False, 0)

        self.image = Gtk.Image.new_from_icon_name("image-loading", Gtk.IconSize.DIALOG)
        self.image.set_size_request(175, 110)
        self.overlay.add(self.image)

        # Format Badge (bottom right)
        ext = os.path.splitext(self.filename)[1].lower().lstrip(".")
        self.badge = Gtk.Label(label=ext.upper())
        self.badge.get_style_context().add_class("badge-pill")
        self.badge.set_halign(Gtk.Align.END)
        self.badge.set_valign(Gtk.Align.END)
        self.badge.set_margin_end(5)
        self.badge.set_margin_bottom(5)
        self.overlay.add_overlay(self.badge)

        # Active checkmark (top left, if current)
        self.active_badge = Gtk.Image.new_from_icon_name("emblem-default", Gtk.IconSize.MENU)
        self.active_badge.set_halign(Gtk.Align.START)
        self.active_badge.set_valign(Gtk.Align.START)
        self.active_badge.set_margin_start(5)
        self.active_badge.set_margin_top(5)
        self.overlay.add_overlay(self.active_badge)
        self.update_active_status()

        # Title Label
        self.lbl_title = Gtk.Label(label=self.clean_name)
        self.lbl_title.set_ellipsize(3)
        self.lbl_title.set_max_width_chars(20)
        self.lbl_title.set_halign(Gtk.Align.CENTER)
        self.box.pack_start(self.lbl_title, True, True, 2)

    def set_pixbuf(self, pixbuf):
        self.image.set_from_pixbuf(pixbuf)

    def update_active_status(self):
        curr = self.engine.config.get("current_wallpaper", "")
        is_active = os.path.abspath(curr) == os.path.abspath(self.wallpaper_path)
        self.active_badge.set_visible(is_active)


class OnlineWallpaperCard(Gtk.FlowBoxChild):
    """FlowBox card widget for online downloadable wallpapers."""
    def __init__(self, item, manager):
        super().__init__()
        self.item = item
        self.manager = manager
        self.is_online = True

        self.get_style_context().add_class("wallpaper-card")
        self.set_tooltip_text(f"{item['title']}\nProvider: {item['provider']} | {item['resolution']}")

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.box.set_size_request(185, 145)
        self.add(self.box)

        self.overlay = Gtk.Overlay()
        self.box.pack_start(self.overlay, False, False, 0)

        self.image = Gtk.Image.new_from_icon_name("image-loading", Gtk.IconSize.DIALOG)
        self.image.set_size_request(175, 110)
        self.overlay.add(self.image)

        # Resolution Badge (bottom right)
        res_text = item.get("resolution", "HD").split("x")[0]
        if "3840" in item.get("resolution", "") or "4K" in item.get("resolution", ""):
            res_text = "4K"
        elif "2560" in item.get("resolution", ""):
            res_text = "2K"
        elif "1920" in item.get("resolution", ""):
            res_text = "1080p"

        self.badge_res = Gtk.Label(label=res_text)
        self.badge_res.get_style_context().add_class("badge-pill")
        self.badge_res.set_halign(Gtk.Align.END)
        self.badge_res.set_valign(Gtk.Align.END)
        self.badge_res.set_margin_end(5)
        self.badge_res.set_margin_bottom(5)
        self.overlay.add_overlay(self.badge_res)

        # Provider Badge (top left)
        prov_lbl = Gtk.Label(label=item.get("provider", "Online"))
        prov_lbl.get_style_context().add_class("badge-provider")
        prov_lbl.set_halign(Gtk.Align.START)
        prov_lbl.set_valign(Gtk.Align.START)
        prov_lbl.set_margin_start(5)
        prov_lbl.set_margin_top(5)
        self.overlay.add_overlay(prov_lbl)

        # Title Label
        self.lbl_title = Gtk.Label(label=item["title"])
        self.lbl_title.set_ellipsize(3)
        self.lbl_title.set_max_width_chars(20)
        self.lbl_title.set_halign(Gtk.Align.CENTER)
        self.box.pack_start(self.lbl_title, True, True, 2)

    def set_pixbuf(self, pixbuf):
        self.image.set_from_pixbuf(pixbuf)


class BodhiWallpaperWindow(Gtk.Window):
    def __init__(self, start_in_prefs=False):
        super().__init__(title="LeafPaper - Bodhi Wallpaper Changer")
        self.engine = BodhiWallpaperEngine()
        self.online_mgr = OnlineWallpaperManager()
        self.thread_pool = ThreadPoolExecutor(max_workers=5)

        self.all_wallpapers = []
        self.filtered_wallpapers = []
        self.online_wallpapers = []
        self.online_page = 1
        self.is_fetching_online = False

        self.selected_wallpaper = None
        self.selected_online_item = None
        self.current_category = "all"
        self.card_widgets = {}
        self.flowbox = None

        # Responsiveness tokens & debouncers
        self._load_token = 0
        self._search_debounce_id = None
        self._notified_tray = False

        # System tray attributes
        self.tray_icon = None
        self.app_indicator = None
        self.tray_menu = None

        # Adaptive window sizing (fits comfortably on 1024x768 or smaller)
        self.set_default_size(940, 620)
        self.set_size_request(660, 440)
        self.set_position(Gtk.WindowPosition.CENTER)

        # Set App Icon
        if os.path.exists(APP_ICON_PATH):
            self.set_icon_from_file(APP_ICON_PATH)
        else:
            self.set_icon_name("preferences-desktop-wallpaper")

        self._apply_css()
        self._build_headerbar()
        self._build_ui()
        self._setup_dnd()
        self._setup_keybindings()

        # Window event listeners
        self.connect("configure-event", self._on_window_configure)
        self.connect("delete-event", self._on_delete_event)

        # Initialize System Tray Icon
        self._init_tray()

        # Load initial local wallpapers
        self.reload_wallpapers()

        # Ensure background daemon is running if slideshow is configured
        if self.engine.config.get("auto_change", False):
            self.thread_pool.submit(self._ensure_daemon_if_needed)

        if start_in_prefs:
            GLib.idle_add(self._on_settings_clicked)

    def _ensure_daemon_if_needed(self):
        if self.engine.config.get("auto_change", False) and not is_daemon_running():
            start_daemon()

    def _apply_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CUSTOM_CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    # ==========================================
    # SYSTEM TRAY INTEGRATION
    # ==========================================
    def _init_tray(self):
        """Initializes the desktop system tray icon with full Moksha and DBus support."""
        if not self.engine.config.get("tray_enabled", True):
            return

        self.tray_menu = self._build_tray_menu()

        # 1. If modern StatusNotifierWatcher is present and AppIndicator3 is installed
        if HAVE_APPINDICATOR and _has_status_notifier_watcher():
            try:
                icon_file = TRAY_ICON_PATH if os.path.exists(TRAY_ICON_PATH) else "preferences-desktop-wallpaper"
                self.app_indicator = AppIndicator3.Indicator.new(
                    "bodhi-wallpaper",
                    icon_file,
                    AppIndicator3.IndicatorCategory.APPLICATION_STATUS
                )
                self.app_indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
                self.app_indicator.set_menu(self.tray_menu)
                return
            except Exception as e:
                print(f"[Tray] AppIndicator init notice: {e}", file=sys.stderr)

        # 2. Native XEmbed StatusIcon (Moksha Desktop shelf systray)
        try:
            self.tray_icon = Gtk.StatusIcon()
            if os.path.exists(TRAY_ICON_PATH):
                self.tray_icon.set_from_file(TRAY_ICON_PATH)
            else:
                self.tray_icon.set_from_icon_name("preferences-desktop-wallpaper")

            self.tray_icon.set_tooltip_text("LeafPaper - Bodhi Wallpaper Changer")
            self.tray_icon.set_visible(True)
            self.tray_icon.connect("activate", self._on_tray_activate)
            self.tray_icon.connect("popup-menu", self._on_tray_popup_menu)
            self._update_tray_tooltip()
        except Exception as e:
            print(f"[Tray] Failed initializing StatusIcon: {e}", file=sys.stderr)

    def _build_tray_menu(self):
        """Builds the context menu for the system tray icon."""
        menu = Gtk.Menu()

        item_open = Gtk.MenuItem(label="🌿 Open LeafPaper")
        item_open.connect("activate", self._on_tray_toggle_window)
        menu.append(item_open)

        menu.append(Gtk.SeparatorMenuItem())

        item_next = Gtk.MenuItem(label="⏭ Next Wallpaper")
        item_next.connect("activate", lambda w: self._on_quick_next(None))
        menu.append(item_next)

        item_prev = Gtk.MenuItem(label="⏮ Previous Wallpaper")
        item_prev.connect("activate", lambda w: self._on_quick_prev(None))
        menu.append(item_prev)

        item_rand = Gtk.MenuItem(label="🎲 Random Wallpaper")
        item_rand.connect("activate", lambda w: self._on_quick_random(None))
        menu.append(item_rand)

        item_bing = Gtk.MenuItem(label="🌐 Today's Bing Daily")
        item_bing.connect("activate", self._on_tray_bing_daily)
        menu.append(item_bing)

        menu.append(Gtk.SeparatorMenuItem())

        item_prefs = Gtk.MenuItem(label="⚙ Preferences...")
        item_prefs.connect("activate", lambda w: self._on_settings_clicked(None))
        menu.append(item_prefs)

        menu.append(Gtk.SeparatorMenuItem())

        item_quit = Gtk.MenuItem(label="✕ Quit Application")
        item_quit.connect("activate", self._quit_application)
        menu.append(item_quit)

        menu.show_all()
        return menu

    def _on_tray_activate(self, icon):
        """Left-click on tray icon toggles or presents the main window."""
        self._on_tray_toggle_window()

    def _on_tray_popup_menu(self, icon, button, activate_time):
        """Right-click on tray icon displays the menu."""
        if self.tray_menu:
            self.tray_menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, activate_time)

    def _on_tray_toggle_window(self, widget=None):
        if self.get_visible():
            if self.is_active():
                self.hide()
            else:
                self.present()
        else:
            self.show_all()
            self.present()

    def _on_tray_bing_daily(self, widget=None):
        def task():
            items = self.online_mgr.fetch_bing_daily(count=1)
            if items:
                style = self.engine.config.get("style", "zoom")
                self.online_mgr.download_and_apply(items[0], self.engine, style=style)
                GLib.idle_add(self.reload_wallpapers)
        self.thread_pool.submit(task)

    def _update_tray_tooltip(self):
        """Updates tray tooltip with the current wallpaper title."""
        if hasattr(self, "tray_icon") and self.tray_icon:
            curr = self.engine.config.get("current_wallpaper", "")
            name = os.path.basename(curr) if curr else "None"
            tip = f"LeafPaper - Bodhi Wallpaper Changer\nCurrent: {name}"
            self.tray_icon.set_tooltip_text(tip)

    def _on_delete_event(self, widget, event):
        """Window close button behavior: minimizes to tray if enabled."""
        if self.engine.config.get("minimize_to_tray", True) and (self.tray_icon or self.app_indicator):
            self.hide()
            if not self._notified_tray:
                self._notified_tray = True
                self.engine.send_notification(
                    "LeafPaper",
                    "Application is minimized to the system tray. Click the tray icon to reopen.",
                    icon_path=APP_ICON_PATH
                )
            return True  # Prevent window destruction
        else:
            self._quit_application()
            return False

    def _quit_application(self, *args):
        """Clean application shutdown."""
        if hasattr(self, "tray_icon") and self.tray_icon:
            self.tray_icon.set_visible(False)
        Gtk.main_quit()

    # ==========================================
    # RESPONSIVENESS & SHORTCUTS
    # ==========================================
    def _setup_keybindings(self):
        self.connect("key-press-event", self._on_key_press)

    def _on_key_press(self, widget, event):
        ctrl = (event.state & Gdk.ModifierType.CONTROL_MASK) != 0
        keyval = event.keyval

        if ctrl and keyval in (Gdk.KEY_b, Gdk.KEY_B):
            self._toggle_sidebar()
            return True
        elif ctrl and keyval in (Gdk.KEY_p, Gdk.KEY_P):
            self._toggle_preview()
            return True
        elif ctrl and keyval in (Gdk.KEY_f, Gdk.KEY_F):
            if self.current_category == "online":
                self.entry_online_query.grab_focus()
            else:
                self.search_entry.grab_focus()
            return True
        elif ctrl and keyval in (Gdk.KEY_r, Gdk.KEY_R):
            self._on_quick_random(None)
            return True
        return False

    def _on_window_configure(self, widget, event):
        """Responsive auto-collapse on narrow screen widths."""
        width = event.width
        if width < 760 and self.preview_scroll.get_visible() and self.sidebar_scroll.get_visible():
            self.preview_scroll.set_visible(False)
            self.btn_toggle_preview.set_active(False)
        return False

    def _build_headerbar(self):
        self.headerbar = Gtk.HeaderBar()
        self.headerbar.set_show_close_button(True)
        self.headerbar.set_title("LeafPaper")
        self.headerbar.set_subtitle("Bodhi Wallpaper Changer")
        self.set_titlebar(self.headerbar)

        # Left Side: Sidebar Toggle + Navigation + Import Controls
        left_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        self.btn_toggle_sidebar = Gtk.ToggleButton()
        self.btn_toggle_sidebar.set_image(Gtk.Image.new_from_icon_name("sidebar-show-symbolic", Gtk.IconSize.BUTTON))
        self.btn_toggle_sidebar.set_tooltip_text("Toggle Sidebar (Ctrl+B)")
        self.btn_toggle_sidebar.set_active(True)
        self.btn_toggle_sidebar.connect("toggled", self._on_sidebar_toggled)
        left_box.pack_start(self.btn_toggle_sidebar, False, False, 0)

        nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        Gtk.StyleContext.add_class(nav_box.get_style_context(), "linked")

        btn_prev = Gtk.Button.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON)
        btn_prev.set_tooltip_text("Previous Wallpaper")
        btn_prev.connect("clicked", self._on_quick_prev)
        nav_box.pack_start(btn_prev, False, False, 0)

        btn_rand = Gtk.Button.new_from_icon_name("media-playlist-shuffle-symbolic", Gtk.IconSize.BUTTON)
        btn_rand.set_tooltip_text("Random Local Wallpaper (Ctrl+R)")
        btn_rand.connect("clicked", self._on_quick_random)
        nav_box.pack_start(btn_rand, False, False, 0)

        btn_next = Gtk.Button.new_from_icon_name("go-next-symbolic", Gtk.IconSize.BUTTON)
        btn_next.set_tooltip_text("Next Wallpaper")
        btn_next.connect("clicked", self._on_quick_next)
        nav_box.pack_start(btn_next, False, False, 0)

        left_box.pack_start(nav_box, False, False, 2)

        btn_add_img = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        btn_add_img.set_tooltip_text("Import Image Files...")
        btn_add_img.connect("clicked", self._on_add_images)
        left_box.pack_start(btn_add_img, False, False, 0)

        btn_add_fld = Gtk.Button.new_from_icon_name("folder-new-symbolic", Gtk.IconSize.BUTTON)
        btn_add_fld.set_tooltip_text("Add Wallpaper Folder...")
        btn_add_fld.connect("clicked", self._on_add_folder)
        left_box.pack_start(btn_add_fld, False, False, 0)

        self.headerbar.pack_start(left_box)

        # Right Side: Settings + Inspector Toggle + Apply Button
        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        btn_settings = Gtk.Button.new_from_icon_name("preferences-system-symbolic", Gtk.IconSize.BUTTON)
        btn_settings.set_tooltip_text("Slideshow Preferences")
        btn_settings.connect("clicked", self._on_settings_clicked)
        right_box.pack_start(btn_settings, False, False, 0)

        self.btn_toggle_preview = Gtk.ToggleButton()
        self.btn_toggle_preview.set_image(Gtk.Image.new_from_icon_name("view-dual-symbolic", Gtk.IconSize.BUTTON))
        self.btn_toggle_preview.set_tooltip_text("Toggle Preview Inspector (Ctrl+P)")
        self.btn_toggle_preview.set_active(True)
        self.btn_toggle_preview.connect("toggled", self._on_preview_toggled)
        right_box.pack_start(self.btn_toggle_preview, False, False, 0)

        self.btn_apply = Gtk.Button(label=" Set Wallpaper")
        self.btn_apply.set_image(Gtk.Image.new_from_icon_name("emblem-default-symbolic", Gtk.IconSize.BUTTON))
        self.btn_apply.get_style_context().add_class("bodhi-apply-btn")
        self.btn_apply.connect("clicked", self._on_apply_clicked)
        right_box.pack_start(self.btn_apply, False, False, 0)

        self.headerbar.pack_end(right_box)

    def _on_sidebar_toggled(self, btn):
        self.sidebar_scroll.set_visible(btn.get_active())

    def _on_preview_toggled(self, btn):
        self.preview_scroll.set_visible(btn.get_active())

    def _toggle_sidebar(self):
        self.btn_toggle_sidebar.set_active(not self.btn_toggle_sidebar.get_active())

    def _toggle_preview(self):
        self.btn_toggle_preview.set_active(not self.btn_toggle_preview.get_active())

    def _build_ui(self):
        # Master Paned Container (Outer Paned splits [Sidebar+Center] and [Preview Inspector])
        self.outer_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(self.outer_paned)

        # Inner Paned Container (Splits [Sidebar] and [Gallery Center])
        self.inner_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.outer_paned.pack1(self.inner_paned, resize=True, shrink=False)

        # ==========================================
        # 1. LEFT PANE: Collapsible / Resizable Sidebar
        # ==========================================
        self.sidebar_scroll = Gtk.ScrolledWindow()
        self.sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.sidebar_scroll.set_size_request(180, -1)

        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sidebar_box.set_margin_start(6)
        sidebar_box.set_margin_end(6)
        sidebar_box.set_margin_top(6)
        sidebar_box.set_margin_bottom(6)
        self.sidebar_scroll.add(sidebar_box)
        self.inner_paned.pack1(self.sidebar_scroll, resize=False, shrink=False)
        self.inner_paned.set_position(195)

        # Search Entry with Debounce
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Filter (Ctrl+F)...")
        self.search_entry.connect("search-changed", self._on_search_changed)
        sidebar_box.pack_start(self.search_entry, False, False, 4)

        # Categories Header
        lbl_cat = Gtk.Label(label="<b>CATEGORIES</b>", use_markup=True)
        lbl_cat.set_halign(Gtk.Align.START)
        lbl_cat.get_style_context().add_class("stat-label")
        sidebar_box.pack_start(lbl_cat, False, False, 2)

        # Categories ListBox
        self.category_list = Gtk.ListBox()
        self.category_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.category_list.connect("row-selected", self._on_category_selected)
        sidebar_box.pack_start(self.category_list, False, False, 0)

        categories = [
            ("all", "🖼 All Wallpapers"),
            ("bodhi", "🌿 Bodhi Backgrounds"),
            ("system", "📁 System Backgrounds"),
            ("user", "🏠 User Wallpapers"),
            ("online", "🌐 Discover Online"),
            ("favorites", "⭐ Favorites"),
            ("history", "🕒 Recent History")
        ]

        self.cat_rows = {}
        for cat_id, title in categories:
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label=title)
            lbl.set_halign(Gtk.Align.START)
            lbl.get_style_context().add_class("sidebar-category")
            row.add(lbl)
            self.category_list.add(row)
            self.cat_rows[cat_id] = row

        sidebar_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

        # Custom Folders Header
        fld_hdr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        lbl_fld = Gtk.Label(label="<b>FOLDERS</b>", use_markup=True)
        lbl_fld.set_halign(Gtk.Align.START)
        lbl_fld.get_style_context().add_class("stat-label")
        fld_hdr_box.pack_start(lbl_fld, True, True, 0)

        btn_sub_fld = Gtk.Button.new_from_icon_name("list-remove-symbolic", Gtk.IconSize.MENU)
        btn_sub_fld.set_relief(Gtk.ReliefStyle.NONE)
        btn_sub_fld.set_tooltip_text("Remove Folder")
        btn_sub_fld.connect("clicked", self._on_remove_folder)
        fld_hdr_box.pack_end(btn_sub_fld, False, False, 0)

        btn_add_fld_small = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.MENU)
        btn_add_fld_small.set_relief(Gtk.ReliefStyle.NONE)
        btn_add_fld_small.set_tooltip_text("Add Folder")
        btn_add_fld_small.connect("clicked", self._on_add_folder)
        fld_hdr_box.pack_end(btn_add_fld_small, False, False, 0)

        sidebar_box.pack_start(fld_hdr_box, False, False, 2)

        # Folders List
        self.folder_list = Gtk.ListBox()
        self.folder_list.connect("row-selected", self._on_folder_selected)
        sidebar_box.pack_start(self.folder_list, True, True, 0)
        self._refresh_folders_list()

        # ==========================================
        # 2. CENTER PANE: Dynamic Gallery & Filters
        # ==========================================
        center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.inner_paned.pack2(center_box, resize=True, shrink=True)

        # Local Status Bar
        self.gallery_status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.gallery_status_bar.set_margin_start(10)
        self.gallery_status_bar.set_margin_end(10)
        self.gallery_status_bar.set_margin_top(6)
        self.gallery_status_bar.set_margin_bottom(4)

        self.lbl_count = Gtk.Label(label="Loading wallpapers...")
        self.lbl_count.set_halign(Gtk.Align.START)
        self.lbl_count.get_style_context().add_class("stat-label")
        self.gallery_status_bar.pack_start(self.lbl_count, True, True, 0)
        center_box.pack_start(self.gallery_status_bar, False, False, 0)

        # Responsive Online Search & Filter Grid
        self.online_bar = Gtk.Grid()
        self.online_bar.set_row_spacing(4)
        self.online_bar.set_column_spacing(6)
        self.online_bar.set_margin_start(8)
        self.online_bar.set_margin_end(8)
        self.online_bar.set_margin_top(4)
        self.online_bar.set_margin_bottom(4)

        # Row 0: Provider + Category + Resolution + Sort
        self.combo_provider = Gtk.ComboBoxText()
        self.combo_provider.append("wallhaven", "Wallhaven (500k+)")
        self.combo_provider.append("bing", "Bing Daily (UHD)")
        self.combo_provider.append("nasa", "NASA Space (APOD)")
        self.combo_provider.append("picsum", "Picsum Photos (5K)")
        self.combo_provider.append("wikimedia", "Wikimedia Featured (8K)")
        self.combo_provider.append("openverse", "Openverse (700M+ CC)")
        self.combo_provider.set_active_id("wallhaven")
        self.combo_provider.connect("changed", self._on_online_provider_changed)
        self.online_bar.attach(self.combo_provider, 0, 0, 1, 1)

        self.combo_online_cat = Gtk.ComboBoxText()
        self.combo_online_cat.set_hexpand(True)
        for k, v in CATEGORY_PRESETS.items():
            self.combo_online_cat.append(k, v["label"])
        self.combo_online_cat.append("custom", "🔍 Custom Search...")
        self.combo_online_cat.set_active_id("nature")
        self.combo_online_cat.connect("changed", self._on_online_cat_changed)
        self.online_bar.attach(self.combo_online_cat, 1, 0, 1, 1)

        self.combo_online_res = Gtk.ComboBoxText()
        self.combo_online_res.append("any", "Any Res")
        self.combo_online_res.append("1920x1080", "1080p+")
        self.combo_online_res.append("2560x1440", "2K+")
        self.combo_online_res.append("3840x2160", "4K+")
        self.combo_online_res.set_active_id("1920x1080")
        self.online_bar.attach(self.combo_online_res, 2, 0, 1, 1)

        self.combo_online_sort = Gtk.ComboBoxText()
        self.combo_online_sort.append("toplist", "Top Rated")
        self.combo_online_sort.append("hot", "Trending")
        self.combo_online_sort.append("random", "Random")
        self.combo_online_sort.set_active_id("toplist")
        self.online_bar.attach(self.combo_online_sort, 3, 0, 1, 1)

        # Row 1: Search Entry + Search Button + Pagination
        self.entry_online_query = Gtk.SearchEntry()
        self.entry_online_query.set_hexpand(True)
        self.entry_online_query.set_placeholder_text("Search keywords (e.g. forest, mountains, neon)...")
        self.entry_online_query.connect("activate", lambda e: self._on_fetch_online_clicked())
        self.online_bar.attach(self.entry_online_query, 0, 1, 2, 1)

        btn_fetch_online = Gtk.Button(label=" Search")
        btn_fetch_online.set_image(Gtk.Image.new_from_icon_name("system-search-symbolic", Gtk.IconSize.BUTTON))
        btn_fetch_online.get_style_context().add_class("bodhi-apply-btn")
        btn_fetch_online.connect("clicked", lambda b: self._on_fetch_online_clicked())
        self.online_bar.attach(btn_fetch_online, 2, 1, 1, 1)

        page_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.btn_online_prev = Gtk.Button.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON)
        self.btn_online_prev.connect("clicked", self._on_online_prev_page)
        page_box.pack_start(self.btn_online_prev, False, False, 0)

        self.lbl_online_page = Gtk.Label(label="1")
        self.lbl_online_page.get_style_context().add_class("stat-value")
        page_box.pack_start(self.lbl_online_page, False, False, 4)

        self.btn_online_next = Gtk.Button.new_from_icon_name("go-next-symbolic", Gtk.IconSize.BUTTON)
        self.btn_online_next.connect("clicked", self._on_online_next_page)
        page_box.pack_start(self.btn_online_next, False, False, 0)
        self.online_bar.attach(page_box, 3, 1, 1, 1)

        center_box.pack_start(self.online_bar, False, False, 0)

        # Scrolled FlowBox Gallery
        self.gallery_scroll = Gtk.ScrolledWindow()
        self.gallery_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_valign(Gtk.Align.START)
        self.flowbox.set_min_children_per_line(1)
        self.flowbox.set_max_children_per_line(24)
        self.flowbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.flowbox.set_homogeneous(True)
        self.flowbox.set_column_spacing(6)
        self.flowbox.set_row_spacing(6)
        self.flowbox.set_margin_start(6)
        self.flowbox.set_margin_end(6)
        self.flowbox.set_margin_top(4)
        self.flowbox.set_margin_bottom(6)
        self.flowbox.connect("child-activated", self._on_card_activated)
        self.flowbox.connect("selected-children-changed", self._on_card_selected)

        self.gallery_scroll.add(self.flowbox)
        center_box.pack_start(self.gallery_scroll, True, True, 0)

        # ==========================================
        # 3. RIGHT PANE: Collapsible Preview Inspector
        # ==========================================
        self.preview_scroll = Gtk.ScrolledWindow()
        self.preview_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.preview_scroll.set_size_request(240, -1)

        self.preview_pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.preview_pane.get_style_context().add_class("preview-box")
        self.preview_scroll.add(self.preview_pane)

        self.outer_paned.pack2(self.preview_scroll, resize=False, shrink=False)
        self.outer_paned.set_position(690)

        # Preview Title
        lbl_prev_title = Gtk.Label(label="<b>PREVIEW &amp; INFO</b>", use_markup=True)
        lbl_prev_title.set_halign(Gtk.Align.START)
        lbl_prev_title.get_style_context().add_class("stat-label")
        self.preview_pane.pack_start(lbl_prev_title, False, False, 0)

        # Preview Image Frame
        preview_frame = Gtk.Frame()
        preview_frame.set_shadow_type(Gtk.ShadowType.IN)
        self.preview_image = Gtk.Image.new_from_icon_name("preferences-desktop-wallpaper", Gtk.IconSize.DIALOG)
        self.preview_image.set_size_request(220, 140)
        preview_frame.add(self.preview_image)
        self.preview_pane.pack_start(preview_frame, False, False, 0)

        # Name and Favorite Row
        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.lbl_sel_name = Gtk.Label(label="Select a wallpaper")
        self.lbl_sel_name.set_halign(Gtk.Align.START)
        self.lbl_sel_name.set_ellipsize(3)
        self.lbl_sel_name.get_style_context().add_class("stat-value")
        name_box.pack_start(self.lbl_sel_name, True, True, 0)

        self.btn_fav = Gtk.Button.new_from_icon_name("non-starred-symbolic", Gtk.IconSize.BUTTON)
        self.btn_fav.set_relief(Gtk.ReliefStyle.NONE)
        self.btn_fav.set_tooltip_text("Favorite Wallpaper")
        self.btn_fav.connect("clicked", self._on_toggle_favorite)
        name_box.pack_end(self.btn_fav, False, False, 0)
        self.preview_pane.pack_start(name_box, False, False, 0)

        # Metadata Grid
        meta_grid = Gtk.Grid()
        meta_grid.set_row_spacing(4)
        meta_grid.set_column_spacing(8)

        meta_fields = [
            ("Resolution:", "lbl_dim"),
            ("File Size:", "lbl_size"),
            ("Format:", "lbl_fmt"),
            ("Source:", "lbl_path")
        ]

        self.meta_labels = {}
        for row, (caption, attr_name) in enumerate(meta_fields):
            c_lbl = Gtk.Label(label=caption)
            c_lbl.set_halign(Gtk.Align.START)
            c_lbl.get_style_context().add_class("stat-label")
            meta_grid.attach(c_lbl, 0, row, 1, 1)

            v_lbl = Gtk.Label(label="--")
            v_lbl.set_halign(Gtk.Align.START)
            v_lbl.set_ellipsize(3)
            v_lbl.get_style_context().add_class("stat-value")
            meta_grid.attach(v_lbl, 1, row, 1, 1)
            self.meta_labels[attr_name] = v_lbl

        self.preview_pane.pack_start(meta_grid, False, False, 2)
        self.preview_pane.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 2)

        # Scaling Mode Setting
        lbl_style = Gtk.Label(label="<b>Scaling Style:</b>", use_markup=True)
        lbl_style.set_halign(Gtk.Align.START)
        lbl_style.get_style_context().add_class("stat-label")
        self.preview_pane.pack_start(lbl_style, False, False, 0)

        self.combo_style = Gtk.ComboBoxText()
        self.combo_style.append("zoom", "Zoom / Fill (Crop)")
        self.combo_style.append("fit", "Fit Screen (Letterbox)")
        self.combo_style.append("stretch", "Stretch")
        self.combo_style.append("center", "Centered (1:1)")
        self.combo_style.append("tile", "Tiled Pattern")
        current_style = self.engine.config.get("style", "zoom")
        self.combo_style.set_active_id(current_style)
        self.combo_style.connect("changed", self._on_style_changed)
        self.preview_pane.pack_start(self.combo_style, False, False, 0)

        # Target Scope
        lbl_scope = Gtk.Label(label="<b>Target Scope:</b>", use_markup=True)
        lbl_scope.set_halign(Gtk.Align.START)
        lbl_scope.get_style_context().add_class("stat-label")
        self.preview_pane.pack_start(lbl_scope, False, False, 0)

        self.combo_scope = Gtk.ComboBoxText()
        self.combo_scope.append("all", "All Desktops & Screens")
        self.combo_scope.append("current", "Current Desktop Only")
        self.combo_scope.set_active_id("all")
        self.preview_pane.pack_start(self.combo_scope, False, False, 0)

        # Download & Save Button (for online wallpapers)
        self.btn_save_library = Gtk.Button(label=" Save to Library")
        self.btn_save_library.set_image(Gtk.Image.new_from_icon_name("document-save-symbolic", Gtk.IconSize.BUTTON))
        self.btn_save_library.connect("clicked", self._on_save_to_library_clicked)
        self.btn_save_library.set_no_show_all(True)
        self.btn_save_library.set_visible(False)
        self.preview_pane.pack_start(self.btn_save_library, False, False, 2)

        # Download Progress Bar
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_no_show_all(True)
        self.progress_bar.set_visible(False)
        self.preview_pane.pack_start(self.progress_bar, False, False, 2)

        # Spacer
        self.preview_pane.pack_start(Gtk.Box(), True, True, 0)

        # Apply Status feedback label
        self.lbl_apply_status = Gtk.Label(label="")
        self.lbl_apply_status.set_halign(Gtk.Align.CENTER)
        self.lbl_apply_status.set_line_wrap(True)
        self.preview_pane.pack_end(self.lbl_apply_status, False, False, 2)

        # Initial category selection
        self.category_list.select_row(self.cat_rows["all"])

    def _setup_dnd(self):
        """Enable drag-and-drop onto the window to add wallpapers or folders."""
        self.drag_dest_set(
            Gtk.DestDefaults.ALL,
            [],
            Gdk.DragAction.COPY
        )
        self.drag_dest_add_uri_targets()
        self.connect("drag-data-received", self._on_drag_data_received)

    def _on_drag_data_received(self, widget, drag_context, x, y, data, info, time):
        uris = data.get_uris()
        added_any = False
        for uri in uris:
            path = unquote(urlparse(uri).path)
            if os.path.isdir(path):
                if self.engine.add_folder(path):
                    added_any = True
            elif os.path.isfile(path):
                dest_dir = os.path.expanduser("~/Pictures/Wallpapers")
                os.makedirs(dest_dir, exist_ok=True)
                dest = os.path.join(dest_dir, os.path.basename(path))
                try:
                    shutil.copy2(path, dest)
                    added_any = True
                except Exception:
                    pass

        if added_any:
            self._refresh_folders_list()
            self.reload_wallpapers()
            self.lbl_apply_status.set_text("Imported new wallpaper(s)!")

        drag_context.finish(True, False, time)

    def reload_wallpapers(self):
        """Scans directories and updates the gallery view."""
        self.lbl_count.set_text("Scanning wallpapers...")
        self.all_wallpapers = self.engine.scan_wallpapers()
        if self.current_category != "online":
            self._filter_and_display()

    def _on_search_changed(self, entry):
        """Debounced search input to keep typing completely fluid and lag-free."""
        if self._search_debounce_id:
            GLib.source_remove(self._search_debounce_id)
        self._search_debounce_id = GLib.timeout_add(180, self._on_search_debounced)

    def _on_search_debounced(self):
        self._search_debounce_id = None
        if self.current_category != "online":
            self._filter_and_display()
        return False

    def _filter_and_display(self):
        # Invalidate any in-flight thumbnail workers from previous categories
        self._load_token += 1
        curr_token = self._load_token

        for child in self.flowbox.get_children():
            self.flowbox.remove(child)
        self.card_widgets.clear()

        search_query = self.search_entry.get_text().strip().lower()
        cat = self.current_category

        filtered = []
        bodhi_dir = "/usr/share/enlightenment/data/backgrounds"
        sys_dir = "/usr/share/backgrounds"
        user_dir = os.path.expanduser("~/Pictures")
        e_dir = os.path.expanduser("~/.e/e/backgrounds")

        favorites = set(self.engine.config.get("favorites", []))
        history = list(self.engine.config.get("history", []))

        if cat == "all":
            filtered = list(self.all_wallpapers)
        elif cat == "bodhi":
            filtered = [w for w in self.all_wallpapers if w.startswith(bodhi_dir)]
        elif cat == "system":
            filtered = [w for w in self.all_wallpapers if w.startswith(sys_dir) and not w.startswith(bodhi_dir)]
        elif cat == "user":
            filtered = [w for w in self.all_wallpapers if w.startswith(user_dir) or w.startswith(e_dir)]
        elif cat == "favorites":
            filtered = [w for w in self.all_wallpapers if w in favorites]
        elif cat == "history":
            filtered = [w for w in history if os.path.exists(w)]
        elif cat.startswith("folder:"):
            target_fld = cat[7:]
            filtered = [w for w in self.all_wallpapers if w.startswith(target_fld)]

        if search_query:
            filtered = [w for w in filtered if search_query in os.path.basename(w).lower()]

        self.filtered_wallpapers = filtered
        self.lbl_count.set_text(f"Showing {len(filtered)} wallpaper{'s' if len(filtered) != 1 else ''}")

        # Populate cards and submit thumbnail jobs with token
        for path in filtered:
            card = WallpaperCard(path, self.engine)
            self.card_widgets[path] = card
            self.flowbox.add(card)
            self.thread_pool.submit(self._async_load_thumbnail, path, curr_token)

        self.flowbox.show_all()

        current_wp = self.engine.config.get("current_wallpaper", "")
        if current_wp in self.card_widgets:
            self.flowbox.select_child(self.card_widgets[current_wp])
            self._update_preview(current_wp)
        elif filtered:
            self.flowbox.select_child(self.card_widgets[filtered[0]])
            self._update_preview(filtered[0])

    def _async_load_thumbnail(self, path, token):
        """Worker thread task with cancellation token check."""
        if token != self._load_token:
            return
        try:
            thumb_path = self.engine.get_thumbnail(path, size=(180, 112))
            if token != self._load_token:
                return
            if thumb_path and os.path.exists(thumb_path):
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(thumb_path, 175, 110, True)
                GLib.idle_add(self._apply_thumbnail_pixbuf, path, pixbuf, token)
        except Exception:
            pass

    def _apply_thumbnail_pixbuf(self, path, pixbuf, token):
        if token == self._load_token and path in self.card_widgets:
            self.card_widgets[path].set_pixbuf(pixbuf)
        return False

    # ==========================================
    # ONLINE WALLPAPERS ENGINE
    # ==========================================
    def _on_online_provider_changed(self, combo):
        prov = combo.get_active_id() or "wallhaven"
        is_wallhaven = (prov == "wallhaven")
        is_searchable = prov in ["wallhaven", "openverse"]
        has_pagination = prov not in ["bing", "nasa"]

        self.combo_online_cat.set_visible(is_wallhaven)
        self.combo_online_res.set_visible(is_wallhaven)
        self.combo_online_sort.set_visible(is_wallhaven)
        self.entry_online_query.set_visible(is_searchable)
        self.btn_online_prev.set_sensitive(has_pagination)
        self.btn_online_next.set_sensitive(has_pagination)
        self.online_page = 1
        self.lbl_online_page.set_text("1")
        self._fetch_online_wallpapers()

    def _on_online_cat_changed(self, combo):
        cat = combo.get_active_id()
        if cat == "custom":
            self.entry_online_query.grab_focus()
        else:
            self.online_page = 1
            self._fetch_online_wallpapers()

    def _on_fetch_online_clicked(self):
        self.online_page = 1
        self._fetch_online_wallpapers()

    def _on_online_prev_page(self, btn):
        if self.online_page > 1:
            self.online_page -= 1
            self.lbl_online_page.set_text(str(self.online_page))
            self._fetch_online_wallpapers()

    def _on_online_next_page(self, btn):
        self.online_page += 1
        self.lbl_online_page.set_text(str(self.online_page))
        self._fetch_online_wallpapers()

    def _fetch_online_wallpapers(self):
        if self.is_fetching_online:
            return
        self.is_fetching_online = True
        self._load_token += 1
        curr_token = self._load_token

        for child in self.flowbox.get_children():
            self.flowbox.remove(child)
        self.card_widgets.clear()

        prov = self.combo_provider.get_active_id() or "wallhaven"
        cat_key = self.combo_online_cat.get_active_id() or "nature"
        query = self.entry_online_query.get_text().strip()
        res = self.combo_online_res.get_active_id() or "1920x1080"
        sort = self.combo_online_sort.get_active_id() or "toplist"
        page = self.online_page

        self.lbl_count.set_text(f"Searching {prov.title()} wallpapers...")

        def task():
            items = []
            try:
                if prov == "bing":
                    items = self.online_mgr.fetch_bing_daily(count=8)
                elif prov == "nasa":
                    items = self.online_mgr.fetch_nasa_apod(count=8)
                elif prov == "picsum":
                    items = self.online_mgr.fetch_picsum(page=page, count=24)
                elif prov == "wikimedia":
                    items = self.online_mgr.fetch_wikimedia_featured(count=24)
                elif prov == "openverse":
                    items = self.online_mgr.fetch_openverse(query=query or "landscape", page=page, count=24)
                else:
                    if cat_key == "custom":
                        items = self.online_mgr.search_wallhaven(
                            query=query or "nature", resolution=res, sorting=sort, page=page
                        )
                    else:
                        items = self.online_mgr.search_wallhaven(
                            category_key=cat_key, resolution=res, sorting=sort, page=page
                        )
            except Exception as e:
                print(f"[GUI] Online search error: {e}", file=sys.stderr)

            GLib.idle_add(self._on_online_fetched, items, prov, curr_token)

        self.thread_pool.submit(task)

    def _on_online_fetched(self, items, provider, token):
        if token != self._load_token:
            return
        self.is_fetching_online = False
        self.online_wallpapers = items
        self.lbl_count.set_text(f"Found {len(items)} online wallpapers ({provider.title()})")

        for item in items:
            card = OnlineWallpaperCard(item, self.online_mgr)
            self.card_widgets[item["id"]] = card
            self.flowbox.add(card)
            self.thread_pool.submit(self._async_load_online_thumbnail, item, card, token)

        self.flowbox.show_all()

        if items:
            first_card = self.card_widgets[items[0]["id"]]
            self.flowbox.select_child(first_card)
            self._update_online_preview(items[0])

    def _async_load_online_thumbnail(self, item, card, token):
        if token != self._load_token:
            return
        try:
            cached_thumb = self.online_mgr.get_cached_thumbnail(item["thumb_url"])
            if token != self._load_token:
                return
            if cached_thumb and os.path.exists(cached_thumb):
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(cached_thumb, 175, 110, True)
                GLib.idle_add(self._apply_online_pixbuf, card, pixbuf, token)
        except Exception:
            pass

    def _apply_online_pixbuf(self, card, pixbuf, token):
        if token == self._load_token and card:
            card.set_pixbuf(pixbuf)
        return False

    def _update_online_preview(self, item):
        self.selected_online_item = item
        self.selected_wallpaper = None

        self.lbl_sel_name.set_text(item["title"])
        self.meta_labels["lbl_dim"].set_text(item.get("resolution", "HD"))
        self.meta_labels["lbl_size"].set_text(item.get("file_size", "Unknown"))
        self.meta_labels["lbl_fmt"].set_text(item.get("format", "JPG"))
        self.meta_labels["lbl_path"].set_text(f"{item.get('provider')} ({item.get('category')})")
        self.meta_labels["lbl_path"].set_tooltip_text(item.get("full_url", ""))

        self.btn_apply.set_label(" Download & Apply")
        self.btn_save_library.set_visible(True)
        self.btn_fav.set_visible(False)

        self.thread_pool.submit(self._async_load_online_preview, item)

    def _async_load_online_preview(self, item):
        try:
            cached_thumb = self.online_mgr.get_cached_thumbnail(item["thumb_url"])
            if cached_thumb and os.path.exists(cached_thumb):
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(cached_thumb, 220, 140, True)
                GLib.idle_add(self.preview_image.set_from_pixbuf, pixbuf)
        except Exception:
            pass

    def _update_preview(self, path):
        self.selected_online_item = None
        self.selected_wallpaper = path
        meta = self.engine.get_wallpaper_metadata(path)
        if not meta:
            return

        self.lbl_sel_name.set_text(meta["name"])
        self.meta_labels["lbl_dim"].set_text(meta["dimensions"])
        self.meta_labels["lbl_size"].set_text(meta["size"])
        self.meta_labels["lbl_fmt"].set_text(meta["format"])
        self.meta_labels["lbl_path"].set_text(os.path.basename(path))
        self.meta_labels["lbl_path"].set_tooltip_text(path)

        self.btn_apply.set_label(" Set Wallpaper")
        self.btn_save_library.set_visible(False)
        self.btn_fav.set_visible(True)

        is_fav = meta["is_favorite"]
        self.btn_fav.set_image(
            Gtk.Image.new_from_icon_name("starred-symbolic" if is_fav else "non-starred-symbolic", Gtk.IconSize.BUTTON)
        )

        self._update_tray_tooltip()
        self.thread_pool.submit(self._async_load_preview, path)

    def _async_load_preview(self, path):
        try:
            thumb_path = self.engine.get_thumbnail(path, size=(480, 300))
            if thumb_path and os.path.exists(thumb_path):
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(thumb_path, 220, 140, True)
                GLib.idle_add(self.preview_image.set_from_pixbuf, pixbuf)
        except Exception:
            pass

    def _on_card_selected(self, flowbox):
        selected = flowbox.get_selected_children()
        if selected:
            card = selected[0]
            if getattr(card, "is_online", False):
                self._update_online_preview(card.item)
            else:
                self._update_preview(card.wallpaper_path)

    def _on_card_activated(self, flowbox, child):
        """Double-click on card applies wallpaper immediately."""
        self._apply_current_selection()

    def _on_apply_clicked(self, widget):
        self._apply_current_selection()

    def _apply_current_selection(self):
        style = self.combo_style.get_active_id() or "zoom"

        # Online Wallpaper Action
        if self.selected_online_item:
            item = self.selected_online_item
            self.lbl_apply_status.set_text(f"Downloading from {item.get('provider')}...")
            self.progress_bar.set_visible(True)
            self.progress_bar.set_fraction(0.15)
            self.btn_apply.set_sensitive(False)

            def online_dl_task():
                success = False
                err_msg = ""
                local_path = None
                try:
                    def p_cb(fraction, curr, total):
                        GLib.idle_add(self.progress_bar.set_fraction, fraction)

                    local_path = self.online_mgr.download_and_apply(
                        item, self.engine, style=style, progress_callback=p_cb
                    )
                    success = True
                except Exception as e:
                    err_msg = str(e)

                GLib.idle_add(self._on_online_applied_finished, success, err_msg, local_path)

            threading.Thread(target=online_dl_task, daemon=True).start()
            return

        if not self.selected_wallpaper:
            return

        self.lbl_apply_status.set_text("Applying wallpaper...")
        self.btn_apply.set_sensitive(False)

        def apply_task():
            success = False
            err_msg = ""
            try:
                ipc_res = send_ipc_command(f"SET {self.selected_wallpaper} {style}")
                if ipc_res and ipc_res.startswith("OK"):
                    success = True
                else:
                    success = self.engine.apply_wallpaper(self.selected_wallpaper, style=style)
            except Exception as e:
                err_msg = str(e)

            GLib.idle_add(self._on_apply_finished, success, err_msg)

        threading.Thread(target=apply_task, daemon=True).start()

    def _on_online_applied_finished(self, success, err_msg, local_path):
        self.progress_bar.set_visible(False)
        self.btn_apply.set_sensitive(True)
        if success:
            self.lbl_apply_status.set_text("✓ Downloaded & Applied to Desktop!")
            self.all_wallpapers = self.engine.scan_wallpapers()
            self._update_tray_tooltip()
        else:
            self.lbl_apply_status.set_text(f"Download Error: {err_msg[:25]}")
        GLib.timeout_add_seconds(4, lambda: self.lbl_apply_status.set_text("") or False)

    def _on_save_to_library_clicked(self, widget):
        if not self.selected_online_item:
            return
        item = self.selected_online_item
        self.lbl_apply_status.set_text("Saving to library...")
        self.progress_bar.set_visible(True)
        self.progress_bar.set_fraction(0.2)
        self.btn_save_library.set_sensitive(False)

        def save_task():
            def p_cb(fraction, curr, total):
                GLib.idle_add(self.progress_bar.set_fraction, fraction)
            success = False
            err_msg = ""
            dest = None
            try:
                dest = self.online_mgr.download_wallpaper(item, progress_callback=p_cb)
                success = True
            except Exception as e:
                err_msg = str(e)

            GLib.idle_add(self._on_save_finished, success, err_msg, dest)

        threading.Thread(target=save_task, daemon=True).start()

    def _on_save_finished(self, success, err_msg, dest):
        self.progress_bar.set_visible(False)
        self.btn_save_library.set_sensitive(True)
        if success:
            self.lbl_apply_status.set_text("✓ Saved to ~/Pictures/Wallpapers/Online!")
            self.all_wallpapers = self.engine.scan_wallpapers()
        else:
            self.lbl_apply_status.set_text(f"Error: {err_msg[:25]}")
        GLib.timeout_add_seconds(4, lambda: self.lbl_apply_status.set_text("") or False)

    def _on_apply_finished(self, success, err_msg):
        self.btn_apply.set_sensitive(True)
        if success:
            self.lbl_apply_status.set_text("✓ Wallpaper applied successfully!")
            self._update_tray_tooltip()
            for card in self.card_widgets.values():
                if hasattr(card, "update_active_status"):
                    card.update_active_status()
        else:
            self.lbl_apply_status.set_text(f"Error: {err_msg[:30]}")

        GLib.timeout_add_seconds(4, lambda: self.lbl_apply_status.set_text("") or False)

    def _on_toggle_favorite(self, widget):
        if not self.selected_wallpaper:
            return
        is_fav = self.engine.toggle_favorite(self.selected_wallpaper)
        self.btn_fav.set_image(
            Gtk.Image.new_from_icon_name("starred-symbolic" if is_fav else "non-starred-symbolic", Gtk.IconSize.BUTTON)
        )
        if self.current_category == "favorites":
            self._filter_and_display()

    def _on_style_changed(self, combo):
        self.engine.config["style"] = combo.get_active_id() or "zoom"
        self.engine.save_config()

    def _on_category_selected(self, listbox, row):
        if not row:
            return
        for cat_id, r in self.cat_rows.items():
            if r == row:
                self.current_category = cat_id
                if hasattr(self, "flowbox") and self.flowbox is not None:
                    if cat_id == "online":
                        self.gallery_status_bar.hide()
                        self.online_bar.show_all()
                        prov = self.combo_provider.get_active_id() or "wallhaven"
                        is_wallhaven = (prov == "wallhaven")
                        is_searchable = prov in ["wallhaven", "openverse"]
                        has_pagination = prov not in ["bing", "nasa"]

                        self.combo_online_cat.set_visible(is_wallhaven)
                        self.combo_online_res.set_visible(is_wallhaven)
                        self.combo_online_sort.set_visible(is_wallhaven)
                        self.entry_online_query.set_visible(is_searchable)
                        self.btn_online_prev.set_sensitive(has_pagination)
                        self.btn_online_next.set_sensitive(has_pagination)
                        if not self.online_wallpapers:
                            self._fetch_online_wallpapers()
                        else:
                            self._on_online_fetched(self.online_wallpapers, prov, self._load_token)
                    else:
                        self.online_bar.hide()
                        self.gallery_status_bar.show_all()
                        self.selected_online_item = None
                        self.btn_save_library.set_visible(False)
                        self._filter_and_display()
                break

    def _on_folder_selected(self, listbox, row):
        if not row:
            return
        self.category_list.unselect_all()
        fld_path = getattr(row, "folder_path", None)
        if fld_path:
            self.current_category = f"folder:{fld_path}"
            if hasattr(self, "flowbox") and self.flowbox is not None:
                self.online_bar.hide()
                self.gallery_status_bar.show_all()
                self.selected_online_item = None
                self.btn_save_library.set_visible(False)
                self._filter_and_display()

    def _refresh_folders_list(self):
        for child in self.folder_list.get_children():
            self.folder_list.remove(child)

        folders = self.engine.config.get("folders", [])
        for fld in folders:
            if fld in ["/usr/share/enlightenment/data/backgrounds", "/usr/share/backgrounds"]:
                continue
            row = Gtk.ListBoxRow()
            row.folder_path = fld
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            lbl = Gtk.Label(label=os.path.basename(fld) or fld)
            lbl.set_halign(Gtk.Align.START)
            lbl.get_style_context().add_class("sidebar-category")
            lbl.set_tooltip_text(fld)
            box.pack_start(lbl, True, True, 0)
            row.add(box)
            self.folder_list.add(row)

        self.folder_list.show_all()

    def _on_add_folder(self, widget):
        dialog = Gtk.FileChooserDialog(
            title="Choose Wallpaper Folder",
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Select", Gtk.ResponseType.OK)

        if dialog.run() == Gtk.ResponseType.OK:
            selected_dir = dialog.get_filename()
            if selected_dir and self.engine.add_folder(selected_dir):
                self._refresh_folders_list()
                self.reload_wallpapers()

        dialog.destroy()

    def _on_remove_folder(self, widget):
        selected_row = self.folder_list.get_selected_row()
        if selected_row and hasattr(selected_row, "folder_path"):
            fld = selected_row.folder_path
            self.engine.remove_folder(fld)
            self._refresh_folders_list()
            self.reload_wallpapers()

    def _on_add_images(self, widget):
        dialog = Gtk.FileChooserDialog(
            title="Import Wallpaper Images",
            parent=self,
            action=Gtk.FileChooserAction.OPEN
        )
        dialog.set_select_multiple(True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Import", Gtk.ResponseType.OK)

        filter_img = Gtk.FileFilter()
        filter_img.set_name("Image & EDJ Files")
        for ext in ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.bmp", "*.edj"]:
            filter_img.add_pattern(ext)
        dialog.add_filter(filter_img)

        if dialog.run() == Gtk.ResponseType.OK:
            dest_dir = os.path.expanduser("~/Pictures/Wallpapers")
            os.makedirs(dest_dir, exist_ok=True)
            for fpath in dialog.get_filenames():
                try:
                    shutil.copy2(fpath, os.path.join(dest_dir, os.path.basename(fpath)))
                except Exception:
                    pass
            self.reload_wallpapers()

        dialog.destroy()

    def _on_quick_prev(self, widget):
        res = send_ipc_command("PREV")
        target = res[3:] if res and res.startswith("OK ") else self.engine.get_next_wallpaper(forward=False)
        if target:
            self.engine.apply_wallpaper(target)
            self._update_selection_from_path(target)

    def _on_quick_next(self, widget):
        res = send_ipc_command("NEXT")
        target = res[3:] if res and res.startswith("OK ") else self.engine.get_next_wallpaper(forward=True)
        if target:
            self.engine.apply_wallpaper(target)
            self._update_selection_from_path(target)

    def _on_quick_random(self, widget):
        res = send_ipc_command("RANDOM")
        target = res[3:] if res and res.startswith("OK ") else self.engine.get_random_wallpaper()
        if target:
            self.engine.apply_wallpaper(target)
            self._update_selection_from_path(target)

    def _update_selection_from_path(self, path):
        if path in self.card_widgets:
            self.flowbox.select_child(self.card_widgets[path])
            self._update_preview(path)
        for card in self.card_widgets.values():
            if hasattr(card, "update_active_status"):
                card.update_active_status()
        self._update_tray_tooltip()

    def _on_settings_clicked(self, widget=None):
        """Opens the Slideshow & Autostart Preferences Dialog."""
        dialog = PreferencesDialog(self, self.engine)
        dialog.run()
        dialog.destroy()
        self.engine.config = self.engine.load_config()
        self._update_tray_tooltip()


class PreferencesDialog(Gtk.Dialog):
    """Preferences dialog for Slideshow, Timers, Autostart, System Tray, and Notifications."""
    def __init__(self, parent, engine):
        super().__init__(title="Wallpaper Preferences", parent=parent, flags=0)
        self.parent_window = parent
        self.engine = engine
        self.set_default_size(440, 380)
        self.set_border_width(10)
        self.add_button("Close", Gtk.ResponseType.CLOSE)

        box = self.get_content_area()
        box.set_spacing(10)

        # 1. Auto Change Switch
        auto_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl_auto = Gtk.Label(label="<b>Enable Automatic Slideshow:</b>", use_markup=True)
        lbl_auto.set_halign(Gtk.Align.START)
        self.switch_auto = Gtk.Switch()
        self.switch_auto.set_active(self.engine.config.get("auto_change", False))
        self.switch_auto.connect("state-set", self._on_auto_toggled)
        auto_box.pack_start(lbl_auto, True, True, 0)
        auto_box.pack_end(self.switch_auto, False, False, 0)
        box.pack_start(auto_box, False, False, 2)

        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 2)

        # Settings Grid
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(10)
        box.pack_start(grid, False, False, 2)

        # Interval
        lbl_int = Gtk.Label(label="Change Interval:")
        lbl_int.set_halign(Gtk.Align.START)
        grid.attach(lbl_int, 0, 0, 1, 1)

        self.combo_interval = Gtk.ComboBoxText()
        intervals = [
            ("1", "1 Minute"),
            ("5", "5 Minutes"),
            ("10", "10 Minutes"),
            ("15", "15 Minutes"),
            ("30", "30 Minutes"),
            ("60", "1 Hour"),
            ("120", "2 Hours"),
            ("360", "6 Hours"),
            ("1440", "24 Hours (Daily)")
        ]
        for key, val in intervals:
            self.combo_interval.append(key, val)
        curr_int = str(self.engine.config.get("interval_minutes", 15))
        self.combo_interval.set_active_id(curr_int if curr_int in [k for k, _ in intervals] else "15")
        self.combo_interval.connect("changed", self._on_interval_changed)
        grid.attach(self.combo_interval, 1, 0, 1, 1)

        # Order (Shuffle vs Sequential)
        lbl_order = Gtk.Label(label="Rotation Order:")
        lbl_order.set_halign(Gtk.Align.START)
        grid.attach(lbl_order, 0, 1, 1, 1)

        self.combo_order = Gtk.ComboBoxText()
        self.combo_order.append("random", "Random / Shuffle")
        self.combo_order.append("sequential", "Sequential")
        self.combo_order.set_active_id("random" if self.engine.config.get("random_order", True) else "sequential")
        self.combo_order.connect("changed", self._on_order_changed)
        grid.attach(self.combo_order, 1, 1, 1, 1)

        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 2)

        # Checkboxes
        self.chk_notify = Gtk.CheckButton(label="Desktop notification on wallpaper change")
        self.chk_notify.set_active(self.engine.config.get("notify", True))
        self.chk_notify.connect("toggled", self._on_notify_toggled)
        box.pack_start(self.chk_notify, False, False, 0)

        self.chk_tray = Gtk.CheckButton(label="Show icon in system tray while running")
        self.chk_tray.set_active(self.engine.config.get("tray_enabled", True))
        self.chk_tray.connect("toggled", self._on_tray_toggled)
        box.pack_start(self.chk_tray, False, False, 0)

        self.chk_min_tray = Gtk.CheckButton(label="Keep running in system tray when window is closed")
        self.chk_min_tray.set_active(self.engine.config.get("minimize_to_tray", True))
        self.chk_min_tray.connect("toggled", self._on_min_tray_toggled)
        box.pack_start(self.chk_min_tray, False, False, 0)

        self.chk_autostart = Gtk.CheckButton(label="Start daemon automatically at system login")
        self.chk_autostart.set_active(os.path.exists(AUTOSTART_FILE))
        self.chk_autostart.connect("toggled", self._on_autostart_toggled)
        box.pack_start(self.chk_autostart, False, False, 0)

        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 2)

        # Service Status Row (Status label + Action button)
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.lbl_daemon_status = Gtk.Label(label="Checking daemon status...")
        self.lbl_daemon_status.set_halign(Gtk.Align.START)
        self.lbl_daemon_status.get_style_context().add_class("stat-label")
        status_box.pack_start(self.lbl_daemon_status, True, True, 0)

        self.btn_daemon_action = Gtk.Button(label="Start Service")
        self.btn_daemon_action.connect("clicked", self._on_daemon_action_clicked)
        status_box.pack_end(self.btn_daemon_action, False, False, 0)
        box.pack_start(status_box, False, False, 2)

        self._check_daemon_status()
        self.show_all()

        # Update status & countdown every second while dialog is open
        self._status_timer_id = GLib.timeout_add(1000, self._check_daemon_status)
        self.connect("destroy", self._on_dialog_destroy)

    def _on_dialog_destroy(self, dialog):
        if getattr(self, "_status_timer_id", None):
            GLib.source_remove(self._status_timer_id)
            self._status_timer_id = None

    def _check_daemon_status(self):
        resp = send_ipc_command("STATUS")
        if resp:
            try:
                info = json.loads(resp)
                if info.get("paused"):
                    state_str = "<span color='#e6a100'>⏸ Paused</span>"
                elif info.get("auto_change"):
                    rem = info.get("seconds_until_next")
                    if rem is not None:
                        mins, secs = divmod(rem, 60)
                        state_str = f"<span color='#779933'>● Active (Next in {mins}m {secs:02d}s)</span>"
                    else:
                        state_str = "<span color='#779933'>● Active (Daemon Running)</span>"
                else:
                    state_str = "<span color='#888888'>○ Idle (Slideshow Off)</span>"
                self.lbl_daemon_status.set_markup(f"<b>Service:</b> {state_str}")
                self.btn_daemon_action.set_label("Restart")
                self.btn_daemon_action.set_tooltip_text("Restart background rotation daemon")
            except Exception:
                self.lbl_daemon_status.set_markup("<b>Service:</b> <span color='#779933'>● Active (Daemon Running)</span>")
                self.btn_daemon_action.set_label("Restart")
        else:
            self.lbl_daemon_status.set_markup("<b>Service:</b> <span color='#d9534f'>○ Inactive (Daemon Not Running)</span>")
            self.btn_daemon_action.set_label("Start Service")
            self.btn_daemon_action.set_tooltip_text("Start background rotation daemon now")
        return True

    def _on_daemon_action_clicked(self, btn):
        btn.set_sensitive(False)
        def task():
            if is_daemon_running():
                restart_daemon()
            else:
                start_daemon()
            GLib.idle_add(self._on_daemon_action_finished)
        self.parent_window.thread_pool.submit(task)

    def _on_daemon_action_finished(self):
        self.btn_daemon_action.set_sensitive(True)
        self._check_daemon_status()

    def _on_auto_toggled(self, switch, state):
        self.engine.config["auto_change"] = state
        self.engine.save_config()

        if state:
            if not is_daemon_running():
                self.parent_window.thread_pool.submit(start_daemon)
            else:
                send_ipc_command("RELOAD")
        else:
            send_ipc_command("RELOAD")

        GLib.timeout_add(300, self._check_daemon_status)

    def _on_interval_changed(self, combo):
        try:
            mins = int(combo.get_active_id())
            self.engine.config["interval_minutes"] = mins
            self.engine.save_config()
            if self.engine.config.get("auto_change", False) and not is_daemon_running():
                self.parent_window.thread_pool.submit(start_daemon)
            else:
                send_ipc_command("RELOAD")
            GLib.timeout_add(200, self._check_daemon_status)
        except Exception:
            pass

    def _on_order_changed(self, combo):
        self.engine.config["random_order"] = (combo.get_active_id() == "random")
        self.engine.save_config()
        send_ipc_command("RELOAD")
        GLib.timeout_add(200, self._check_daemon_status)

    def _on_notify_toggled(self, chk):
        self.engine.config["notify"] = chk.get_active()
        self.engine.save_config()
        send_ipc_command("RELOAD")

    def _on_tray_toggled(self, chk):
        enabled = chk.get_active()
        self.engine.config["tray_enabled"] = enabled
        self.engine.save_config()
        if hasattr(self.parent_window, "tray_icon") and self.parent_window.tray_icon:
            self.parent_window.tray_icon.set_visible(enabled)
        elif enabled and hasattr(self.parent_window, "_init_tray"):
            self.parent_window._init_tray()

    def _on_min_tray_toggled(self, chk):
        self.engine.config["minimize_to_tray"] = chk.get_active()
        self.engine.save_config()

    def _on_autostart_toggled(self, chk):
        enabled = chk.get_active()
        self.engine.config["autostart"] = enabled
        self.engine.save_config()

        os.makedirs(AUTOSTART_DIR, exist_ok=True)
        if enabled:
            launcher = get_launcher_path()
            autostart_content = f"""[Desktop Entry]
Type=Application
Name=LeafPaper Daemon
Comment=Background wallpaper rotation for Moksha Desktop
Exec={launcher} --daemon
Icon=bodhi-wallpaper
Terminal=false
Categories=Utility;Settings;
X-Moksha-Autostart=true
StartupNotify=false
"""
            with open(AUTOSTART_FILE, "w", encoding="utf-8") as f:
                f.write(autostart_content)
            if self.engine.config.get("auto_change", False) and not is_daemon_running():
                self.parent_window.thread_pool.submit(start_daemon)
        else:
            if os.path.exists(AUTOSTART_FILE):
                try:
                    os.remove(AUTOSTART_FILE)
                except Exception:
                    pass
        GLib.timeout_add(200, self._check_daemon_status)


def main():
    start_prefs = "--preferences" in sys.argv
    win = BodhiWallpaperWindow(start_in_prefs=start_prefs)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
