"""apply_sleep_close_patch.py - two things in one step.

1) HARD SLEEP. After "Guts abhi band ho jao" he stays asleep until you say "Guts":
   - anything he tries to say while asleep is blocked (and logged as [Sleep] Blocked)
   - any tool he tries to run while asleep is refused
   - the wake word is only accepted from a finished short phrase (max 4 words), never from
     half-heard sound or from a long sentence that happens to contain the word
   - the quiet time after falling asleep is 6 seconds (was 4)
2) CLOSE TOOL. "Guts, notepad band kar do", "Downloads folder band karo", "saare folders band karo".
   It closes windows politely (like clicking the X), so unsaved work still gets a Save question.

It reads live_voice_6.py and creates a NEW file live_voice_7.py.
Your live_voice_6.py is NOT changed, so it stays as your backup.

Run (in the Guts_AI folder):
  python apply_sleep_close_patch.py
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "live_voice_6.py"
DST = Path(sys.argv[2]) if len(sys.argv) > 2 else BASE / "live_voice_7.py"

# ---------------- 1) HARD SLEEP ----------------
OLD_HEARD = r'''WAKE_WORDS = {"guts", "gut", "gutts", "gats"}   # spellings the listener may give for "Guts"
WAKE_DEBUG = True                                # prints what he hears while asleep


def heard_wake(data: bytes) -> bool:
    rec = WAKE["rec"]
    if rec is None:
        return False
    if time.time() < WAKE.get("ignore_until", 0):
        WAKE["need_reset"] = True          # still in the quiet time after falling asleep
        return False
    if WAKE.get("need_reset"):
        rec.Reset()
        WAKE["need_reset"] = False
    if rec.AcceptWaveform(data):
        text = json.loads(rec.Result()).get("text", "")
        if text and WAKE_DEBUG:
            print(f"[Wake] heard: {text}")
    else:
        text = json.loads(rec.PartialResult()).get("partial", "")
    if WAKE_WORDS & set(text.split()):
        rec.Reset()
        return True
    return False'''

NEW_HEARD = r'''WAKE_WORDS = {"guts", "gut", "gutts", "gats"}   # spellings the listener may give for "Guts"
WAKE_DEBUG = True                                # prints what he hears while asleep
WAKE_MAX_WORDS = 4                               # a wake call is a SHORT phrase, like "Guts" or "Guts uth ja"


def heard_wake(data: bytes) -> bool:
    rec = WAKE["rec"]
    if rec is None:
        return False
    if time.time() < WAKE.get("ignore_until", 0):
        WAKE["need_reset"] = True          # still in the quiet time after falling asleep
        return False
    if WAKE.get("need_reset"):
        rec.Reset()
        WAKE["need_reset"] = False
    if not rec.AcceptWaveform(data):
        return False                       # only a FINISHED phrase counts, never half-heard sound
    text = json.loads(rec.Result()).get("text", "")
    if not text:
        return False
    words = text.split()
    ok = len(words) <= WAKE_MAX_WORDS and bool(WAKE_WORDS & set(words))
    if WAKE_DEBUG:
        print(f"[Wake] heard: {text}" + ("   <-- WAKE" if ok else ""))
    return ok'''

# ---------------- 2) CLOSE TOOL ----------------
CLOSE_BLOCK = r'''# ================= CLOSE APPS AND FOLDERS =================
import ctypes
from ctypes import wintypes

WM_CLOSE = 0x0010
CLOSE_ALIASES = {"vscode": "visual studio code", "vs code": "visual studio code", "code": "visual studio code",
                 "browser": "brave", "internet": "brave", "calc": "calculator", "taskmanager": "task manager"}
FOLDER_NAMES = ("desktop", "documents", "downloads", "pictures", "music", "videos")
KEEP_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW",
                "ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"}   # taskbar, desktop, terminals (Guts lives there)
BROWSERS = ("brave", "chrome", "edge", "firefox", "opera")


def _windows() -> list:
    """All visible windows as (handle, title, class)."""
    user32 = ctypes.windll.user32
    found = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _):
        if hwnd and user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                title = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, title, n + 1)
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, 256)
                found.append((int(hwnd), title.value, cls.value))
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return found


def _do_close(handles: list) -> str:
    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    for h in handles:
        user32.PostMessageW(h, WM_CLOSE, 0, 0)       # same as clicking the X: apps still ask to save
    return f"Closed {len(handles)} window(s)."


def close_item(name: str) -> str:
    """Close an open app window or File Explorer folder window."""
    low = name.lower().strip()
    want_folder = bool(re.search(r"\bfolders?\b", low)) or low in ("explorer", "file explorer", "windows explorer")
    key = re.sub(r"\b(folders?|window|windows|app|application|explorer|file|files|all)\b", " ", low)
    key = re.sub(r"\s+", " ", key).strip()
    key = CLOSE_ALIASES.get(key, key)

    me = ctypes.windll.kernel32.GetConsoleWindow()
    wins = [w for w in _windows()
            if w[0] != me and w[2] not in KEEP_CLASSES and w[1].lower() != "program manager"]
    explorer = [w for w in wins if w[2] == "CabinetWClass"]

    if want_folder:
        hits = [w for w in explorer if not key or key in w[1].lower()]
    else:
        if not key:
            return "Which app or folder should I close?"
        hits = [w for w in wins if key in w[1].lower()]
        ex_hits = [w for w in hits if w[2] == "CabinetWClass"]
        if key in FOLDER_NAMES and ex_hits:
            hits = ex_hits

    if not hits:
        return f"No open window found for '{name}'."
    if len(hits) > 6:
        return f"Too many windows match '{name}' ({len(hits)}). Ask Boss to be more specific."
    titles = "; ".join(w[1][:40] for w in hits[:3])
    handles = [w[0] for w in hits]
    risky = len(hits) > 1 or any(b in w[1].lower() for w in hits for b in BROWSERS)
    if risky:
        return _ask(f"close {len(hits)} window(s): {titles}", _do_close, handles=handles)
    return _do_close(handles) + f" ({titles})"


# ================= TOOL REGISTRY ================='''

CLOSE_DECL = '''decl("run_code", "Run the last code that was written. Risky code needs Boss's spoken yes."),
    decl("close_item", "Close an open app window or File Explorer folder window. Use the app name "
         "(notepad, calculator, brave, vscode, whatsapp) or the folder name (Downloads, Desktop), "
         "or say 'folders' to close all folder windows. Several windows or a browser needs Boss's spoken yes.",
         name="App name, folder name, or the word folders"),'''

EDITS = [
    ("wake check (finished short phrase only)", OLD_HEARD, NEW_HEARD),
    ("longer quiet time after sleep",
     'WAKE["ignore_until"] = time.time() + 4',
     'WAKE["ignore_until"] = time.time() + 6'),
    ("block his voice while asleep",
     "await asyncio.to_thread(out.write, msg.data)",
     'if STATE["asleep"]:\n'
     '                        if not STATE.get("blocked"):\n'
     '                            print("[Sleep] Blocked: he tried to talk while asleep.")\n'
     '                            STATE["blocked"] = True\n'
     '                    else:\n'
     '                        STATE["blocked"] = False\n'
     '                        await asyncio.to_thread(out.write, msg.data)'),
    ("refuse tools while asleep",
     "if GUARD and fc.name not in OPEN_TOOLS and not GUARD.boss_recent(FACE_GRACE):",
     'if STATE["asleep"]:\n'
     '                            result = "ASLEEP: Guts is sleeping, so nothing was done. Say nothing."\n'
     '                        elif GUARD and fc.name not in OPEN_TOOLS and not GUARD.boss_recent(FACE_GRACE):'),
    ("close tool code",
     "# ================= TOOL REGISTRY =================",
     CLOSE_BLOCK),
    ("close tool in function list",
     "research, write_code, run_code]",
     "research, write_code, run_code, close_item]"),
    ("close tool declaration",
     'decl("run_code", "Run the last code that was written. Risky code needs Boss\'s spoken yes."),',
     CLOSE_DECL),
    ("system prompt",
     'call open_item. To play a video or song call play_youtube. "',
     'call open_item. To play a video or song call play_youtube. "\n'
     '        "To close an app, window or folder call close_item. "'),
]


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run this from the Guts_AI folder.")
        return
    text = SRC.read_text(encoding="utf-8")
    if "close_item" in text:
        print("This file already has the close tool. Nothing to do.")
        return

    for label, anchor, new in EDITS:
        n = text.count(anchor)
        if n != 1:
            print(f"STOPPED. Could not safely patch '{label}' (found {n} matches, need 1).")
            print("Nothing was written. Send me this message and your live_voice_6.py.")
            return
        text = text.replace(anchor, new)

    compile(text, str(DST), "exec")          # syntax check before saving
    DST.write_text(text, encoding="utf-8")
    print(f"Done: {DST.name} created ({len(EDITS)} changes). {SRC.name} is untouched.")
    print("Next: python live_voice_7.py")


if __name__ == "__main__":
    main()
