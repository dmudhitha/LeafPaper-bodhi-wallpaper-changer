#!/usr/bin/env python3
"""
Bodhi Wallpaper Online - Internet Wallpaper Downloader & Provider Engine
Provides multi-source online wallpaper search and download capabilities from:
1. Wallhaven (500k+ high-resolution 4K/2K/1080p wallpapers, categories, tags, and filters)
2. Bing Daily Spotlight (Daily curated high-resolution photography)
3. NASA Astronomy Picture of the Day (APOD) (Deep-space imagery & astrophotography)
"""

import os
import sys
import json
import hashlib
import urllib.request
import urllib.parse
from pathlib import Path

CACHE_DIR = os.path.expanduser("~/.cache/bodhi-wallpaper")
ONLINE_THUMBS_DIR = os.path.join(CACHE_DIR, "online_thumbs")
DOWNLOADS_DIR = os.path.expanduser("~/Pictures/Wallpapers/Online")

USER_AGENT = "LeafPaper/1.0 (https://github.com/dmudhitha/LeafPaper-bodhi-wallpaper-changer; contact@bodhi.org)"

# Category Presets for Wallhaven
CATEGORY_PRESETS = {
    "nature": {"query": "nature", "categories": "100", "label": "🏔 Nature & Landscapes"},
    "space": {"query": "space", "categories": "100", "label": "🌌 Space & Astronomy"},
    "minimalism": {"query": "minimalism", "categories": "100", "label": "🕶 Minimalist & Dark"},
    "cyberpunk": {"query": "cyberpunk", "categories": "110", "label": "🌆 Cyberpunk & Sci-Fi"},
    "anime": {"query": "anime", "categories": "010", "label": "🎨 Anime & Digital Art"},
    "architecture": {"query": "architecture", "categories": "100", "label": "🏛 City & Architecture"},
    "animals": {"query": "animals", "categories": "100", "label": "🐾 Animals & Wildlife"},
    "cars": {"query": "cars", "categories": "100", "label": "🏎 Cars & Supercars"},
    "fantasy": {"query": "fantasy", "categories": "110", "label": "🏰 Fantasy & Concept Art"},
    "abstract": {"query": "abstract", "categories": "100", "label": "🌀 Abstract & 3D"}
}


class OnlineWallpaperManager:
    def __init__(self):
        os.makedirs(ONLINE_THUMBS_DIR, exist_ok=True)
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)

    def _get_request(self, url):
        return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    def search_wallhaven(self, query=None, category_key=None, resolution=None, sorting="toplist", page=1):
        """
        Searches Wallhaven for wallpapers matching the parameters.
        Returns a list of standardized wallpaper item dictionaries.
        """
        base_url = "https://wallhaven.cc/api/v1/search"
        params = {
            "purity": "100",  # Safe for work strictly enforced
            "sorting": sorting,
            "page": str(page)
        }

        # Resolve category or query
        if category_key and category_key in CATEGORY_PRESETS:
            preset = CATEGORY_PRESETS[category_key]
            params["categories"] = preset["categories"]
            params["q"] = preset["query"]
        else:
            params["categories"] = "111"
            if query:
                params["q"] = query

        # Minimum resolution filter
        if resolution and resolution != "any":
            params["atleast"] = resolution

        url = f"{base_url}?{urllib.parse.urlencode(params)}"

        items = []
        try:
            req = self._get_request(url)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for entry in data.get("data", []):
                wall_id = entry.get("id", "")
                res_str = entry.get("resolution", "Unknown")
                category_name = entry.get("category", "general").capitalize()

                items.append({
                    "id": f"wh_{wall_id}",
                    "title": f"Wallhaven {wall_id}",
                    "provider": "Wallhaven",
                    "category": category_name,
                    "resolution": res_str,
                    "file_size": self._format_size(entry.get("file_size", 0)),
                    "format": entry.get("file_type", "image/jpeg").split("/")[-1].upper(),
                    "thumb_url": entry.get("thumbs", {}).get("small", ""),
                    "full_url": entry.get("path", ""),
                    "source_url": entry.get("url", ""),
                    "filename": f"wallhaven_{wall_id}.{entry.get('file_type', 'image/jpeg').split('/')[-1]}"
                })
        except Exception as e:
            print(f"[Online] Error fetching from Wallhaven: {e}", file=sys.stderr)

        return items

    def fetch_bing_daily(self, count=8):
        """
        Fetches the latest Bing Daily wallpapers with high-resolution photography.
        """
        url = f"https://www.bing.com/HPImageArchive.aspx?format=js&idx=0&n={min(count, 8)}&mkt=en-US"
        items = []
        try:
            req = self._get_request(url)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for entry in data.get("images", []):
                url_base = entry.get("urlbase", "")
                if url_base:
                    full_url = f"https://www.bing.com{url_base}_UHD.jpg"
                    thumb_url = f"https://www.bing.com{url_base}_400x240.jpg"
                else:
                    full_url = f"https://www.bing.com{entry.get('url')}"
                    thumb_url = full_url

                raw_title = entry.get("title") or entry.get("copyright") or "Bing Daily"
                title = raw_title.split("(")[0].strip()
                date_str = entry.get("enddate", "")
                clean_id = hashlib.md5(full_url.encode()).hexdigest()[:8]

                items.append({
                    "id": f"bing_{clean_id}",
                    "title": title,
                    "provider": "Bing Daily",
                    "category": "Daily Spotlight",
                    "resolution": "3840 × 2160 (UHD)" if "_UHD" in full_url else "1920 × 1080",
                    "file_size": "~ 2.5 MB",
                    "format": "JPG",
                    "thumb_url": thumb_url,
                    "full_url": full_url,
                    "source_url": "https://www.bing.com",
                    "filename": f"bing_{date_str}_{clean_id}.jpg"
                })
        except Exception as e:
            print(f"[Online] Error fetching Bing wallpapers: {e}", file=sys.stderr)

        return items

    def fetch_nasa_apod(self, count=8):
        """
        Fetches recent NASA Astronomy Pictures of the Day (APOD).
        """
        url = f"https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY&count={min(count, 12)}"
        items = []
        try:
            req = self._get_request(url)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for entry in data:
                if entry.get("media_type") != "image":
                    continue

                full_url = entry.get("hdurl") or entry.get("url")
                thumb_url = entry.get("url") or full_url
                title = entry.get("title", "NASA Astronomy")
                date_str = entry.get("date", "")
                clean_id = hashlib.md5(full_url.encode()).hexdigest()[:8]

                items.append({
                    "id": f"nasa_{clean_id}",
                    "title": title,
                    "provider": "NASA Astronomy",
                    "category": "Astrophotography",
                    "resolution": "High-Res HD",
                    "file_size": "Variable",
                    "format": full_url.split(".")[-1].upper() if "." in full_url else "JPG",
                    "thumb_url": thumb_url,
                    "full_url": full_url,
                    "source_url": "https://apod.nasa.gov",
                    "filename": f"nasa_{date_str}_{clean_id}.jpg"
                })
        except Exception as e:
            print(f"[Online] Error fetching NASA APOD: {e}", file=sys.stderr)

        return items

    def fetch_picsum(self, page=1, count=24):
        """
        Fetches curated high-resolution photography from Picsum (up to 5000x3333).
        """
        url = f"https://picsum.photos/v2/list?page={page}&limit={min(count, 30)}"
        items = []
        try:
            req = self._get_request(url)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for entry in data:
                pid = entry.get("id")
                author = entry.get("author", "Photographer")
                w = entry.get("width", 3840)
                h = entry.get("height", 2160)
                download_url = entry.get("download_url")
                thumb_url = f"https://picsum.photos/id/{pid}/320/200"

                items.append({
                    "id": f"picsum_{pid}",
                    "title": f"Photo #{pid} by {author}",
                    "provider": "Picsum",
                    "category": "Photography",
                    "resolution": f"{w} × {h}",
                    "file_size": "~ 3.5 MB",
                    "format": "JPG",
                    "thumb_url": thumb_url,
                    "full_url": download_url,
                    "source_url": entry.get("url", "https://picsum.photos"),
                    "filename": f"picsum_{pid}_{w}x{h}.jpg"
                })
        except Exception as e:
            print(f"[Online] Error fetching from Picsum: {e}", file=sys.stderr)

        return items

    def fetch_wikimedia_featured(self, count=24):
        """
        Fetches museum-grade, award-winning public domain featured pictures from Wikimedia Commons.
        """
        url = (
            "https://commons.wikimedia.org/w/api.php?action=query&generator=categorymembers"
            "&gcmtitle=Category:Featured_pictures_on_Wikimedia_Commons&gcmtype=file"
            f"&prop=imageinfo&iiprop=url|size&iiurlwidth=400&format=json&gcmlimit={min(count, 30)}"
        )
        items = []
        try:
            req = self._get_request(url)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            pages = data.get("query", {}).get("pages", {})
            for pid, page in pages.items():
                title = page.get("title", "Wikimedia").replace("File:", "").replace("_", " ")
                clean_title = os.path.splitext(title)[0][:35]
                ii = page.get("imageinfo", [{}])[0]
                full_url = ii.get("url", "")
                thumb_url = ii.get("thumburl") or full_url

                clean_url = full_url.split("?")[0].lower()
                if not clean_url.endswith((".jpg", ".jpeg", ".png", ".webp")):
                    continue

                w = ii.get("width", "HD")
                h = ii.get("height", "")
                ext = clean_url.split(".")[-1].upper()

                items.append({
                    "id": f"wiki_{pid}",
                    "title": clean_title,
                    "provider": "Wikimedia",
                    "category": "Heritage / Arts",
                    "resolution": f"{w} × {h}" if h else str(w),
                    "file_size": "High-Res",
                    "format": ext,
                    "thumb_url": thumb_url,
                    "full_url": full_url,
                    "source_url": "https://commons.wikimedia.org",
                    "filename": f"wikimedia_{pid}.{ext.lower()}"
                })
        except Exception as e:
            print(f"[Online] Error fetching from Wikimedia: {e}", file=sys.stderr)

        return items

    def search_wikimedia(self, query="landscape", count=24):
        """
        Searches Wikimedia Commons for high-resolution images matching query or category.
        """
        q = (query or "landscape").strip()
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": f"{q} filetype:bitmap",
            "gsrnamespace": "6",
            "gsrlimit": str(min(count, 30)),
            "prop": "imageinfo",
            "iiprop": "url|size",
            "iiurlwidth": "400",
            "format": "json"
        }
        url = f"https://commons.wikimedia.org/w/api.php?{urllib.parse.urlencode(params)}"
        items = []
        try:
            req = self._get_request(url)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            pages = data.get("query", {}).get("pages", {})
            for pid, page in pages.items():
                title = page.get("title", "Wikimedia").replace("File:", "").replace("_", " ")
                clean_title = title.split(".")[0][:35]
                ii = page.get("imageinfo", [{}])[0]
                full_url = ii.get("url", "")
                thumb_url = ii.get("thumburl") or full_url

                clean_url = full_url.split("?")[0].lower()
                if not clean_url.endswith((".jpg", ".jpeg", ".png", ".webp")):
                    continue

                w = ii.get("width", "HD")
                h = ii.get("height", "")
                ext = clean_url.split(".")[-1].upper()
                page_title = page.get("title", "")
                quoted_title = urllib.parse.quote(page_title)

                items.append({
                    "id": f"wiki_{pid}",
                    "title": clean_title,
                    "provider": "Wikimedia",
                    "category": q.capitalize(),
                    "resolution": f"{w} × {h}" if h else str(w),
                    "file_size": "High-Res",
                    "format": ext,
                    "thumb_url": thumb_url,
                    "full_url": full_url,
                    "source_url": f"https://commons.wikimedia.org/wiki/{quoted_title}",
                    "filename": f"wikimedia_{pid}.{ext.lower()}"
                })
        except Exception as e:
            print(f"[Online] Error searching Wikimedia: {e}", file=sys.stderr)

        return items

    def fetch_openverse(self, query="landscape", page=1, count=24):
        """
        Searches Openverse (Creative Commons / WordPress Foundation global open media).
        """
        q = query or "landscape"
        params = {
            "q": q,
            "page": str(page),
            "page_size": str(min(count, 30)),
            "license_type": "commercial,modification"
        }
        url = f"https://api.openverse.org/v1/images/?{urllib.parse.urlencode(params)}"
        items = []
        try:
            req = self._get_request(url)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for entry in data.get("results", []):
                img_id = entry.get("id", "")[:8]
                title = entry.get("title") or f"Openverse {img_id}"
                clean_title = title.split("(")[0].strip()[:35]
                full_url = entry.get("url", "")
                thumb_url = entry.get("thumbnail") or full_url
                w = entry.get("width", "HD")
                h = entry.get("height", "")
                ext = full_url.split(".")[-1].split("?")[0].lower()
                if ext not in ["jpg", "jpeg", "png", "webp"]:
                    ext = "jpg"

                items.append({
                    "id": f"ov_{img_id}",
                    "title": clean_title,
                    "provider": "Openverse",
                    "category": q.capitalize(),
                    "resolution": f"{w} × {h}" if h else "HD",
                    "file_size": "Variable",
                    "format": ext.upper(),
                    "thumb_url": thumb_url,
                    "full_url": full_url,
                    "source_url": entry.get("foreign_landing_url", "https://openverse.org"),
                    "filename": f"openverse_{img_id}.{ext}"
                })
        except Exception as e:
            print(f"[Online] Error fetching from Openverse: {e}", file=sys.stderr)

        return items

    def get_cached_thumbnail(self, thumb_url):
        """
        Returns local cached thumbnail path for an online image URL.
        Downloads in background if not already cached.
        """
        if not thumb_url:
            return None

        url_hash = hashlib.md5(thumb_url.encode()).hexdigest()
        cached_path = os.path.join(ONLINE_THUMBS_DIR, f"{url_hash}.jpg")

        if os.path.exists(cached_path) and os.path.getsize(cached_path) > 0:
            return cached_path

        try:
            req = self._get_request(thumb_url)
            with urllib.request.urlopen(req, timeout=6) as resp, open(cached_path + ".tmp", "wb") as f:
                f.write(resp.read())
            os.replace(cached_path + ".tmp", cached_path)
            return cached_path
        except Exception as e:
            if os.path.exists(cached_path + ".tmp"):
                try:
                    os.remove(cached_path + ".tmp")
                except Exception:
                    pass
            return None

    def download_wallpaper(self, item, target_dir=None, progress_callback=None):
        """
        Downloads a full-resolution wallpaper image to the local destination directory.
        Returns the absolute local path.
        """
        dest_dir = target_dir or DOWNLOADS_DIR
        os.makedirs(dest_dir, exist_ok=True)

        filename = item.get("filename") or f"online_wallpaper_{item['id']}.jpg"
        dest_path = os.path.join(dest_dir, filename)

        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
            return dest_path

        full_url = item.get("full_url")
        if not full_url:
            raise ValueError("No download URL provided in wallpaper item.")

        temp_path = dest_path + ".part"
        try:
            req = self._get_request(full_url)
            with urllib.request.urlopen(req, timeout=25) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 64 * 1024

                with open(temp_path, "wb") as out_f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            percent = min(1.0, downloaded / total_size)
                            progress_callback(percent, downloaded, total_size)

            os.replace(temp_path, dest_path)
            return dest_path
        except Exception as e:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise RuntimeError(f"Download failed: {e}")

    def download_and_apply(self, item, engine, style="zoom", progress_callback=None):
        """
        Downloads the full-resolution wallpaper and applies it immediately to Moksha.
        """
        local_path = self.download_wallpaper(item, progress_callback=progress_callback)
        engine.apply_wallpaper(local_path, style=style, notify=True)
        return local_path

    def _format_size(self, size_bytes):
        if not size_bytes:
            return "Unknown"
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"


if __name__ == "__main__":
    mgr = OnlineWallpaperManager()
    print("Testing Wallhaven search ('nature')...")
    res = mgr.search_wallhaven(category_key="nature", resolution="1920x1080")
    print(f"Wallhaven returned {len(res)} wallpapers.")
    if res:
        print("Sample:", res[0]["title"], res[0]["resolution"], res[0]["full_url"])

    print("\nTesting Bing Daily wallpapers...")
    bing = mgr.fetch_bing_daily(3)
    print(f"Bing returned {len(bing)} wallpapers.")
    if bing:
        print("Sample Bing:", bing[0]["title"], bing[0]["full_url"])
