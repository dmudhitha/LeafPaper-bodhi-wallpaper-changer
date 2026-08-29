#!/usr/bin/env python3
"""
Bodhi Wallpaper Daemon - Background Slideshow & IPC Service
Manages automatic wallpaper rotation and listens on a local Unix socket
for commands from the CLI, Tray applet, or GUI.
"""

import os
import sys
import time
import socket
import select
import signal
import json
import threading
from bodhi_wallpaper_engine import (
    BodhiWallpaperEngine,
    SOCKET_FILE,
    LOCK_FILE,
    send_ipc_command
)


class BodhiWallpaperDaemon:
    def __init__(self):
        self.engine = BodhiWallpaperEngine()
        self.running = False
        self.paused = False
        self.last_change_time = time.time()
        self.server_socket = None
        self.timer_thread = None
        self._lock_fd = None

    def acquire_lock(self):
        """Ensure single instance of the daemon runs."""
        try:
            import fcntl
            self._lock_fd = open(LOCK_FILE, "w")
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_fd.write(str(os.getpid()))
            self._lock_fd.flush()
            return True
        except (IOError, BlockingIOError):
            return False

    def release_lock(self):
        if self._lock_fd:
            try:
                import fcntl
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                self._lock_fd.close()
            except Exception:
                pass
            if os.path.exists(LOCK_FILE):
                try:
                    os.remove(LOCK_FILE)
                except Exception:
                    pass

    def start(self):
        # Check if already running via IPC ping
        status = send_ipc_command("PING")
        if status == "PONG":
            print("[Daemon] Bodhi Wallpaper Daemon is already running.", file=sys.stderr)
            sys.exit(0)

        if not self.acquire_lock():
            print("[Daemon] Could not acquire lock file. Another instance might be running.", file=sys.stderr)
            sys.exit(1)

        # Setup signals
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGHUP, self._handle_signal)

        # Setup socket
        if os.path.exists(SOCKET_FILE):
            try:
                os.remove(SOCKET_FILE)
            except Exception:
                pass

        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.bind(SOCKET_FILE)
        self.server_socket.listen(5)
        # Ensure only user can access socket
        os.chmod(SOCKET_FILE, 0o600)

        self.running = True
        self.last_change_time = time.time()

        # Start timer thread
        self.timer_thread = threading.Thread(target=self._slideshow_loop, daemon=True)
        self.timer_thread.start()

        print(f"[Daemon] Bodhi Wallpaper Daemon started (PID: {os.getpid()})")
        self._ipc_loop()

    def _handle_signal(self, signum, frame):
        if signum in (signal.SIGINT, signal.SIGTERM):
            print("[Daemon] Received termination signal. Exiting...")
            self.stop()
        elif signum == signal.SIGHUP:
            print("[Daemon] Received SIGHUP. Reloading configuration...")
            self.engine.config = self.engine.load_config()

    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
        if os.path.exists(SOCKET_FILE):
            try:
                os.remove(SOCKET_FILE)
            except Exception:
                pass
        self.release_lock()
        sys.exit(0)

    def _slideshow_loop(self):
        """Thread that handles automated timed wallpaper changes."""
        while self.running:
            try:
                time.sleep(1)
                if not self.running:
                    break

                config = self.engine.config
                auto_change = config.get("auto_change", False)
                interval_seconds = max(10, int(config.get("interval_minutes", 15)) * 60)

                if auto_change and not self.paused:
                    elapsed = time.time() - self.last_change_time
                    if elapsed >= interval_seconds:
                        self._trigger_change(random_pick=config.get("random_order", True))
            except Exception as e:
                print(f"[Daemon] Error in slideshow loop: {e}", file=sys.stderr)
                time.sleep(5)

    def _trigger_change(self, random_pick=True):
        """Picks and applies next or random wallpaper."""
        try:
            if random_pick:
                target = self.engine.get_random_wallpaper()
            else:
                target = self.engine.get_next_wallpaper(forward=True)

            if target:
                style = self.engine.config.get("style", "zoom")
                notify = self.engine.config.get("notify", True)
                self.engine.apply_wallpaper(target, style=style, notify=notify)
                self.last_change_time = time.time()
                print(f"[Daemon] Applied wallpaper: {os.path.basename(target)}")
        except Exception as e:
            print(f"[Daemon] Failed to change wallpaper: {e}", file=sys.stderr)

    def _ipc_loop(self):
        """Main thread handles incoming IPC requests over Unix socket."""
        while self.running:
            try:
                readable, _, _ = select.select([self.server_socket], [], [], 1.0)
                if not readable:
                    continue

                client, _ = self.server_socket.accept()
                threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()
            except Exception as e:
                if self.running:
                    print(f"[Daemon] Error in IPC loop: {e}", file=sys.stderr)

    def _handle_client(self, client):
        try:
            client.settimeout(3.0)
            data = client.recv(4096).decode("utf-8").strip()
            if not data:
                return

            response = self._process_command(data)
            client.sendall((response + "\n").encode("utf-8"))
        except Exception as e:
            print(f"[Daemon] Client handling error: {e}", file=sys.stderr)
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _process_command(self, cmd_line):
        parts = cmd_line.split(maxsplit=1)
        cmd = parts[0].upper()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "PING":
            return "PONG"

        elif cmd == "NEXT":
            target = self.engine.get_next_wallpaper(forward=True)
            if target:
                self.engine.apply_wallpaper(target)
                self.last_change_time = time.time()
                return f"OK {target}"
            return "ERROR No wallpapers found"

        elif cmd == "PREV":
            target = self.engine.get_next_wallpaper(forward=False)
            if target:
                self.engine.apply_wallpaper(target)
                self.last_change_time = time.time()
                return f"OK {target}"
            return "ERROR No wallpapers found"

        elif cmd == "RANDOM":
            target = self.engine.get_random_wallpaper()
            if target:
                self.engine.apply_wallpaper(target)
                self.last_change_time = time.time()
                return f"OK {target}"
            return "ERROR No wallpapers found"

        elif cmd == "SET":
            if not arg:
                return "ERROR Missing wallpaper path"
            subparts = arg.split(maxsplit=1)
            target_path = os.path.abspath(os.path.expanduser(subparts[0]))
            style = subparts[1] if len(subparts) > 1 else self.engine.config.get("style", "zoom")
            try:
                self.engine.apply_wallpaper(target_path, style=style)
                self.last_change_time = time.time()
                return f"OK {target_path}"
            except Exception as e:
                return f"ERROR {e}"

        elif cmd == "PAUSE":
            self.paused = True
            return "OK PAUSED"

        elif cmd == "RESUME":
            self.paused = False
            self.last_change_time = time.time()
            return "OK RESUMED"

        elif cmd == "TOGGLE_PAUSE":
            self.paused = not self.paused
            if not self.paused:
                self.last_change_time = time.time()
            return f"OK {'PAUSED' if self.paused else 'RESUMED'}"

        elif cmd == "STATUS":
            self.engine.config = self.engine.load_config()
            interval_sec = int(self.engine.config.get("interval_minutes", 15)) * 60
            remaining = max(0, int(interval_sec - (time.time() - self.last_change_time)))
            info = {
                "running": True,
                "paused": self.paused,
                "current": self.engine.config.get("current_wallpaper", ""),
                "auto_change": self.engine.config.get("auto_change", False),
                "interval_minutes": self.engine.config.get("interval_minutes", 15),
                "seconds_until_next": remaining if self.engine.config.get("auto_change") and not self.paused else None,
                "random_order": self.engine.config.get("random_order", True),
                "style": self.engine.config.get("style", "zoom")
            }
            return json.dumps(info)

        elif cmd == "RELOAD":
            self.engine.config = self.engine.load_config()
            return "OK RELOADED"

        elif cmd in ("STOP", "QUIT"):
            threading.Thread(target=self.stop, daemon=True).start()
            return "OK STOPPING"

        return f"ERROR Unknown command: {cmd}"


if __name__ == "__main__":
    daemon = BodhiWallpaperDaemon()
    daemon.start()
