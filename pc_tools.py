"""pc_tools.py - put this file in the Guts_AI folder, next to live_voice_2.py.
Plain functions Guts can call as tools. No Gemini/Live code in here."""
import os
import sys
import time
import shutil
import platform
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

import psutil

HOME = Path.home()

# ---------- BRAVE ----------
BRAVE_PATHS = [
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
]


def find_brave():
    for p in BRAVE_PATHS:
        if os.path.exists(p):
            return p
    return shutil.which("brave")


def open_in_brave(url_or_query: str) -> str:
    """Open a website or search in Brave browser."""
    t = url_or_query.strip()
    if not t.startswith(("http://", "https://")):
        if "." in t and " " not in t:
            t = "https://" + t
        else:
            t = "https://search.brave.com/search?q=" + quote_plus(t)
    brave = find_brave()
    try:
        if brave:
            subprocess.Popen([brave, t])
            return f"Opened in Brave: {t}"
        webbrowser.open(t)
        return f"Brave not found, opened in default browser: {t}"
    except Exception as e:
        return f"Browser error: {e}"


# ---------- SPECS ----------
def get_pc_specs() -> str:
    """Full PC specs: OS, CPU, RAM, disks, battery, uptime."""
    try:
        lines = [
            f"OS: {platform.platform()}",
            f"CPU: {platform.processor()} | cores {psutil.cpu_count(logical=False)} physical, "
            f"{psutil.cpu_count()} logical",
            f"RAM: {psutil.virtual_memory().total / 1e9:.1f} GB total, "
            f"{psutil.virtual_memory().percent}% used",
        ]
        for part in psutil.disk_partitions():
            try:
                u = psutil.disk_usage(part.mountpoint)
                lines.append(f"Disk {part.device}: {u.total / 1e9:.0f} GB total, {u.free / 1e9:.0f} GB free")
            except Exception:
                pass
        b = psutil.sensors_battery()
        if b:
            lines.append(f"Battery: {b.percent}% ({'charging' if b.power_plugged else 'on battery'})")
        up = (time.time() - psutil.boot_time()) / 3600
        lines.append(f"Uptime: {up:.1f} hours")
        return "\n".join(lines)
    except Exception as e:
        return f"Specs error: {e}"


# ---------- FILE INFO + SEARCH ----------
def file_info(path: str) -> str:
    """Size, type, dates of a file or folder."""
    p = Path(path).expanduser()
    if not p.exists():
        return "Not found."
    try:
        s = p.stat()
        kind = "folder" if p.is_dir() else (p.suffix or "file")
        extra = f", {len(os.listdir(p))} items" if p.is_dir() else f", {s.st_size / 1024:.1f} KB"
        mod = time.strftime("%Y-%m-%d %H:%M", time.localtime(s.st_mtime))
        return f"{p.name}: {kind}{extra}, modified {mod}"
    except Exception as e:
        return f"Info error: {e}"


SKIP_DIRS = {"AppData", "node_modules", "venv", ".git", "$Recycle.Bin", "Windows"}


def search_files(keyword: str, folder: str = "") -> str:
    """Find files/folders by name (max 25 results, 20 sec limit)."""
    base = Path(folder).expanduser() if folder else HOME
    kw, hits, start = keyword.lower(), [], time.time()
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for n in dirs + files:
            if kw in n.lower():
                hits.append(os.path.join(root, n))
                if len(hits) >= 25:
                    return "\n".join(hits)
        if time.time() - start > 20:
            break
    return "\n".join(hits) or "No match."


# ---------- RUN (call ONLY after Boss says yes) ----------
BLOCKED_RUN_DIRS = (r"c:\windows", r"c:\program files\windowsapps")
RUN_EXT = {".py", ".exe", ".bat", ".cmd", ".lnk", ".jar"}


def run_program_now(path: str) -> str:
    """Run a script/program. Must only be called after the voice 'yes'."""
    p = Path(path).expanduser()
    if not p.exists():
        return "Not found."
    if str(p).lower().startswith(BLOCKED_RUN_DIRS):
        return "BLOCKED: system folder."
    if p.suffix.lower() not in RUN_EXT:
        return f"Cannot run {p.suffix} files."
    try:
        if p.suffix.lower() == ".py":
            subprocess.Popen([sys.executable, str(p)], cwd=str(p.parent),
                             creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        else:
            os.startfile(str(p))
        return f"Started: {p.name}"
    except Exception as e:
        return f"Run error: {e}"
