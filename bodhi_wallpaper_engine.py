#!/usr/bin/env python3
"""
Bodhi Wallpaper Engine - Core Moksha / Enlightenment Desktop Integration
Provides wallpaper scanning, metadata extraction, EDJ compilation,
caching, wallpaper applying, configuration persistence, and IPC.
"""

import os
import sys
import json
import time
import io
import glob
import hashlib
import tempfile
import socket
import subprocess
import struct
import zlib
import shutil
from pathlib import Path
from PIL import Image

# XDG Base Directories
CONFIG_DIR = os.path.expanduser("~/.config/bodhi-wallpaper")
CACHE_DIR = os.path.expanduser("~/.cache/bodhi-wallpaper")
THUMBS_DIR = os.path.join(CACHE_DIR, "thumbnails")
DATA_DIR = os.path.expanduser("~/.local/share/bodhi-wallpaper")
EDJ_CACHE_DIR = os.path.join(DATA_DIR, "edj_cache")
MOKSHA_BG_DIR = os.path.expanduser("~/.e/e/backgrounds")

CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
SOCKET_FILE = f"/tmp/bodhi-wallpaper-{os.getuid()}.sock"
LOCK_FILE = f"/tmp/bodhi-wallpaper-daemon-{os.getuid()}.lock"

# Default wallpaper paths on Bodhi Linux
DEFAULT_WALLPAPER_DIRS = [
    "/usr/share/enlightenment/data/backgrounds",
    "/usr/share/backgrounds",
    os.path.expanduser("~/Pictures/Wallpapers"),
    os.path.expanduser("~/.e/e/backgrounds"),
    os.path.expanduser("~/Pictures")
]

SUPPORTED_EXTENSIONS = {'.edj', '.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'}

DEFAULT_CONFIG = {
    "folders": [
        "/usr/share/enlightenment/data/backgrounds",
        "/usr/share/backgrounds",
        os.path.expanduser("~/Pictures/Wallpapers"),
        os.path.expanduser("~/.e/e/backgrounds")
    ],
    "favorites": [],
    "history": [],
    "current_wallpaper": "",
    "style": "zoom",  # zoom, fit, stretch, center, tile
    "auto_change": False,
    "interval_minutes": 15,
    "random_order": True,
    "notify": True,
    "autostart": False,
    "tray_enabled": True,
    "minimize_to_tray": True,
    "target_desktop": "all"  # 'all' or 'current'
}


class BodhiWallpaperEngine:
    def __init__(self):
        self._init_directories()
        self.config = self.load_config()
        self._cached_desktops = None
        self._cached_screens = None

    def _init_directories(self):
        for d in [CONFIG_DIR, CACHE_DIR, THUMBS_DIR, DATA_DIR, EDJ_CACHE_DIR, MOKSHA_BG_DIR]:
            os.makedirs(d, exist_ok=True)

    def load_config(self):
        config = dict(DEFAULT_CONFIG)
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    config.update(saved)
            except Exception as e:
                print(f"[Engine] Warning: Failed to parse config file: {e}", file=sys.stderr)
        return config

    def save_config(self):
        try:
            temp_file = CONFIG_FILE + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
            os.replace(temp_file, CONFIG_FILE)
        except Exception as e:
            print(f"[Engine] Error saving config: {e}", file=sys.stderr)

    def ensure_moksha_msgbus(self):
        """Ensure Moksha DBus msgbus module is loaded and enabled."""
        try:
            subprocess.run(["enlightenment_remote", "-module-load", "msgbus"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            subprocess.run(["enlightenment_remote", "-module-enable", "msgbus"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        except Exception as e:
            print(f"[Engine] Warning ensuring msgbus: {e}", file=sys.stderr)

    def get_desktops_and_screens(self, refresh=False):
        """Returns (desk_x_count, desk_y_count, screen_count)."""
        if not refresh and self._cached_desktops is not None and self._cached_screens is not None:
            return (*self._cached_desktops, self._cached_screens)

        self.ensure_moksha_msgbus()
        dx, dy = 1, 1
        try:
            res = subprocess.run(["enlightenment_remote", "-desktops-get"],
                                 capture_output=True, text=True, timeout=2)
            parts = res.stdout.strip().split()
            if len(parts) >= 2:
                dx, dy = int(parts[0]), int(parts[1])
        except Exception:
            pass

        screens = 1
        try:
            res = subprocess.run(["xrandr", "-q"], capture_output=True, text=True, timeout=2)
            screens = len([line for line in res.stdout.splitlines() if " connected" in line]) or 1
        except Exception:
            pass

        self._cached_desktops = (dx, dy)
        self._cached_screens = screens
        return dx, dy, screens

    def scan_wallpapers(self, folder=None):
        """Scans folder or all configured folders for wallpapers."""
        folders = [folder] if folder else self.config.get("folders", [])
        wallpapers = []
        seen = set()

        for fld in folders:
            expanded = os.path.expanduser(fld)
            if not os.path.isdir(expanded):
                continue

            try:
                for root, _, files in os.walk(expanded):
                    for fname in sorted(files):
                        ext = os.path.splitext(fname)[1].lower()
                        if ext in SUPPORTED_EXTENSIONS:
                            full_path = os.path.join(root, fname)
                            if full_path not in seen:
                                seen.add(full_path)
                                wallpapers.append(full_path)
            except Exception as e:
                print(f"[Engine] Error scanning folder '{fld}': {e}", file=sys.stderr)

        return wallpapers

    def _decode_image_data(self, data):
        """
        Decodes binary image data which may be:
        1. Standard image (JPEG, PNG, WebP, GIF, BMP).
        2. EET internal image format (magic 0xac1dfeed) with zlib raw BGRA/RGBA.
        """
        if not data:
            return None

        # Check for EET magic header: 0xac1dfeed (little-endian)
        if len(data) >= 32:
            magic = struct.unpack('<I', data[:4])[0]
            if magic == 0xac1dfeed:
                try:
                    magic, w, h, alpha, comp, qual, lossy, resv = struct.unpack('<8I', data[:32])
                    if w > 0 and h > 0:
                        payload = data[32:]
                        # If payload starts with JPEG or PNG SOI
                        if payload.startswith(b'\xff\xd8\xff') or payload.startswith(b'\x89PNG\r\n\x1a\n'):
                            return Image.open(io.BytesIO(payload))
                        # Otherwise decompressed zlib raw pixel buffer
                        raw = zlib.decompress(payload)
                        mode = 'RGBA' if alpha else 'RGB'
                        raw_mode = 'BGRA' if alpha else 'BGR'
                        if len(raw) == w * h * 4:
                            return Image.frombytes('RGBA', (w, h), raw, 'raw', 'BGRA')
                        elif len(raw) == w * h * 3:
                            return Image.frombytes('RGB', (w, h), raw, 'raw', 'BGR')
                except Exception:
                    pass

        # Try standard PIL loader
        try:
            return Image.open(io.BytesIO(data))
        except Exception:
            return None

    def _extract_image_from_edj(self, edj_path):
        """
        Extracts the best (largest/main) image from a Moksha .edj file.
        Returns a PIL Image or None.
        """
        try:
            res = subprocess.run(["eet", "-l", edj_path], capture_output=True, text=True, timeout=3)
            keys = [k for k in res.stdout.splitlines() if k.startswith("edje/images/")]
            if not keys:
                return None

            best_img = None
            best_area = 0

            # Scan keys to pick the primary wallpaper image (largest resolution)
            for k in keys:
                extract_proc = subprocess.run(["eet", "-x", edj_path, k], capture_output=True, timeout=3)
                if extract_proc.stdout:
                    img = self._decode_image_data(extract_proc.stdout)
                    if img:
                        area = img.size[0] * img.size[1]
                        if area > best_area:
                            best_area = area
                            best_img = img

            return best_img
        except Exception as e:
            print(f"[Engine] Failed extracting image from {edj_path}: {e}", file=sys.stderr)
            return None

    def get_thumbnail(self, wallpaper_path, size=(240, 150)):
        """
        Returns cached thumbnail path for wallpaper (.edj or image).
        Extracts image on-the-fly and caches it as PNG/JPEG thumbnail.
        """
        if not os.path.exists(wallpaper_path):
            return None

        try:
            mtime = os.path.getmtime(wallpaper_path)
            path_hash = hashlib.md5(f"{wallpaper_path}_{mtime}_{size[0]}x{size[1]}".encode()).hexdigest()
            thumb_path = os.path.join(THUMBS_DIR, f"{path_hash}.jpg")

            if os.path.exists(thumb_path):
                return thumb_path

            # Generate thumbnail
            img = None
            if wallpaper_path.lower().endswith(".edj"):
                img = self._extract_image_from_edj(wallpaper_path)
            else:
                img = Image.open(wallpaper_path)

            if img:
                img = img.convert("RGB")
                # High quality crop & resize thumbnail maintaining aspect ratio
                img.thumbnail(size, Image.Resampling.LANCZOS)
                img.save(thumb_path, "JPEG", quality=85)
                return thumb_path

        except Exception as e:
            print(f"[Engine] Failed generating thumbnail for {wallpaper_path}: {e}", file=sys.stderr)

        return None

    def get_wallpaper_metadata(self, wallpaper_path):
        """Returns details dictionary about the wallpaper."""
        if not os.path.exists(wallpaper_path):
            return None

        filename = os.path.basename(wallpaper_path)
        ext = os.path.splitext(filename)[1].lower()
        size_bytes = os.path.getsize(wallpaper_path)
        size_str = self._format_size(size_bytes)

        width, height = 0, 0
        try:
            if ext == ".edj":
                img = self._extract_image_from_edj(wallpaper_path)
                if img:
                    width, height = img.size
            else:
                with Image.open(wallpaper_path) as img:
                    width, height = img.size
        except Exception:
            pass


        return {
            "name": os.path.splitext(filename)[0].replace("-", " ").replace("_", " "),
            "filename": filename,
            "path": wallpaper_path,
            "format": ext.upper().lstrip("."),
            "width": width,
            "height": height,
            "dimensions": f"{width} × {height}" if width and height else "Unknown",
            "size": size_str,
            "is_edj": ext == ".edj",
            "is_favorite": wallpaper_path in self.config.get("favorites", [])
        }

    def _format_size(self, size_bytes):
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"

    def compile_image_to_edj(self, image_path, style="zoom"):
        """
        Compiles standard image (.jpg, .png, etc.) to Moksha .edj background.
        Caches compiled file so subsequent uses are instantaneous.
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        mtime = os.path.getmtime(image_path)
        content_hash = hashlib.md5(f"{image_path}_{mtime}_{style}".encode()).hexdigest()[:12]
        cached_edj = os.path.join(EDJ_CACHE_DIR, f"wp_{content_hash}_{style}.edj")

        if os.path.exists(cached_edj):
            return cached_edj

        with tempfile.TemporaryDirectory() as tmpdir:
            img = Image.open(image_path).convert("RGB")
            w, h = img.size
            aspect = round(w / h, 9) if h > 0 else 0.0

            tmp_img_name = "image.jpg"
            tmp_img_path = os.path.join(tmpdir, tmp_img_name)
            img.save(tmp_img_path, "JPEG", quality=95)

            # Generate EDC for requested style
            # 4: Zoom/Crop, 2: Fit/Letterbox, 3: Stretch, 1: Center, 0: Tile
            if style == "fit":
                edc_body = f"""
images {{ image: "{tmp_img_name}" LOSSY 92; }}
collections {{
    group {{
        name: "e/desktop/background";
        data {{ item: "style" "2"; item: "noanimation" "1"; }}
        max: {w} {h};
        parts {{
            part {{
                name: "bg";
                mouse_events: 0;
                description {{
                    state: "default" 0.0;
                    aspect: {aspect} {aspect};
                    aspect_preference: BOTH;
                    image {{ normal: "{tmp_img_name}"; scale_hint: STATIC; }}
                }}
            }}
        }}
    }}
}}
"""
            elif style == "stretch":
                edc_body = f"""
images {{ image: "{tmp_img_name}" LOSSY 92; }}
collections {{
    group {{
        name: "e/desktop/background";
        data {{ item: "style" "3"; item: "noanimation" "1"; }}
        max: {w} {h};
        parts {{
            part {{
                name: "bg";
                mouse_events: 0;
                description {{
                    state: "default" 0.0;
                    aspect: 0.0 0.0;
                    aspect_preference: NONE;
                    image {{ normal: "{tmp_img_name}"; scale_hint: STATIC; }}
                }}
            }}
        }}
    }}
}}
"""
            elif style == "center":
                edc_body = f"""
images {{ image: "{tmp_img_name}" LOSSY 92; }}
collections {{
    group {{
        name: "e/desktop/background";
        data {{ item: "style" "1"; item: "noanimation" "1"; }}
        max: {w} {h};
        parts {{
            part {{
                name: "bg";
                mouse_events: 0;
                description {{
                    state: "default" 0.0;
                    min: {w} {h};
                    max: {w} {h};
                    fixed: 1 1;
                    image {{ normal: "{tmp_img_name}"; scale_hint: STATIC; }}
                }}
            }}
        }}
    }}
}}
"""
            elif style == "tile":
                edc_body = f"""
images {{ image: "{tmp_img_name}" LOSSY 92; }}
collections {{
    group {{
        name: "e/desktop/background";
        data {{ item: "style" "0"; item: "noanimation" "1"; }}
        parts {{
            part {{
                name: "bg";
                mouse_events: 0;
                description {{
                    state: "default" 0.0;
                    fill {{
                        size {{
                            relative: 0.0 0.0;
                            offset: {w} {h};
                        }}
                    }}
                    image {{ normal: "{tmp_img_name}"; scale_hint: STATIC; }}
                }}
            }}
        }}
    }}
}}
"""
            else:  # default 'zoom' / style 4
                edc_body = f"""
images {{ image: "{tmp_img_name}" LOSSY 92; }}
collections {{
    group {{
        name: "e/desktop/background";
        data {{ item: "style" "4"; item: "noanimation" "1"; }}
        max: {w} {h};
        parts {{
            part {{
                name: "bg";
                mouse_events: 0;
                description {{
                    state: "default" 0.0;
                    aspect: {aspect} {aspect};
                    aspect_preference: NONE;
                    image {{ normal: "{tmp_img_name}"; scale_hint: STATIC; }}
                }}
            }}
        }}
    }}
}}
"""
            edc_path = os.path.join(tmpdir, "bg.edc")
            tmp_out_edj = os.path.join(tmpdir, "out.edj")
            with open(edc_path, "w", encoding="utf-8") as f:
                f.write(edc_body)

            res = subprocess.run(["edje_cc", "-id", tmpdir, edc_path, tmp_out_edj],
                                 capture_output=True, text=True, timeout=10)
            if res.returncode != 0:
                raise RuntimeError(f"edje_cc compilation failed: {res.stderr}")

            # Move compiled file to cache
            os.replace(tmp_out_edj, cached_edj)

        return cached_edj

    def apply_wallpaper(self, wallpaper_path, style=None, all_desktops=True, notify=None):
        """
        Applies wallpaper to Moksha desktop.
        Automatically converts images to .edj if needed and calls enlightenment_remote.
        """
        if not os.path.exists(wallpaper_path):
            raise FileNotFoundError(f"Wallpaper does not exist: {wallpaper_path}")

        style = style or self.config.get("style", "zoom")
        notify = self.config.get("notify", True) if notify is None else notify

        self.ensure_moksha_msgbus()

        # Determine EDJ path
        if wallpaper_path.lower().endswith(".edj"):
            edj_path = wallpaper_path
        else:
            edj_path = self.compile_image_to_edj(wallpaper_path, style)

        # 1. Set global default background
        subprocess.run(["enlightenment_remote", "-default-bg-set", edj_path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)

        # 2. Apply to screens & virtual desktops
        dx, dy, screens = self.get_desktops_and_screens()
        for x in range(dx):
            for y in range(dy):
                for z in range(screens):
                    subprocess.run(["enlightenment_remote", "-desktop-bg-add", "0", str(z), str(x), str(y), edj_path],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)

        # 3. Update configuration and history
        self.config["current_wallpaper"] = wallpaper_path
        self.config["style"] = style

        history = self.config.get("history", [])
        if wallpaper_path in history:
            history.remove(wallpaper_path)
        history.insert(0, wallpaper_path)
        self.config["history"] = history[:50]  # Keep last 50
        self.save_config()

        # 4. Notify if requested
        if notify:
            name = os.path.splitext(os.path.basename(wallpaper_path))[0].replace("-", " ").replace("_", " ")
            self.send_notification("Wallpaper Changed", f"Now active: {name}", wallpaper_path)

        return True

    def send_notification(self, title, message, icon_path=None):
        """Sends native desktop notification."""
        try:
            import gi
            gi.require_version("Notify", "0.7")
            from gi.repository import Notify
            if not Notify.is_initted():
                Notify.init("Bodhi Wallpaper Changer")
            thumb = self.get_thumbnail(icon_path) if icon_path else None
            notif_icon = thumb if thumb else "preferences-desktop-wallpaper"
            n = Notify.Notification.new(title, message, notif_icon)
            n.set_timeout(3500)
            n.show()
        except Exception:
            # Fallback to notify-send CLI
            try:
                cmd = ["notify-send", "-a", "Bodhi Wallpaper Changer", title, message]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except Exception:
                pass

    def toggle_favorite(self, wallpaper_path):
        favorites = self.config.get("favorites", [])
        if wallpaper_path in favorites:
            favorites.remove(wallpaper_path)
            is_fav = False
        else:
            favorites.append(wallpaper_path)
            is_fav = True
        self.config["favorites"] = favorites
        self.save_config()
        return is_fav

    def add_folder(self, folder_path):
        folder_path = os.path.abspath(os.path.expanduser(folder_path))
        folders = self.config.get("folders", [])
        if folder_path not in folders and os.path.isdir(folder_path):
            folders.append(folder_path)
            self.config["folders"] = folders
            self.save_config()
            return True
        return False

    def remove_folder(self, folder_path):
        folder_path = os.path.abspath(os.path.expanduser(folder_path))
        folders = self.config.get("folders", [])
        if folder_path in folders:
            folders.remove(folder_path)
            self.config["folders"] = folders
            self.save_config()
            return True
        return False

    def get_next_wallpaper(self, forward=True):
        wallpapers = self.scan_wallpapers()
        if not wallpapers:
            return None

        current = self.config.get("current_wallpaper", "")
        try:
            idx = wallpapers.index(current)
            next_idx = (idx + 1) if forward else (idx - 1)
            next_idx = next_idx % len(wallpapers)
        except ValueError:
            next_idx = 0

        return wallpapers[next_idx]

    def get_random_wallpaper(self):
        import random
        wallpapers = self.scan_wallpapers()
        if not wallpapers:
            return None

        current = self.config.get("current_wallpaper", "")
        candidates = [w for w in wallpapers if w != current]
        return random.choice(candidates) if candidates else wallpapers[0]


# IPC Communication helpers
def send_ipc_command(command, timeout=2.0):
    """
    Sends a string command over the Unix domain socket to the daemon.
    Returns response string or None if daemon is not running.
    """
    if not os.path.exists(SOCKET_FILE):
        return None

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(SOCKET_FILE)
            client.sendall((command.strip() + "\n").encode("utf-8"))
            response = client.recv(4096).decode("utf-8").strip()
            return response
    except Exception:
        return None


def is_daemon_running():
    """Checks whether the background wallpaper daemon is responsive."""
    return send_ipc_command("PING") == "PONG"


def get_launcher_path():
    """Detects the installed or local executable path for bodhi-wallpaper."""
    user_bin = os.path.expanduser("~/.local/bin/bodhi-wallpaper")
    if os.path.exists(user_bin) and os.access(user_bin, os.X_OK):
        return user_bin

    which_bin = shutil.which("bodhi-wallpaper")
    if which_bin and os.access(which_bin, os.X_OK):
        return which_bin

    script_dir = os.path.dirname(os.path.abspath(__file__))
    local_launcher = os.path.join(script_dir, "bodhi-wallpaper")
    if os.path.exists(local_launcher) and os.access(local_launcher, os.X_OK):
        return local_launcher

    return "bodhi-wallpaper"


def start_daemon():
    """Starts the background rotation daemon detached from parent."""
    if is_daemon_running():
        return True

    launcher = get_launcher_path()
    cmd = [launcher, "--daemon"]

    # Fallback to direct python script if launcher binary is not directly executable
    if not os.path.exists(launcher) or not os.access(launcher, os.X_OK):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        daemon_script = os.path.join(script_dir, "bodhi_wallpaper_daemon.py")
        if os.path.exists(daemon_script):
            cmd = [sys.executable, daemon_script]

    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True
        )
        for _ in range(30):
            time.sleep(0.1)
            if is_daemon_running():
                return True
        return is_daemon_running()
    except Exception as e:
        print(f"[Engine] Failed to start daemon: {e}", file=sys.stderr)
        return False


def stop_daemon():
    """Stops the background rotation daemon."""
    if not is_daemon_running():
        return True

    send_ipc_command("STOP")
    for _ in range(25):
        time.sleep(0.1)
        if not is_daemon_running():
            return True
    return False


def restart_daemon():
    """Restarts the background rotation daemon."""
    stop_daemon()
    time.sleep(0.2)
    return start_daemon()


if __name__ == "__main__":
    engine = BodhiWallpaperEngine()
    print("Moksha Desktops and screens:", engine.get_desktops_and_screens())
    wallpapers = engine.scan_wallpapers()
    print(f"Found {len(wallpapers)} wallpapers across configured directories.")
    if wallpapers:
        print("Sample wallpaper:", wallpapers[0])
        print("Metadata:", engine.get_wallpaper_metadata(wallpapers[0]))
