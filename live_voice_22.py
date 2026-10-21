import traceback
import os
import re
import json
import random
import time
import shutil
import asyncio
import subprocess
from pathlib import Path
from urllib.parse import quote, quote_plus

import pyautogui
import psutil
import pyaudio
from send2trash import send2trash
from dotenv import load_dotenv
from google import genai
from google.genai import types
from game_buddy import open_tekken8, game_buddy, game_stream, GAME_PROMPT
from video_edit import latest_video, video_info, video_auto_edit, video_status
from video_pro import video_pro_edit, video_add_captions
from video_music import video_add_music, music_list
from pt_tools import open_packet_tracer, pt_demo_topology
from pt_ip import ip_plan, subnet_info
import guts_hands
from pc_tools import (open_in_brave, find_brave, get_pc_specs,
                      file_info, search_files, run_program_now)

import guts_brain

try:
    import pygetwindow as gw
except Exception:
    print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
    traceback.print_exc()
    gw = None

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MODEL = "gemini-3.8-live"
SEND_RATE = 16000   # mic
RECV_RATE = 24000   # Guts voice
CHUNK = 1024

HOME = Path.home()
PROFILE = BASE / "guts_user_profile.json"
CONTACTS_FILE = BASE / "contacts.json"

BLOCKED_DIRS = ("c:\\windows", "c:\\program files", "c:\\program files (x86)", "c:\\programdata")
PROTECTED_NAMES = {".env", "guts_user_profile.json", "contacts.json", "pc_tools.py", "guts_brain.py", "face_guard.py"}
NEVER_DELETE = {"onedrive", "desktop", "documents", "downloads", "pictures", "music", "videos", "appdata"}
TEXT_EXT = {".txt", ".md", ".py", ".json", ".csv", ".log", ".html", ".css", ".js", ".java",
            ".c", ".cpp", ".xml", ".ini", ".yaml", ".yml"}
NO_OPEN_EXT = {".exe", ".bat", ".cmd", ".ps1", ".vbs", ".msi", ".scr", ".com", ".js", ".jar"}

# state shared between tools (worker threads) and the async loop
# proactive mode: Guts watches the PC and talks first (set PROACTIVE = False to turn off)
PROACTIVE = True
DEBUG_WATCH = True       # prints a [Watch] line every check so you can see it working
OBS_INTERVAL = 60        # seconds between PC checks
SPEAK_COOLDOWN = 240     # min seconds between proactive lines
IDLE_AFTER = 40         # Boss silent this many seconds -> Guts starts a chat
IDLE_MAX_IN_ROW = 3     # then waits until Boss talks again (saves quota)
POLL = 5                # how often the watcher wakes up (seconds)

# face lock: only Boss's face (checked locally with the camera) can use tools
FACE_LOCK = True
FACE_GRACE = 90         # seconds Boss may be out of camera view before tools lock
GUARD = None
OPEN_TOOLS = {"get_system_status"}

STATE = {"pending": None, "heard": "", "last_activity": time.time(), "last_proactive": 0.0,
         "window": "", "window_since": 0.0, "nudged": False, "files": {}, "lowbat": False, "idle_count": 0, "last_obs": 0.0, "last_starter": -1,
         "visitor_mode": "roast", "visitor_until": 0.0,
         "asleep": False, "sleep_after_turn": False}


# ================= HELPERS =================
def special(name: str):
    n = name.strip().lower()
    for k in ("Desktop", "Documents", "Downloads"):
        if n == k.lower():
            p = HOME / "OneDrive" / k
            return p if p.exists() else HOME / k
    return None


def to_path(s: str) -> Path:
    return special(s) or Path(os.path.expandvars(s)).expanduser()


def in_blocked(p: Path) -> bool:
    return str(p).lower().startswith(BLOCKED_DIRS)


def is_protected(p: Path) -> bool:
    n = p.name.lower()
    return n in PROTECTED_NAMES or n.startswith("live_voice")


def _ask(desc: str, func, **kw) -> str:
    """Prepare an action. It only runs after Boss says yes (checked in Python, not by Gemini)."""
    STATE["pending"] = {"desc": desc, "func": func, "kw": kw, "armed": False, "t": time.time()}
    return ("PENDING - nothing has been done yet. In one short sentence tell Boss what you are about "
            "to do and ask him to say yes or no: " + desc)


# ================= TOOLS: NO CONFIRMATION =================
def get_system_status() -> str:
    b = psutil.sensors_battery()
    bat = f"{b.percent}% ({'charging' if b.power_plugged else 'on battery'})" if b else "Desktop"
    return f"CPU {psutil.cpu_percent()}%, RAM {psutil.virtual_memory().percent}%, Battery {bat}"


def get_active_window() -> str:
    try:
        return (gw.getActiveWindowTitle() if gw else None) or "Unknown"
    except Exception:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        return "Unknown"


def list_folder(path: str = "Desktop") -> str:
    try:
        items = sorted(os.listdir(to_path(r"C:\Users\Abhiraj\OneDrive\Desktop\Guts_AI")))[:60]
        return "\n".join(items) or "(empty)"
    except Exception as e:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        return f"List error: {e}"


def read_file(path: str) -> str:
    p = to_path(path)
    if p.name.lower() == ".env":
        return "Blocked: secrets."
    if not p.is_file():
        return "File not found."
    if p.suffix.lower() not in TEXT_EXT:
        return f"Cannot read {p.suffix} files."
    try:
        return p.read_text(encoding="utf-8", errors="ignore")[:3000]
    except Exception as e:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        return f"Read error: {e}"


APPS = {"notepad": "notepad", "calculator": "calc", "whatsapp": "whatsapp:", "vscode": "code",
        "explorer": "explorer", "paint": "mspaint", "settings": "ms-settings:", "task manager": "taskmgr"}


def find_shortcut(name: str):
    roots = [os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
             os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")]
    n = name.lower()
    for r in roots:
        for dp, _, fs in os.walk(r):
            for f in fs:
                if f.lower().endswith(".lnk") and n in f.lower():
                    return os.path.join(dp, f)
    return None


def open_item(name: str) -> str:
    key = name.lower().strip()
    try:
        if key in ("brave", "browser", "internet"):
            b = find_brave()
            if b:
                subprocess.Popen([b])
                return "Opened Brave"
            return "Brave not found."
        if key in APPS:
            subprocess.Popen(f'start "" {APPS[key]}', shell=True)
            return f"Opened {name}"
        p = to_path(name)
        if p.exists():
            if p.is_file() and p.suffix.lower() in NO_OPEN_EXT:
                return "Program files are not opened this way. Use run_program."
            os.startfile(str(p))
            return f"Opened {p}"
        lnk = find_shortcut(key)
        if lnk:
            os.startfile(lnk)
            return f"Opened {Path(lnk).stem}"
        return f"Could not find '{name}'."
    except Exception as e:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        return f"Open error: {e}"


def _load_profile() -> dict:
    try:
        return json.loads(PROFILE.read_text(encoding="utf-8"))
    except Exception:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        return {}


def remember(key: str, value: str) -> str:
    d = _load_profile()
    d.setdefault("facts", {})[key] = value
    PROFILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"Saved: {key} = {value}"


def recall() -> str:
    return json.dumps(_load_profile().get("facts", {}), ensure_ascii=False) or "{}"


def play_youtube(query: str) -> str:
    """Find the first YouTube result and play it in Brave (falls back to the search page)."""
    url, title = None, query
    try:
        import yt_dlp
        opts = {"quiet": True, "skip_download": True, "extract_flat": True, "noplaylist": True}
        with yt_dlp.YoutubeDL(opts) as y:
            e = y.extract_info(f"ytsearch1:{query}", download=False)["entries"][0]
            url = f"https://www.youtube.com/watch?v={e['id']}"
            title = e.get("title") or query
    except Exception as ex:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        print(f"[YouTube] direct lookup failed ({str(ex)[:80]}), opening search page")
    if not url:
        url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
        title = f"search results for {query}"
    return open_in_brave(url) + f" | {title}"


def set_visitor_mode(mode: str, minutes: str = "30") -> str:
    mode = mode.lower().strip()
    if mode not in ("roast", "polite"):
        return "Mode must be roast or polite."
    try:
        mins = max(1, min(240, int(float(minutes))))
    except Exception:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        mins = 30
    STATE["visitor_mode"], STATE["visitor_until"] = mode, time.time() + mins * 60
    return f"Visitor mode: {mode} for {mins} minutes."


def log_mood(mood: str, note: str) -> str:
    d = _load_profile()
    log = d.setdefault("mood_log", [])
    log.append({"time": time.strftime("%Y-%m-%d %H:%M"), "mood": mood, "note": note})
    d["mood_log"] = log[-30:]
    PROFILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    return "Mood noted."


# ================= PC OBSERVATION (proactive mode) =================
def scan_files() -> dict:
    snap = {}
    for k in ("Desktop", "Documents", "Downloads"):
        base = special(k)
        if not base or not base.exists():
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "venv", "__pycache__")]
            if root[len(str(base)):].count(os.sep) >= 2:
                dirs[:] = []
            for f in files:
                fp = os.path.join(root, f)
                try:
                    snap[fp] = os.path.getmtime(fp)
                except OSError:
                    pass
            if len(snap) > 4000:
                return snap
    return snap


def observe() -> list:
    """Returns a list of notable things. Only names/titles, never file contents."""
    notes, now = [], time.time()
    win = get_active_window()
    if win != STATE["window"]:
        STATE["window"], STATE["window_since"], STATE["nudged"] = win, now, False
    elif not STATE["nudged"] and win != "Unknown" and now - STATE["window_since"] > 5400:
        notes.append(f"Boss has been on '{win}' for over {int((now - STATE['window_since']) / 60)} minutes straight")
        STATE["nudged"] = True

    files = scan_files()
    if STATE["files"]:
        changed = [os.path.basename(f) for f, m in files.items()
                   if STATE["files"].get(f) != m
                   and not os.path.basename(f).lower().startswith(("~$", "guts_user_profile"))
                   and not f.lower().endswith((".tmp", ".bak", ".crdownload"))][:5]
        if changed:
            notes.append("New or changed files: " + ", ".join(changed))
    STATE["files"] = files

    cpu, ram = psutil.cpu_percent(), psutil.virtual_memory().percent
    if cpu > 90 or ram > 92:
        notes.append(f"PC is under heavy load (CPU {cpu}%, RAM {ram}%)")
    b = psutil.sensors_battery()
    low = bool(b and b.percent < 20 and not b.power_plugged)
    if low and not STATE["lowbat"]:
        notes.append(f"Battery is low: {b.percent}%")
    STATE["lowbat"] = low
    return notes


# ================= TOOLS: NEED VOICE YES =================
def _do_write(path: str, content: str) -> str:
    p = Path(path)
    if p.exists():
        shutil.copy2(p, str(p) + ".bak")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {p}"


def write_file(path: str, content: str) -> str:
    p = to_path(path).resolve()
    if in_blocked(p) or is_protected(p):
        return "BLOCKED: protected location or file."
    return _ask(f"write file {p.name} ({len(content)} characters) in {p.parent}", _do_write,
                path=str(p), content=content)


def _do_delete(path: str) -> str:
    send2trash(path)
    return f"Moved to Recycle Bin: {path}"


def delete_path(path: str) -> str:
    p = to_path(path).resolve()
    if not p.exists():
        return "Not found."
    if in_blocked(p) or is_protected(p) or len(p.parts) <= 3 or p.name.lower() in NEVER_DELETE:
        return "BLOCKED: protected location or file."
    return _ask(f"move {p.name} to the Recycle Bin ({p})", _do_delete, path=str(p))


def run_program(path: str) -> str:
    p = to_path(path).resolve()
    if not p.exists():
        return "Not found."
    if in_blocked(p):
        return "BLOCKED: system folder."
    return _ask(f"run {p.name} ({p})", run_program_now, path=str(p))


def _load_contacts() -> dict:
    if not CONTACTS_FILE.exists():
        print(f"[Contacts] File not found: {CONTACTS_FILE}")
        return {}
    try:
        data = json.loads(CONTACTS_FILE.read_text(encoding="utf-8-sig"))
        return {k.lower().strip(): re.sub(r"\D", "", str(v)) for k, v in data.items()}
    except Exception as e:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        print(f"[Contacts] Cannot read {CONTACTS_FILE}: {e}")
        return {}


def list_contacts() -> str:
    c = _load_contacts()
    return ", ".join(c) if c else "No contacts loaded. contacts.json is missing or has a JSON error."


def _do_whatsapp(phone: str, message: str) -> str:
    os.startfile(f"whatsapp://send?phone={phone}&text={quote(message)}")
    time.sleep(6)
    pyautogui.press("enter")
    return "WhatsApp message sent."


def send_whatsapp(contact: str, message: str) -> str:
    contacts = _load_contacts()
    phone = contacts.get(contact.lower().strip())
    if not phone:
        return f"I only know these contacts: {', '.join(contacts) or 'none (contacts.json missing)'}"
    return _ask(f"send WhatsApp to {contact}: '{message}'", _do_whatsapp, phone=phone, message=message)


# ================= CODING AND RESEARCH =================
def research(question: str) -> str:
    """Web research using the second Gemini key."""
    try:
        return guts_brain.research(question)
    except Exception as e:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        return f"Research failed: {e}"


def write_code(topic: str) -> str:
    """Write code into a NEW folder under projects and open it in VS Code. Does NOT run it."""
    try:
        return guts_brain.write_code(topic)
    except Exception as e:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        return f"Code writing failed: {e}"


def _run_code_forced() -> str:
    return guts_brain.run_code(force=True)


def run_code() -> str:
    """Run the last code that was written. Clean code runs now; risky code needs Boss's spoken yes."""
    try:
        result = guts_brain.run_code()
        if not result.startswith("NOT RUN"):
            return result
        path = Path(guts_brain.LAST.read_text(encoding="utf-8").strip())
        flags = guts_brain.check_code(path)
        return _ask(f"run {path.name} even though it uses risky things: {', '.join(flags)}. "
                    "Boss should have read the code in VS Code first", _run_code_forced)
    except Exception as e:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        return f"Run failed: {e}"


# ================= CLOSE APPS AND FOLDERS =================
import ctypes
import psutil
from ctypes import wintypes

WM_CLOSE = 0x0010
CLOSE_ALIASES = {"vscode": "visual studio code", "vs code": "visual studio code", "code": "visual studio code",
                 "browser": "brave", "internet": "brave", "calc": "calculator", "taskmanager": "task manager"}
FOLDER_NAMES = ("desktop", "documents", "downloads", "pictures", "music", "videos")
KEEP_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW"}
IGNORE_PROCS = {"textinputhost.exe", "shellexperiencehost.exe", "searchhost.exe",
                "startmenuexperiencehost.exe", "lockapp.exe", "systemsettingsbroker.exe"}
NEVER_KILL = {"explorer.exe", "winlogon.exe", "csrss.exe", "dwm.exe", "services.exe", "lsass.exe",
              "svchost.exe", "smss.exe", "wininit.exe", "system", "registry", "fontdrvhost.exe",
              "applicationframehost.exe", "windowsterminal.exe", "conhost.exe", "ctfmon.exe"}
BROWSERS = ("brave", "chrome", "edge", "firefox", "opera")
_PROC_CACHE = {}


def _proc_name(pid: int) -> str:
    if pid not in _PROC_CACHE:
        try:
            _PROC_CACHE[pid] = psutil.Process(pid).name().lower()
        except Exception:
            print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
            traceback.print_exc()
            _PROC_CACHE[pid] = ""
    return _PROC_CACHE[pid]


def _protected_pids() -> set:
    pids = set()
    try:
        p = psutil.Process()
        while p is not None:
            pids.add(p.pid)
            p = p.parent()
    except Exception:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        pass
    return pids


def _cloaked(hwnd) -> bool:
    try:
        v = wintypes.DWORD()
        ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(v), ctypes.sizeof(v))
        return v.value != 0
    except Exception:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        return False


def _windows() -> list:
    user32 = ctypes.windll.user32
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    found = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):
                return True
            if user32.GetWindowLongW(hwnd, -20) & 0x80:
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if not n or _cloaked(hwnd):
                return True
            title = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, title, n + 1)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            found.append((int(hwnd), title.value, cls.value, int(pid.value)))
        except Exception:
            print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
            traceback.print_exc()
            pass
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return found


def _eligible() -> list:
    prot = _protected_pids()
    return [w for w in _windows()
            if w[3] not in prot and w[2] not in KEEP_CLASSES and w[1].lower() != "program manager"
            and _proc_name(w[3]) not in IGNORE_PROCS]


def _matches(w, key: str) -> bool:
    title, proc = w[1].lower(), _proc_name(w[3]).replace(".exe", "")
    return key in title or proc == key.replace(" ", "") or (len(key) >= 4 and key in proc)


def _clean_key(name: str):
    low = name.lower().strip()
    want_folder = bool(re.search(r"\bfolders?\b", low)) or low in ("explorer", "file explorer", "windows explorer")
    key = re.sub(r"\b(folders?|window|windows|app|application|explorer|file|files|all)\b", " ", low)
    key = re.sub(r"\s+", " ", key).strip()
    return CLOSE_ALIASES.get(key, key), want_folder


def _do_close(handles: list) -> str:
    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    for h in handles:
        user32.PostMessageW(h, WM_CLOSE, 0, 0)
    return f"Closed {len(handles)} window(s)."


def _short(wins, n: int = 4) -> str:
    return "; ".join(w[1][:35] for w in wins[:n]) + (f" and {len(wins) - n} more" if len(wins) > n else "")


def list_open_windows() -> str:
    wins = _eligible()
    if not wins:
        return "Nothing is open."
    return "\n".join(f"{w[1][:60]}  ({_proc_name(w[3]).replace('.exe', '') or '?'})" for w in wins[:25])


def close_item(name: str) -> str:
    key, want_folder = _clean_key(name)
    wins = _eligible()
    explorer = [w for w in wins if w[2] == "CabinetWClass"]
    if want_folder:
        hits = [w for w in explorer if not key or key in w[1].lower()]
    else:
        if not key:
            return "Which app, file or folder should I close?"
        hits = [w for w in wins if _matches(w, key)]
        ex_hits = [w for w in hits if w[2] == "CabinetWClass"]
        if key in FOLDER_NAMES and ex_hits:
            hits = ex_hits
    if not hits:
        return f"No open window found for '{name}'."
    if len(hits) > 12:
        return f"Too many windows match '{name}' ({len(hits)}). Ask Boss to be more specific."
    handles = [w[0] for w in hits]
    risky = len(hits) > 1 or any(b in w[1].lower() or b in _proc_name(w[3]) for w in hits for b in BROWSERS)
    if risky:
        return _ask(f"close {len(hits)} window(s): {_short(hits)}", _do_close, handles=handles)
    return _do_close(handles) + f" ({_short(hits)})"


def close_all_apps(keep: str = "") -> str:
    keeps = [k.strip().lower() for k in keep.split(",") if k.strip()]
    keeps = [CLOSE_ALIASES.get(k, k) for k in keeps]
    hits = [w for w in _eligible() if not any(_matches(w, k) for k in keeps)]
    if not hits:
        return "Nothing to close."
    return _ask(f"close ALL {len(hits)} open windows ({_short(hits, 5)})"
                + (f", keeping {', '.join(keeps)}" if keeps else ""),
                _do_close, handles=[w[0] for w in hits])


def _all_procs() -> list:
    out = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            out.append((p.info["pid"], (p.info["name"] or "").lower()))
        except Exception:
            print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
            traceback.print_exc()
            pass
    return out


def _do_kill(pids: list) -> str:
    n = 0
    for pid in pids:
        try:
            psutil.Process(pid).kill()
            n += 1
        except Exception:
            print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
            traceback.print_exc()
            pass
    return f"Force-closed {n} process(es)."


def force_close(name: str) -> str:
    key, _ = _clean_key(name)
    if not key:
        return "Which app should I force close?"
    prot = _protected_pids()
    pids, names = set(), set()
    for w in _windows():
        if _matches(w, key):
            pids.add(w[3])
    for pid, pname in _all_procs():
        base = pname.replace(".exe", "")
        if base == key.replace(" ", "") or (len(key) >= 4 and key in base):
            pids.add(pid)
    safe = []
    for pid in pids:
        pn = _proc_name(pid) or next((n for p, n in _all_procs() if p == pid), "")
        if pid in prot or pn in NEVER_KILL:
            continue
        safe.append(pid)
        names.add(pn.replace(".exe", ""))
    if not safe:
        return f"Nothing safe to force close for '{name}'. Windows programs and Guts are protected. Try close_item."
    return _ask(f"FORCE-KILL {', '.join(sorted(names))} ({len(safe)} process). Unsaved work will be lost",
                _do_kill, pids=safe)


# ================= CISCO PACKET TRACER =================
def _wait_for_pt(seconds: int = 45) -> bool:
    import pt_send
    if pt_send.find_pt_main():
        return True
    open_packet_tracer()
    end = time.time() + seconds
    while time.time() < end:
        time.sleep(2)
        if pt_send.find_pt_main():
            time.sleep(4)
            return True
    return False


def _do_pt_send(path: str) -> str:
    import pt_send
    from pt_tools import clean_js
    script = clean_js(Path(path).read_text(encoding="utf-8"))
    if not _wait_for_pt():
        return ("Packet Tracer did not open in time (it may be waiting for Boss to sign in). "
                f"The script is saved at {path}")
    return pt_send.send(script)


def build_pt_lab(request: str) -> str:
    try:
        import pt_lab
        import pt_tools
        pt_lab.LAB_DIR = pt_tools.PT_DIR
        result = pt_lab.make_lab(request)
    except Exception as e:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        return f"Lab planning failed: {e}"
    if not result["ok"]:
        return "Could not make a clean lab. Problems: " + " | ".join(result["errors"][:3])
    spec = result["spec"]
    path = str(Path(result["folder"]) / "lab.js")
    routers = "; ".join(f"{d} {i} {ip}" for d, i, ip, _ in spec.get("_ips", [])[:6])
    hosts = "; ".join(f"{h['name']} {h.get('ip') or 'DHCP'}" for h in spec.get("hosts", [])[:6])
    msg = _ask(f"build the lab '{spec.get('title')}' ({result['devices']} devices, {result['links']} cables) "
               "inside Packet Tracer. Guts will automatically use the mouse and keyboard to open Packet Tracer, paste the script into the builder, and run it, so Boss should not touch it",
               _do_pt_send, path=path)
    return (msg + f" Router and switch IPs: {routers or 'none'}. PC IPs: {hosts or 'none'}. "
            f"Say only the most useful addresses. The full table is in addressing.txt in {result['folder']}.")


def pt_send_demo() -> str:
    try:
        import pt_tools
        pt_tools.save_pt_script("demo", pt_tools.DEMO_JS)
        path = str(pt_tools.PT_DIR / "demo.js")
    except Exception as e:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        return f"Demo failed: {e}"
    return _ask("send a small test network (1 switch, 2 PCs) into Packet Tracer. Guts will automatically use the mouse "
                "and keyboard to build it, so Boss should not touch it", _do_pt_send, path=path)


# ================= HEAVY BRAIN =================
import heavy_brain


def _heavy_precheck(task: str, kind: str, file_path: str) -> str:
    cfg = heavy_brain._cfg()
    if not cfg:
        return "No heavy key yet. Boss must add HEAVY_API_KEY to the .env file, then restart Guts."
    if "error" in cfg:
        return cfg["error"]
    if not cfg.get("model"):
        return "HEAVY_MODEL is not set in .env."
    if (kind or "analysis").lower().strip() not in heavy_brain.KINDS:
        return f"kind must be one of: {', '.join(heavy_brain.KINDS)}."
    if len((task or "").strip()) < 20:
        return "That is too short for the heavy brain."
    if heavy_brain.JOB["state"] == "running":
        return "The heavy brain is already working."
    if file_path:
        try:
            heavy_brain._read_context(file_path)
        except Exception as e:
            return f"The file cannot be sent: {e}"
    return ""


def _do_heavy(task: str, kind: str, file_path: str) -> str:
    return heavy_brain.heavy_task(task, kind, file_path)


def heavy_task(task: str, kind: str = "analysis", file_path: str = "") -> str:
    problem = _heavy_precheck(task, kind, file_path)
    if problem:
        return problem
    what = f"send a heavy {kind} task to the big brain"
    if file_path:
        what += f", together with the file {Path(file_path).name}"
    return _ask(what + f". Task: {task.strip()[:90]}", _do_heavy, task=task, kind=kind, file_path=file_path)


def heavy_status() -> str:
    return heavy_brain.heavy_status()


# ================= TOOL REGISTRY =================
def decl(fname, desc, /, _req=None, **params):
    kw = dict(name=fname, description=desc)
    if params:
        kw["parameters"] = types.Schema(
            type="OBJECT",
            properties={k: types.Schema(type="STRING", description=v) for k, v in params.items()},
            required=list(_req if _req is not None else params),
        )
    return types.FunctionDeclaration(**kw)


FUNCS = [get_system_status, get_pc_specs, get_active_window, list_folder, read_file, file_info,
         search_files, open_item, open_in_brave, remember, recall,
         write_file, delete_path, run_program, send_whatsapp, list_contacts, log_mood, play_youtube, set_visitor_mode,
         research, write_code, run_code, close_item, list_open_windows, close_all_apps, force_close, open_packet_tracer, pt_demo_topology, ip_plan, subnet_info, build_pt_lab, pt_send_demo, latest_video, video_info, video_auto_edit, video_status]
FUNCS += [heavy_task, heavy_status, open_tekken8, game_buddy, guts_hands.set_volume, guts_hands.set_brightness, guts_hands.take_screenshot, guts_hands.system_power, guts_hands.media_control, guts_hands.press_hotkey, guts_hands.type_text, video_pro_edit, video_add_captions, video_add_music, music_list]
TOOL_FUNCS = {f.__name__: f for f in FUNCS}

DECLS = [
    decl("get_system_status", "CPU, RAM and battery right now."),
    decl("get_pc_specs", "Full PC specs: OS, CPU, RAM, disks, battery, uptime."),
    decl("get_active_window", "Title of the window Boss is using right now."),
    decl("list_folder", "List files in a folder.", path="Desktop, Documents, Downloads or full folder path"),
    decl("read_file", "Read the first part of a text/code file.", path="Full file path"),
    decl("file_info", "Size, type and date of a file or folder.", path="Full path"),
    decl("search_files", "Find files or folders by name.", _req=["keyword"], keyword="Part of the file name", folder="Optional folder"),
    decl("open_item", "Open an app, file or folder.", name="App name or path"),
    decl("open_in_brave", "Open website or search in Brave.", url_or_query="URL or query"),
    decl("remember", "Save a fact about Boss.", key="Short label", value="The fact"),
    decl("recall", "Read all saved facts."),
    decl("write_file", "Create or overwrite a text file. Needs spoken yes.", path="Full path", content="Text"),
    decl("delete_path", "Move file/folder to Recycle Bin. Needs spoken yes.", path="Full path"),
    decl("run_program", "Run program. Needs spoken yes.", path="Full path"),
    decl("open_packet_tracer", "Open Cisco Packet Tracer."),
    decl("ip_plan", "Make VLSM IP addressing plan.", _req=["lans"], lans="LANs and host counts"),
    decl("subnet_info", "Exact subnet details.", address="IP/CIDR"),
    decl("pt_demo_topology", "Save small test network script."),
    decl("build_pt_lab", "Automatically build network/VLAN lab inside Packet Tracer after Boss says yes.", request="Boss's request in English"),
    decl("pt_send_demo", "Send test network into Packet Tracer. Needs spoken yes."),
    decl("latest_video", "Find newest video.", _req=[], folder="Folder path"),
    decl("video_info", "Video info.", path="Path"),
    decl("video_auto_edit", "Auto edit video.", _req=["path"], path="Path", style="reel or original"),
    decl("video_status", "Video edit status."),
    decl("open_tekken8", "Start Tekken 8."),
    decl("game_buddy", "Tekken commentary.", _req=["mode"], mode="on, off or status", boss_side="left or right"),
    decl("video_pro_edit", "Pro edit video.", _req=["path"], path="Path", hook="auto, none, or text", style="reel or original", music="auto, song name, or path"),
    decl("video_add_captions", "Add captions.", _req=["path"], path="Path", hook="Optional hook"),
    decl("video_add_music", "Add music.", _req=["path"], path="Path", music="auto or path"),
    decl("music_list", "List music songs."),
    decl("send_whatsapp", "Send WhatsApp. Needs spoken yes.", contact="Name", message="Text"),
    decl("log_mood", "Quietly log mood.", mood="stressed, angry, sad, tired, happy, excited", note="Reason"),
    decl("play_youtube", "Play on YouTube in Brave.", query="Topic"),
    decl("set_visitor_mode", "Visitor mode.", mode="roast or polite", minutes="Mins"),
    decl("list_contacts", "List WhatsApp contacts."),
    decl("research", "Web research.", question="Question"),
    decl("write_code", "Write code in VS Code.", topic="Topic"),
    decl("run_code", "Run last code."),
    decl("list_open_windows", "List open windows."),
    decl("close_all_apps", "Close all apps. Needs spoken yes.", _req=[], keep="Keep apps"),
    decl("force_close", "Force kill app. Needs spoken yes.", name="App name"),
    decl("close_item", "Close item window.", name="App or folder name"),
]
DECLS += [
    decl("set_volume", "Set volume 0-100.", level="0 to 100"),
    decl("set_brightness", "Set brightness 0-100.", level="0 to 100"),
    decl("take_screenshot", "Take screenshot.", name="Name"),
    decl("system_power", "Power control.", action="lock, sleep, shutdown, restart"),
    decl("media_control", "Media control.", action="play_pause, next, prev"),
    decl("press_hotkey", "Hotkey.", keys="e.g. win+d"),
    decl("type_text", "Type text.", text="Text"),
    decl("heavy_task", "Send serious task to heavy brain. Needs spoken yes.", _req=["task", "kind"], task="Task text", kind="code, debug, architecture, research, analysis, planning, document", file_path="Optional file path"),
    decl("heavy_status", "Heavy brain status."),
]
assert {f.__name__ for f in FUNCS} == {d.name for d in DECLS}, "Tool function/declaration mismatch"
TOOL_DECLS = [types.Tool(function_declarations=DECLS)]


# ================= VOICE YES / NO =================
YES = {"yes", "yeah", "yep", "haan", "han", "haa", "ha", "ok", "okay", "sure", "theek", "bhej",
       "bhejo", "karo", "हाँ", "हां", "हा", "ठीक", "करो", "भेजो"}
NO = {"no", "nope", "nahi", "nahin", "na", "mat", "ruko", "cancel", "stop", "नहीं", "नही", "मत", "रुको"}


def judge(text: str):
    words = set(re.findall(r"[\w\u0900-\u097F]+", text.lower()))
    if words & NO:
        return "no"
    if words & YES:
        return "yes"
    return None


async def handle_confirm(session, text: str):
    pend = STATE["pending"]
    if not pend or not pend["armed"]:
        return
    if GUARD and not GUARD.boss_recent(15):
        return
    if time.time() - pend["t"] > 45:
        STATE["pending"] = None
        print("[Confirm expired]")
        return
    STATE["heard"] += " " + text
    verdict = judge(STATE["heard"])
    if not verdict:
        return
    STATE["pending"], STATE["heard"] = None, ""
    if verdict == "no":
        result = "Boss said NO. Nothing was done."
    else:
        try:
            result = await asyncio.to_thread(pend["func"], **pend["kw"])
        except Exception as e:
            print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
            traceback.print_exc()
            result = f"Action failed: {e}"
    print(f"[Action] {result}")
    try:
        await session.send_realtime_input(text=f"[SYSTEM RESULT] {result} Tell Boss in one short sentence.")
    except Exception as e:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        print(f"(could not tell Guts: {e})")


# ================= WAKE WORD =================
WAKE_ENABLED = True
WAKE = {"rec": None, "tried": False}


def init_wake():
    if not WAKE_ENABLED or WAKE["tried"]:
        return
    WAKE["tried"] = True
    try:
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
        print("[Wake] Loading wake-word model...")
        model = Model(lang="en-us")
        WAKE["rec"] = KaldiRecognizer(model, SEND_RATE, json.dumps(WAKE_GRAMMAR))
        print("[Wake] Wake word ON.")
    except Exception as e:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        print(f"[Wake] Wake word OFF: {e}")


WAKE_GRAMMAR = ["black", "swordsman", "sword", "man", "[unk]"]


def wake_match(words) -> bool:
    joined = "".join(words)
    return "blackswordsman" in joined or "blackswordman" in joined or "blackswordsmen" in joined


WAKE_DEBUG = True
WAKE_MAX_WORDS = 4


def heard_wake(data: bytes) -> bool:
    rec = WAKE["rec"]
    if rec is None:
        return False
    if time.time() < WAKE.get("ignore_until", 0):
        WAKE["need_reset"] = True
        return False
    if WAKE.get("need_reset"):
        rec.Reset()
        WAKE["need_reset"] = False
    if not rec.AcceptWaveform(data):
        return False
    text = json.loads(rec.Result()).get("text", "")
    if not text:
        return False
    words = text.split()
    ok = len(words) <= WAKE_MAX_WORDS and wake_match(words)
    return ok


SLEEP_RE = re.compile(
    r"(band|bund|बंद|बन्द)\s*(ho|हो)\s*(jao|jaao|ja|जाओ|जा)|(so|सो)\s*(jao|jaao|ja|जाओ|जा)")
_RECENT = []


def is_goodbye(text: str) -> bool:
    now = time.time()
    _RECENT.append((now, text.lower()))
    _RECENT[:] = [(t, s) for t, s in _RECENT if now - t < 8]
    low = " ".join(s for _, s in _RECENT)
    words = set(re.findall(r"[\w\u0900-\u097F]+", low))
    if (words & {"bye", "बाय"}) or SLEEP_RE.search(low):
        _RECENT.clear()
        return True
    return False


# ================= LIVE SESSION =================
pya = pyaudio.PyAudio()


def build_system() -> str:
    prof = _load_profile()
    facts = json.dumps(prof.get("facts", {}), ensure_ascii=False)
    recent = "; ".join(f"{m['time']} {m['mood']}" for m in prof.get("mood_log", [])[-3:]) or "none yet"
    return (
        "You are Guts, Boss's loyal Giga Chad best friend. Speak natural Hinglish, "
        "1-3 short sentences, witty and warm. Call him 'Boss'. Never say 'As an AI'. "
        "For PC status, specs, current window, files, folders or apps you MUST call the matching tool "
        "first and answer from the real result. Never guess PC information. "
        "Boss uses Brave, not Chrome: for any website or web search call open_in_brave. "
        "To open an app, file or folder call open_item. To play a video or song call play_youtube. " + GAME_PROMPT + 
        "VIDEO EDITING: to find Boss's newest video call latest_video. To edit a video call video_auto_edit. "
        "PRO VIDEO EDIT: call video_pro_edit or video_add_captions or video_add_music. "
        "CISCO PACKET TRACER: to open it call open_packet_tracer. To test setup call pt_demo_topology. "
        "For IP addressing or subnetting call ip_plan or subnet_info. "
        "To BUILD a network or topology in Packet Tracer (routers, switches, PCs, cables, IP addresses, routing, VLANs) "
        "call build_pt_lab with Boss's whole request in English. It plans and checks the lab, and AUTOMATICALLY builds it "
        "inside Packet Tracer using mouse and keyboard automation (opening Packet Tracer, pasting script into builder, and running it) "
        "after Boss says yes. NEVER tell Boss to paste anything manually because you do it completely automatically. "
        "To send test network call pt_send_demo. "
        "JARVIS HANDS: use set_volume, set_brightness, take_screenshot, system_power, media_control, press_hotkey, type_text. "
        "HEAVY BRAIN: call heavy_task for serious tasks. "
        "ACCESS: only Boss is verified by his face. "
        "write_file, delete_path, run_program, send_whatsapp, build_pt_lab and pt_send_demo only PREPARE an action and return PENDING. "
        "When that happens, say what you are about to do in one short sentence and ask 'yes ya no?'. "
        "Never say it is done until you receive a [SYSTEM RESULT] message. "
        "CODING: call write_code or run_code. "
        "RESEARCH: call research. "
        "SLEEP: when Boss says goodbye or band ho jao, reply with ONE very short goodbye line. "
        f"Boss's recent moods: {recent}. "
        f"Known facts about Boss: {facts}"
    )


async def send_mic(session):
    stream = pya.open(format=pyaudio.paInt16, channels=1, rate=SEND_RATE,
                      input=True, frames_per_buffer=CHUNK)
    try:
        while True:
            data = await asyncio.to_thread(stream.read, CHUNK, False)
            if STATE["asleep"]:
                if await asyncio.to_thread(heard_wake, data):
                    STATE["asleep"] = False
                    STATE["last_activity"] = time.time()
                    STATE["idle_count"] = 0
                    print("[Wake] Guts is awake.")
                    try:
                        await session.send_realtime_input(
                            text="[WAKE] Boss just called you by name. Reply with ONE very short Hinglish line.")
                    except Exception as e:
                        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
                        traceback.print_exc()
                        print(f"(wake message failed: {e})")
                continue
            try:
                await session.send_realtime_input(
                    audio=types.Blob(data=data, mime_type=f"audio/pcm;rate={SEND_RATE}"))
            except Exception as ws_drop:
                print(f"⚠️ [WebSocket Drop Handled in send_mic]: {ws_drop}")
                break
    finally:
        stream.close()


# ================= SLOW TOOLS (run in the background so the live connection never waits) =================
SLOW_TOOLS = {"build_pt_lab", "write_code"}
_SLOW_JOBS = {}


def start_slow_tool(session, name, args):
    job = _SLOW_JOBS.get(name)
    if job is not None and not job.done():
        return (f"{name} is already running in the background. Tell Boss in one short sentence to wait, "
                "and do not start it again.")
    _SLOW_JOBS[name] = asyncio.create_task(_run_slow_tool(session, name, args))
    return ("STARTED in the background, it can take up to a minute. In ONE short sentence tell Boss it is running "
            "and that you will tell him when it is done. Do not call this tool again and do not wait.")


async def _run_slow_tool(session, name, args):
    try:
        result = await asyncio.to_thread(TOOL_FUNCS[name], **args)
    except Exception as e:
        result = f"Error: {e}"
    text = str(result)
    print(f"[Slow] {name} finished: {text[:200]}")
    try:
        await session.send_realtime_input(
            text=f"[TOOL DONE] {name} finished. Result: {text[:1500]} "
                 "Tell Boss the outcome in one or two short Hinglish sentences. Do not read the tag aloud.")
        STATE["last_activity"] = time.time()
    except Exception as e:
        print(f"[Slow] could not tell Guts (the connection changed): {e}. The result is printed above.")


async def play_replies(session):
    out = pya.open(format=pyaudio.paInt16, channels=1, rate=RECV_RATE, output=True)
    try:
        while True:
            async for msg in session.receive():
                if msg.tool_call:
                    responses = []
                    for fc in msg.tool_call.function_calls:
                        args = dict(fc.args or {})
                        print(f"[Tool]: {fc.name} {args}")
                        if STATE["asleep"]:
                            result = "ASLEEP: Guts is sleeping, so nothing was done. Say nothing."
                        elif GUARD and fc.name not in OPEN_TOOLS and not GUARD.boss_recent(FACE_GRACE):
                            if GUARD.stranger_active:
                                result = "DENIED: stranger active."
                            else:
                                result = "NOT VERIFIED YET: ask Boss to look at camera."
                        else:
                            try:
                                if fc.name in SLOW_TOOLS:
                                    result = start_slow_tool(session, fc.name, args)
                                else:
                                    result = await asyncio.to_thread(TOOL_FUNCS[fc.name], **args)
                            except Exception as e:
                                print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
                                traceback.print_exc()
                                result = f"Error: {e}"
                        responses.append(types.FunctionResponse(
                            id=fc.id, name=fc.name, response={"result": result}))
                    await session.send_tool_response(function_responses=responses)

                if msg.data:
                    STATE["last_activity"] = time.time()
                    if STATE["asleep"]:
                        if not STATE.get("blocked"):
                            STATE["blocked"] = True
                    else:
                        STATE["blocked"] = False
                        await asyncio.to_thread(out.write, msg.data)

                sc = msg.server_content
                if sc and sc.input_transcription and sc.input_transcription.text:
                    t = sc.input_transcription.text
                    print(f"[Boss]: {t}")
                    STATE["last_activity"] = time.time()
                    STATE["idle_count"] = 0
                    await handle_confirm(session, t)
                    if is_goodbye(t) and WAKE["rec"] is not None:
                        STATE["sleep_after_turn"] = True
                if sc and sc.output_transcription and sc.output_transcription.text:
                    print(f"[Guts]: {sc.output_transcription.text}")
                if sc and sc.turn_complete:
                    if STATE["sleep_after_turn"]:
                        STATE["sleep_after_turn"] = False
                        STATE["asleep"] = True
                        WAKE["ignore_until"] = time.time() + 6
                    pend = STATE["pending"]
                    if pend and not pend["armed"]:
                        pend["armed"], pend["t"] = True, time.time()
                        STATE["heard"] = ""
    finally:
        out.close()


STARTERS = [
    "tell one surprising tech or cybersecurity fact in a fun way",
    "give a short riddle or brain teaser and wait for his answer",
    "ask a would-you-rather question (tech or funny)",
    "ask what he is building or learning today and offer to help",
    "playfully comment on the window he is using right now",
    "friendly Giga Chad teasing or light roast, then ask something",
    "one short motivational line, then ask his goal for today",
    "ask a quick quiz question on coding or networking",
]


def idle_prompt(secs: int) -> str:
    i = random.choice([k for k in range(len(STARTERS)) if k != STATE["last_starter"]])
    STATE["last_starter"] = i
    return (f"[IDLE CHAT] Boss has been quiet for {secs} seconds. Start an interesting conversation in "
            f"1-2 short Hinglish sentences. Idea: {STARTERS[i]}.")


def face_event_prompt(ev: str) -> str:
    if ev == "stranger":
        return visitor_prompt()
    if ev == "unsure":
        return "[FACE UNSURE] Ask Boss to look straight at the camera."
    return "[BOSS RECOGNIZED] Greet him warmly."


def visitor_prompt() -> str:
    return "[VISITOR] Roast them playfully in 1-2 short Hinglish sentences."


async def watch_pc(session):
    await asyncio.to_thread(observe)
    STATE["last_obs"] = time.time()
    while True:
        await asyncio.sleep(POLL)
        now = time.time()
        silent = now - STATE["last_activity"]
        if STATE.get("game_quiet") or STATE["asleep"] or STATE["pending"]:
            continue
        job = heavy_brain.JOB
        if job["state"] in ("done", "failed") and STATE.get("heavy_told") != job["t0"]:
            STATE["heavy_told"] = job["t0"]
            text = f"[HEAVY DONE] Summary: {job['summary']}" if job["state"] == "done" else f"[HEAVY FAILED] {job['msg']}"
            try:
                await session.send_realtime_input(text=text)
                STATE["last_activity"] = time.time()
            except Exception as e:
                print(f"(heavy notice failed: {e})")
            continue
        if GUARD and silent > 3:
            ev = GUARD.pop_event()
            if ev:
                text = face_event_prompt(ev)
                try:
                    await session.send_realtime_input(text=text)
                    STATE["last_activity"] = time.time()
                except Exception as e:
                    print(f"(face event send failed: {e})")
                continue
        if not PROACTIVE or silent < 10:
            continue
        notes = []
        if now - STATE["last_obs"] >= OBS_INTERVAL:
            STATE["last_obs"] = now
            notes = await asyncio.to_thread(observe)
        if notes and now - STATE["last_proactive"] >= SPEAK_COOLDOWN:
            text = ("[AUTO-OBSERVATION] " + " | ".join(notes) + f". Say ONE short friendly line.")
        elif silent >= IDLE_AFTER and STATE["idle_count"] < IDLE_MAX_IN_ROW:
            STATE["idle_count"] += 1
            text = idle_prompt(int(silent))
        else:
            continue
            
        try:
            await session.send_realtime_input(text=text)
            STATE["last_proactive"] = STATE["last_activity"] = now
            print(f"[Proactive] {text[:120]}")
        except Exception as e:
            err_str = str(e)
            print(f'\n❌ [Guts Debug] DETAILED TRACEBACK:\n(proactive send failed: {e})')
            if "1011" in err_str or "ConnectionClosed" in err_str or "closed" in err_str:
                print("⚠️ [WebSocket Closed]: Stopping watch_pc to allow clean reconnect...")
                break


async def main():
    STATE["pending"], STATE["heard"] = None, ""
    print(f"[Contacts] {len(_load_contacts())} loaded from {CONTACTS_FILE}")
    init_wake()
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=build_system(),
        tools=TOOL_DECLS,
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    async with client.aio.live.connect(model=MODEL, config=config) as session:
        print("Guts is live. Use HEADPHONES. Talk to him. Ctrl+C to stop.")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(send_mic(session))
            tg.create_task(play_replies(session))
            tg.create_task(game_stream(session, STATE))
            if PROACTIVE or GUARD:
                tg.create_task(watch_pc(session))


FAILS = {"n": 0, "t0": time.time()}


def discover_live_models():
    names = [MODEL]
    try:
        for m in client.models.list():
            n = m.name.replace("models/", "")
            if "bidiGenerateContent" in (m.supported_actions or []) and n not in names:
                names.append(n)
    except Exception as e:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
    return names


LIVE_MODELS = discover_live_models()
print(f"[Live] Live models available: {', '.join(LIVE_MODELS)}")


if FACE_LOCK:
    try:
        from face_guard import FaceGuard
        GUARD = FaceGuard()
        GUARD.start()
        print("[Face] Face lock ON.")
    except Exception as e:
        print(f"[Face] Face lock OFF: {e}")

while True:
    try:
        FAILS["t0"] = time.time()
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        break
    except Exception as e:
        print('\n❌ [Guts Debug] DETAILED TRACEBACK:')
        traceback.print_exc()
        err = str(e)
        if time.time() - FAILS["t0"] > 60:
            FAILS["n"] = 0
        FAILS["n"] += 1
        busy = any(k in err.lower() for k in ("503", "unavailable", "overloaded", "high demand", "1011", "1013", "try again"))
        delay = min(90, 3 * (2 ** min(FAILS["n"] - 1, 5))) + random.uniform(0, 3)
        if busy and len(LIVE_MODELS) > 1:
            LIVE_MODELS.append(LIVE_MODELS.pop(0))
            MODEL = LIVE_MODELS[0]
        print(f"Session ended ({err[:150]}).")
        print(f"{'Google is busy. ' if busy else ''}Try {FAILS['n']}: waiting {int(delay)} sec, then using {MODEL} ...")
        time.sleep(delay)