"""pt_send.py - puts a script INTO Cisco Packet Tracer (not VS Code).

It does by itself what you do by hand: Extensions > Builder Code Editor > paste > Run.
It clicks where YOU showed it once (calibration), so it works with any Packet Tracer version.

Commands (run in the Guts_AI folder, Packet Tracer open and visible):
  python pt_send.py calibrate     show it 4 places (about 1 minute, only once)
  python pt_send.py clicktest     DEBUG: tries 2 click methods on the Extensions menu (does the menu open?)
  python pt_send.py check         DEBUG: shows what it sees and moves the mouse to each saved place (no clicks)
  python pt_send.py clipcheck     DEBUG: can it write and read the clipboard?
  python pt_send.py test          sends one switch to Packet Tracer (prints every step, checks the paste worked)
  python pt_send.py send lab.js   sends any script file

From other code:   import pt_send;  print(pt_send.send(script_text))

Safety: before it pastes, it checks that the window in front belongs to Packet Tracer.
If not, it stops and pastes nothing, so your text never lands in VS Code or another app.
Redo 'calibrate' if you change screen resolution or the Packet Tracer window size.
"""
import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

BASE = Path(__file__).resolve().parent
CAL_FILE = BASE / "pt_clicks.json"
VK_RSHIFT = 0xA1          # you tap the RIGHT Shift key to say "the mouse is on the right spot"
VERBOSE = True            # prints every step so you can see where it stops
CLICK_HOLD = 0.12         # how long the mouse button stays down (some apps ignore instant clicks)
USE_WIN32_CLICK = False   # True = click with Windows mouse_event instead of pyautogui (try if clicks do nothing)

STEPS = [
    ("extensions", "Put the mouse on the 'Extensions' menu in Packet Tracer's top menu bar. Do NOT click."),
    ("builder", "Now CLICK 'Extensions' so the menu opens, then put the mouse on 'Builder Code Editor'. Do NOT click it."),
    ("editor", "Now CLICK 'Builder Code Editor' so it opens, then put the mouse in the big text area of the editor."),
    ("run", "Put the mouse on the editor's 'Run' button. Do NOT click it."),
]


def log(msg: str):
    if VERBOSE:
        print(f"[pt_send] {msg}", flush=True)


# ================= WINDOWS HELPERS =================
def _u():
    return ctypes.windll.user32


def _dpi():
    try:
        _u().SetProcessDPIAware()      # same pixel units for reading and clicking
    except Exception:
        pass


def _title(hwnd) -> str:
    n = _u().GetWindowTextLengthW(hwnd)
    if not n:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    _u().GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _rect(hwnd):
    r = wintypes.RECT()
    _u().GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def _pid(hwnd) -> int:
    pid = wintypes.DWORD()
    _u().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _windows() -> list:
    """Visible windows with a title: (handle, title, rect)."""
    found = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if hwnd and _u().IsWindowVisible(hwnd):
            t = _title(hwnd)
            if t:
                found.append((int(hwnd), t, _rect(hwnd)))
        return True

    _u().EnumWindows(enum_proc(cb), 0)
    return found


def _cursor():
    pt = wintypes.POINT()
    _u().GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _root_under_cursor():
    u = _u()
    pt = wintypes.POINT()
    u.GetCursorPos(ctypes.byref(pt))
    u.WindowFromPoint.argtypes = [wintypes.POINT]
    u.WindowFromPoint.restype = wintypes.HWND
    u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    u.GetAncestor.restype = wintypes.HWND
    h = u.WindowFromPoint(pt)
    return int(u.GetAncestor(h, 2)) if h else 0       # 2 = top-level window


def _foreground() -> int:
    return int(_u().GetForegroundWindow() or 0)


def _key_down(vk: int) -> bool:
    return bool(_u().GetAsyncKeyState(vk) & 0x8000)


def find_pt_main():
    """The main Packet Tracer window: (handle, title, rect) or None."""
    for w in _windows():
        low = w[1].lower()
        if "packet tracer" in low and "builder" not in low and "visual studio code" not in low:
            return w
    return None


def find_by_key(key: str):
    for w in _windows():
        if key and key.lower() in w[1].lower():
            return w
    return None


def title_key(title: str) -> str:
    return title.split(" - ")[0].strip()


def activate(hwnd: int) -> bool:
    u = _u()
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)          # restore
    for attempt in range(3):
        u.SetForegroundWindow(hwnd)
        time.sleep(0.4)
        if _foreground() == hwnd:
            return True
        if attempt == 0:
            import pyautogui
            pyautogui.press("alt")     # lets Windows accept the focus change
    return _foreground() == hwnd


# ================= CALIBRATE =================
def calibrate():
    _dpi()
    main = find_pt_main()
    if not main:
        print("Packet Tracer is not open (or its window has no title). Open it, then try again.")
        return
    print("Calibration: 4 places. Keep Packet Tracer open and visible.")
    print("For each place: move the mouse there, then TAP THE RIGHT SHIFT KEY (it is safe, it does nothing in Packet Tracer).\n")
    cal = {}
    for name, text in STEPS:
        print(f"[{name}] {text}")
        while not _key_down(VK_RSHIFT):
            time.sleep(0.05)
        x, y = _cursor()
        main = find_pt_main()
        root = _root_under_cursor()
        anchor = None
        key = ""
        if name in ("editor", "run") and root and root != main[0] and _title(root):
            anchor, key = (root, _title(root), _rect(root)), title_key(_title(root))
        if anchor is None:
            anchor = main
        left, top, right, bottom = anchor[2]
        cal[name] = {"anchor_key": key, "rx": x - left, "ry": y - top}
        where = f"window '{key}'" if key else "the Packet Tracer window"
        print(f"   saved ({x},{y}) relative to {where}")
        while _key_down(VK_RSHIFT):
            time.sleep(0.05)
        time.sleep(0.3)
    CAL_FILE.write_text(json.dumps(cal, indent=2), encoding="utf-8")
    print(f"\nCalibration saved in {CAL_FILE.name}. Next: python pt_send.py check")


# ================= CLICKING =================
def _win32_click(x, y):
    u = _u()
    u.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    u.mouse_event(0x0002, 0, 0, 0, 0)      # left button down
    time.sleep(CLICK_HOLD)
    u.mouse_event(0x0004, 0, 0, 0, 0)      # left button up


def _do_click(x, y):
    """Move, let the app notice the mouse, then press and HOLD briefly (instant clicks are often ignored)."""
    import pyautogui
    pyautogui.moveTo(x, y, duration=0.3)
    pyautogui.moveRel(1, 0)
    pyautogui.moveRel(-1, 0)
    time.sleep(0.2)
    if USE_WIN32_CLICK:
        _win32_click(x, y)
        return
    pyautogui.mouseDown()
    time.sleep(CLICK_HOLD)
    pyautogui.mouseUp()


def _pt_is_higher_privilege(pid: int) -> bool:
    """True when Packet Tracer runs as Administrator but this script does not (Windows then ignores our clicks)."""
    try:
        import psutil
        psutil.Process(pid).exe()
        return False
    except Exception as e:
        return e.__class__.__name__ == "AccessDenied"


ADMIN_HINT = ("Packet Tracer seems to run as Administrator, so Windows blocks clicks from a normal PowerShell. "
              "Close PowerShell, open it with: right click > Run as administrator, and try again.")


def clicktest():
    """Clicks the Extensions menu with two methods so we can see which one works."""
    global USE_WIN32_CLICK
    import pyautogui
    _dpi()
    if not CAL_FILE.exists():
        print("Not calibrated yet. Run: python pt_send.py calibrate")
        return
    cal = json.loads(CAL_FILE.read_text(encoding="utf-8"))
    main = find_pt_main()
    if not main:
        print("Packet Tracer is not open (or it is minimized).")
        return
    if _pt_is_higher_privilege(_pid(main[0])):
        print("WARNING: " + ADMIN_HINT)
    p = cal["extensions"]
    x, y = main[2][0] + p["rx"], main[2][1] + p["ry"]
    for label, win32 in (("A  pyautogui press-and-hold", False), ("B  Windows mouse_event", True)):
        USE_WIN32_CLICK = win32
        print(f"\n[{label}] clicking Extensions in 2 seconds. WATCH: does the menu open?")
        activate(main[0])
        time.sleep(2)
        _do_click(x, y)
        time.sleep(2.5)
        pyautogui.press("esc")
        time.sleep(1)
    print("\nTell me: did the menu open in A, in B, in both, or in neither?")


# ================= CHECK (debug, no clicks) =================
def check():
    import pyautogui
    _dpi()
    if not CAL_FILE.exists():
        print("Not calibrated yet. Run: python pt_send.py calibrate")
        return
    cal = json.loads(CAL_FILE.read_text(encoding="utf-8"))
    main = find_pt_main()
    print("Packet Tracer window :", (main[1], main[2]) if main else "NOT FOUND (open it, do not minimize it)")
    if main and _pt_is_higher_privilege(_pid(main[0])):
        print("WARNING:", ADMIN_HINT)
    print("\nWindows that mention Packet Tracer or Builder:")
    for h, t, r in _windows():
        if "packet tracer" in t.lower() or "builder" in t.lower():
            print(f"   '{t}'  rect={r}  pid={_pid(h)}")
    print("\nSaved calibration:")
    for name in ("extensions", "builder", "editor", "run"):
        p = cal.get(name)
        print(f"   {name:10} anchor={p['anchor_key']!r:28} offset=({p['rx']},{p['ry']})" if p else f"   {name}: MISSING")
    if not main:
        return
    print("\nWatch the mouse now. It moves to each saved place for 2 seconds. NO clicks.")
    print("Tell me for each place: is the mouse on the right spot?")
    for name in ("extensions", "builder", "editor", "run"):
        p = cal.get(name)
        if not p:
            continue
        w = find_by_key(p["anchor_key"]) if p["anchor_key"] else main
        if not w:
            print(f"   {name}: its window is not open right now (open the Builder Code Editor to check this one)")
            continue
        x, y = w[2][0] + p["rx"], w[2][1] + p["ry"]
        pyautogui.moveTo(x, y, duration=0.6)
        print(f"   {name}: mouse is at ({x},{y})")
        time.sleep(2)


# ================= SEND =================
def _copy(text: str) -> bool:
    try:
        subprocess.run("clip", input=text.encode("ascii", "replace"), shell=True, check=True)
        return True
    except Exception:
        return False


def _click(cal: dict, name: str):
    p = cal[name]
    w = find_by_key(p["anchor_key"]) if p["anchor_key"] else find_pt_main()
    if not w:
        raise RuntimeError(f"cannot find the window for '{name}'")
    left, top, right, bottom = w[2]
    x, y = left + p["rx"], top + p["ry"]
    if not (left <= x <= right and top <= y <= bottom):
        raise RuntimeError("the window size changed since calibration. Run: python pt_send.py calibrate")
    log(f"click {name} at ({x},{y}) in '{w[1][:40]}'")
    _do_click(x, y)


def _read_clip():
    """Reads the Windows clipboard text directly (no PowerShell). Returns None if it cannot be read."""
    try:
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        u.OpenClipboard.argtypes = [wintypes.HWND]
        u.GetClipboardData.argtypes = [wintypes.UINT]
        u.GetClipboardData.restype = wintypes.HANDLE
        k.GlobalLock.argtypes = [wintypes.HANDLE]
        k.GlobalLock.restype = ctypes.c_void_p
        k.GlobalUnlock.argtypes = [wintypes.HANDLE]
        opened = False
        for _ in range(20):
            if u.OpenClipboard(None):
                opened = True
                break
            time.sleep(0.05)
        if not opened:
            raise RuntimeError("clipboard is busy")
        try:
            h = u.GetClipboardData(13)              # CF_UNICODETEXT
            if not h:
                return ""
            ptr = k.GlobalLock(h)
            try:
                return ctypes.wstring_at(ptr)
            finally:
                k.GlobalUnlock(h)
        finally:
            u.CloseClipboard()
    except Exception as e:
        log(f"direct clipboard read failed ({e}), trying PowerShell")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                           capture_output=True, text=True, timeout=15)
        return r.stdout
    except Exception:
        return None


def clipcheck():
    """DEBUG: can this program write the clipboard and read it back?"""
    _dpi()
    ok = _copy("__GUTS_CLIP_TEST__")
    got = _read_clip()
    print(f"write ok: {ok} | read back: {got!r}")
    print("Clipboard works." if got and "GUTS_CLIP_TEST" in got else
          "Clipboard read-back is BROKEN here. That would make the paste check give a false 'did not work'.")


def _norm(s: str) -> str:
    return "".join((s or "").split())          # ignore spaces and line breaks when comparing


def _combo(*keys):
    """Slow key combination. pyautogui.hotkey is so fast that the Packet Tracer editor can miss the Ctrl."""
    import pyautogui
    for k in keys[:-1]:
        pyautogui.keyDown(k)
        time.sleep(0.15)
    pyautogui.press(keys[-1])
    time.sleep(0.2)
    for k in reversed(keys[:-1]):
        pyautogui.keyUp(k)
        time.sleep(0.15)


SENTINEL = "__GUTS_EMPTY__"


def _editor_has(script: str) -> bool:
    """Reads the editor back: copy everything in it and compare with the script."""
    _copy(SENTINEL)
    time.sleep(0.3)
    _combo("ctrl", "a")
    _combo("ctrl", "c")
    time.sleep(0.6)
    got = _read_clip()
    n_got = len(_norm(got or ""))
    log(f"editor read-back: {n_got} characters (script has {len(_norm(script))})")
    if got is None:
        log("-> the clipboard could not be read at all")
    elif _norm(got) == _norm(SENTINEL):
        log("-> Ctrl+A / Ctrl+C did not reach the editor (clipboard still has my marker)")
    elif n_got == 0:
        log("-> the editor copied NOTHING (it is empty, or it does not support Ctrl+C)")
    return bool(_norm(script)) and _norm(script) == _norm(got or "")


def _paste_verified(cal: dict, script: str) -> str:
    import pyautogui
    _copy(script)
    _click(cal, "editor")
    time.sleep(0.5)
    _combo("ctrl", "a")
    pyautogui.press("delete")
    time.sleep(0.3)
    log("pasting script via Ctrl+V ...")
    _combo("ctrl", "v")
    time.sleep(0.8)
    return "Ctrl+V (Direct)"


def _wait_for_window(key: str, seconds: float = 5.0):
    t0 = time.time()
    while time.time() - t0 < seconds:
        w = find_by_key(key)
        if w:
            return w
        time.sleep(0.3)
    return None


def _front_is_ok(pt_pid: int, editor_key: str):
    fg = _foreground()
    if not fg:
        return False, "no window in front"
    title = _title(fg)
    low = title.lower()
    if _pid(fg) == pt_pid:
        return True, title
    if editor_key and editor_key.lower() in low and "visual studio code" not in low:
        return True, title
    return False, f"'{title}' (pid {_pid(fg)}, Packet Tracer pid {pt_pid})"


def send(script: str) -> str:
    """Puts the script into Packet Tracer and presses Run. Returns a short message."""
    import pyautogui
    _dpi()
    if not CAL_FILE.exists():
        return "Not calibrated yet. Run once: python pt_send.py calibrate"
    cal = json.loads(CAL_FILE.read_text(encoding="utf-8"))
    main = find_pt_main()
    if not main:
        return "Packet Tracer is not open (or it is minimized). Open it first."
    log(f"Packet Tracer window found: '{main[1][:50]}'")
    if _pt_is_higher_privilege(_pid(main[0])):
        log("WARNING: " + ADMIN_HINT)
    if not _copy(script):
        return "Could not copy the script to the clipboard."
    log("script copied to clipboard")
    try:
        if not activate(main[0]):
            return "Could not bring Packet Tracer to the front. Click on it once and try again."
        log("Packet Tracer is in front")
        pt_pid = _pid(main[0])
        key = cal["editor"]["anchor_key"]
        editor = find_by_key(key) if key else None
        if editor:
            log(f"editor window already open: '{editor[1][:40]}'")
            activate(editor[0])
        else:
            _click(cal, "extensions")
            time.sleep(0.8)
            _click(cal, "builder")
            if key:
                editor = _wait_for_window(key)
                if not editor:
                    return (f"Stopped: the editor window '{key}' did not open after clicking Builder Code Editor. "
                            "Run: python pt_send.py check")
                log(f"editor window opened: '{editor[1][:40]}'")
                activate(editor[0])
            else:
                time.sleep(2.5)
        _click(cal, "editor")
        time.sleep(0.5)
        ok, info = _front_is_ok(pt_pid, key)
        if not ok:
            return (f"Stopped: the window in front is {info}, not the editor, so nothing was pasted. "
                    "The script is on your clipboard. Run: python pt_send.py check")
        log(f"editor is in front: '{info[:40]}'")
        method = _paste_verified(cal, script)
        if not method:
            return ("Stopped: the script did NOT get into the editor, so Run was not pressed. "
                    "The script is on your clipboard: click in the editor, press Ctrl+V and Run by hand, "
                    "and tell me what the lines above printed.")
        log(f"script is in the editor (method: {method})")
        _click(cal, "run")
        return "Sent to Packet Tracer and pressed Run. If no device appeared, open the editor and read its message."
    except Exception as e:
        return f"Send failed: {e}. The script is on your clipboard: paste it into the Builder Code Editor by hand."


TEST_SCRIPT = 'addDevice("S1","2960-24TT",200,150);\n'

if __name__ == "__main__":
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    if cmd == "calibrate":
        calibrate()
    elif cmd == "check":
        check()
    elif cmd == "clipcheck":
        clipcheck()
    elif cmd == "clicktest":
        clicktest()
    elif cmd == "test":
        print(send(TEST_SCRIPT))
    elif cmd == "send" and len(sys.argv) > 2:
        print(send(Path(sys.argv[2]).read_text(encoding="utf-8")))
    else:
        print(__doc__)
