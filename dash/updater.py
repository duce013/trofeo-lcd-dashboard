"""Self-update from GitHub Releases: find the latest TrofeoLCD.exe, download it, run its installer."""
from __future__ import annotations

import ctypes
import json
import os
import tempfile
import urllib.request

from version import REPO, VERSION

API = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = "TrofeoLCD.exe"
UA = {"User-Agent": "TrofeoLCD-updater", "Accept": "application/vnd.github+json"}


def parse(tag: str) -> tuple[int, ...]:
    """'v1.10.2' -> (1, 10, 2); junk parts count as 0 so a bad tag never crashes the check."""
    parts = []
    for p in tag.lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(tag: str, current: str = VERSION) -> bool:
    a, b = parse(tag), parse(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def latest(timeout=10) -> tuple[str, str | None, str]:
    """(tag, exe download url or None, release page url)."""
    with urllib.request.urlopen(urllib.request.Request(API, headers=UA), timeout=timeout) as r:
        rel = json.load(r)
    url = next((a["browser_download_url"] for a in rel.get("assets", []) if a.get("name") == ASSET), None)
    return rel.get("tag_name", ""), url, rel.get("html_url", "")


def download(url: str, progress=None) -> str:
    dest = os.path.join(tempfile.gettempdir(), "TrofeoLCD-update.exe")
    tmp = dest + ".part"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]}), timeout=30) as r, \
            open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    if total and os.path.getsize(tmp) != total:
        os.remove(tmp)
        raise IOError("download incomplete")
    os.replace(tmp, dest)
    return dest


def run_installer(exe: str) -> bool:
    """Start the new exe's installer elevated; it stops the running copy and replaces it."""
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, "--install", None, 1) > 32


if __name__ == "__main__":
    assert parse("v1.2.3") == (1, 2, 3) and parse("1.10") == (1, 10) and parse("v2.0.0-beta") == (2, 0, 0)
    assert is_newer("v1.1.1", "1.1.0") and is_newer("v1.10.0", "1.9.9") and is_newer("v2", "1.9.9")
    assert not is_newer("v1.1.0", "1.1.0") and not is_newer("v1.0.9", "1.1.0") and not is_newer("v1.1", "1.1.0")
    print("version compare ok")
    print("latest on GitHub:", latest()[:2])
