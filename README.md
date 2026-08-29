# 🍃 LeafPaper - Bodhi Wallpaper Changer

A high-performance, modern wallpaper manager, multi-source online downloader, and automated slideshow application tailored specifically for **Bodhi Linux** and the **Moksha Desktop** (Enlightenment foundation).

![App Icon](assets/bodhi-wallpaper.png)

---

## 🌟 Key Features

- **Native Moksha Desktop Engine Integration**:
  - Direct support for official Bodhi Linux `.edj` backgrounds (`/usr/share/enlightenment/data/backgrounds/`).
  - Automatic compilation of standard images (`JPEG`, `PNG`, `WebP`, `BMP`) into hardware-accelerated Moksha `.edj` themes via `edje_cc`.
  - Multi-desktop grid support (`X × Y` virtual desktops) and multi-monitor setups.
  - Automatic DBus `msgbus` initialization and instant wallpaper switching without restarting Moksha.
- **5 Custom Wallpaper Scaling Modes**:
  - **Zoom / Fill (Crop)**: Fills the entire display while maintaining aspect ratio (default).
  - **Fit Screen (Letterbox)**: Shows the entire image with elegant black letterboxing.
  - **Stretch**: Stretches the image to fill the exact screen geometry.
  - **Centered (1:1)**: Centers the image at native pixel resolution.
  - **Tiled**: Repeats the wallpaper pattern across the workspace.
- **Internet Wallpaper Downloader & Multi-Category Browser**:
  - **6 Built-in Online Providers**:
    - **Wallhaven**: Over 500,000+ curated 4K/2K/1080p desktop wallpapers with resolution filters (`1080p+`, `2K+`, `4K+`, `Any`) and sorting (`Top Rated`, `Hot`, `Latest`, `Random`).
    - **Bing Daily Spotlight**: Daily high-resolution curated photography with official descriptions.
    - **NASA Astronomy (APOD)**: Daily deep-space astrophotography from NASA Hubble/JWST.
    - **Picsum Photos**: Curated high-resolution photography (up to 5K, 5000×3333) with author attribution.
    - **Wikimedia Commons Featured**: Museum-grade, award-winning public domain photography (up to 8K+, 7000×5000+).
    - **Openverse**: Global search across 700+ million Creative Commons images (maintained by the WordPress Foundation).
  - **10 Categorized Presets**:
    - 🏔 Nature & Landscapes
    - 🌌 Space & Astronomy
    - 🕶 Minimalist & Dark
    - 🌆 Cyberpunk & Sci-Fi
    - 🎨 Anime & Digital Art
    - 🏛 City & Architecture
    - 🐾 Animals & Wildlife
    - 🏎 Cars & Supercars
    - 🏰 Fantasy & Concept Art
    - 🌀 Abstract & 3D
    - 🔍 Custom keyword search (e.g. "forest", "rain", "neon", "sunset")
  - **One-Click Download & Apply**: Downloads the original image directly into `~/Pictures/Wallpapers/Online/`, compiles it into a Moksha `.edj` theme, and sets it on your desktop immediately.
  - **Save to Library**: Saves online wallpapers directly to your permanent local collection.
- **Modern GTK3 Graphical Interface**:
  - Visual gallery with asynchronous background thumbnail rendering.
  - Live search filter and category navigation (*Bodhi Backgrounds*, *User Wallpapers*, *Discover Online*, *Favorites*, *Recent History*, and *Custom Folders*).
  - Inspector pane with live high-resolution preview and metadata (dimensions, file size, format, path).
  - Drag-and-drop support: drag pictures or folders from Thunar/file manager directly into the app window.
- **Automated Slideshow Daemon & System Tray Applet**:
  - Background timer daemon for scheduled rotation (intervals from 1 minute to 24 hours).
  - Random / Shuffle or Sequential rotation order.
  - System tray applet (`AppIndicator3` / `Gtk.StatusIcon`) with quick controls: *Next*, *Previous*, *Random*, *Pause / Resume*.
  - Native desktop notifications on wallpaper change.
  - Optional autostart on system login.
- **Comprehensive Command-Line Interface (CLI)**:
  - Full CLI control for terminal enthusiasts, scripts, or hotkey binding (`bodhi-wallpaper --next`, `--random`, `--bing-daily`, `--online-category <cat>`).

---

## 📂 Project Structure

```text
/home/mudhitha/System/wallpapper/
├── bodhi-wallpaper              # Unified master CLI & application launcher
├── bodhi_wallpaper_gui.py       # Modern GTK3 Graphical User Interface
├── bodhi_wallpaper_engine.py    # Moksha DBus engine, EDJ compiler, caching & IPC
├── bodhi_wallpaper_daemon.py    # Background rotation timer & IPC socket service
├── bodhi_wallpaper_tray.py      # Moksha system tray status indicator
├── assets/
│   ├── bodhi-wallpaper.svg      # Vector SVG application emblem
│   ├── bodhi-wallpaper.png      # 256x256 application icon
│   └── bodhi-wallpaper-tray.png # 24x24 tray icon
├── bodhi-wallpaper.desktop      # Desktop entry with desktop actions
├── bodhi-wallpaper-autostart.desktop # XDG autostart entry for daemon
├── install.sh                   # Local user and system installer
├── uninstall.sh                 # Uninstaller script
├── build-deb.sh                 # Debian package builder
└── README.md                    # Documentation
```

---

## 🚀 Installation

### Option 1: Quick Local User Install (No Root / Sudo Required)
```bash
cd /home/mudhitha/System/wallpapper
./install.sh
```
This installs the executable to `~/.local/bin/bodhi-wallpaper`, creates the application menu entry in `~/.local/share/applications/`, and registers the icons.

### Option 2: System-Wide Install (All Users)
```bash
sudo ./install.sh --system
```

### Option 3: Install via Debian Package (.deb)
Build and install a clean Debian package:
```bash
./build-deb.sh
sudo dpkg -i bodhi-wallpaper-changer_1.0-1_all.deb
```

---

## 💻 Usage

### 1. Launching the GUI
Launch from the Bodhi Application Menu (**Applications → Settings → Bodhi Wallpaper Changer**) or via terminal:
```bash
bodhi-wallpaper
```

### 2. Command-Line Controls
| Command | Description |
| :--- | :--- |
| `bodhi-wallpaper` | Launch the GTK3 GUI manager |
| `bodhi-wallpaper --next` | Switch to the next wallpaper |
| `bodhi-wallpaper --prev` | Switch to the previous wallpaper |
| `bodhi-wallpaper --random` | Switch to a random wallpaper |
| `bodhi-wallpaper --set <file>` | Apply a specific wallpaper image or `.edj` |
| `bodhi-wallpaper --set <file> --style fit` | Apply wallpaper with specific scaling (`zoom`, `fit`, `stretch`, `center`, `tile`) |
| `bodhi-wallpaper --daemon` | Start background rotation daemon |
| `bodhi-wallpaper --tray` | Start the system tray applet |
| `bodhi-wallpaper --pause` | Pause the slideshow rotation |
| `bodhi-wallpaper --resume` | Resume the slideshow rotation |
| `bodhi-wallpaper --status` | Display current wallpaper and daemon status |
| `bodhi-wallpaper --list` | List all discovered wallpapers |
| `bodhi-wallpaper --bing-daily` | Download and apply today's Bing Daily spotlight wallpaper |
| `bodhi-wallpaper --picsum` | Download and apply a curated 5K photography wallpaper from Picsum |
| `bodhi-wallpaper --wikimedia` | Download and apply an award-winning 8K featured picture from Wikimedia |
| `bodhi-wallpaper --openverse <query>` | Search and apply wallpaper from 700M+ Openverse Creative Commons library |
| `bodhi-wallpaper --online-category <cat>` | Download & apply wallpaper from category (`nature`, `space`, `cyberpunk`, `anime`, etc.) |
| `bodhi-wallpaper --online-search <query>` | Search Wallhaven and apply/download matching wallpaper |
| `bodhi-wallpaper --add-folder <path>` | Add a custom folder to wallpaper sources |
| `bodhi-wallpaper --remove-folder <path>` | Remove a folder from sources |

---

## ⚙️ Configuration & Storage Paths

- **Configuration File**: `~/.config/bodhi-wallpaper/config.json`
- **Thumbnail Cache**: `~/.cache/bodhi-wallpaper/thumbnails/`
- **Compiled EDJ Cache**: `~/.local/share/bodhi-wallpaper/edj_cache/`
- **IPC Domain Socket**: `/tmp/bodhi-wallpaper-<uid>.sock`
- **Moksha Wallpapers**: `~/.e/e/backgrounds/` and `/usr/share/enlightenment/data/backgrounds/`

---

## ⌨️ Moksha Keyboard Shortcut Integration
You can easily bind wallpaper changing to keyboard shortcuts in Moksha:
1. Open **Settings Panel → Input → Key Bindings**.
2. Click **Add**.
3. Set action to **Launch Command** and enter:
   - `bodhi-wallpaper --next` (e.g. `Ctrl+Alt+Right` or `Super+W`)
   - `bodhi-wallpaper --random` (e.g. `Ctrl+Alt+R`)
