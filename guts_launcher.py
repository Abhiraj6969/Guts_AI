"""guts_launcher.py - the program inside Guts.exe (no console window).

  Guts.exe                run Guts (the setup wizard opens first on a new PC)
  Guts.exe --login        same, used by Start with Windows (waits a little for mic, camera and internet)
  Guts.exe --setup        open the setup wizard again (name, key, contacts, face ...)
  Guts.exe --avatar       show only the face on the screen (it is started automatically with Guts)
  Guts.exe --stop         turn Guts OFF (stops a running Guts)
  Guts.exe --status       tells you if Guts is running or off
  Guts.exe --selftest     check that every library is inside the exe (writes selftest.txt)

Guts's own files (guts_main.py and the helper modules) are plain source files in the 'app' folder next to the exe.
Everything personal is written there: .env, guts_settings.json, contacts.json, boss_face.npy, projects, guts.log.
"""
import atexit
import importlib
import json
import os
import runpy
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path


def app_dir() -> Path:
    env = os.environ.get("GUTS_APP_DIR")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "app"
    return Path(__file__).resolve().parent


APP = app_dir()
os.environ["GUTS_APP_DIR"] = str(APP)
os.chdir(APP)
sys.path.insert(0, str(APP))

LOG = APP / "guts.log"
PIDFILE = APP / "guts.pid"
LOCK_PORT = 47653                   # one Guts at a time
MAIN_SCRIPT = "guts_main.py"
LOGIN_DELAY = 15
MAX_QUICK_FAILS = 5

if False:                           # lets PyInstaller see what the plain-source Guts files need
    import tkinter                  # noqa: F401
    import tkinter.messagebox       # noqa: F401
    import tkinter.scrolledtext     # noqa: F401
    import tkinter.simpledialog     # noqa: F401
    import tkinter.ttk              # noqa: F401
    import winreg                   # noqa: F401
    import audioop                  # noqa: F401
    import ctypes.wintypes          # noqa: F401


def setup_log():
    if LOG.exists() and LOG.stat().st_size > 1_000_000:
        LOG.replace(APP / "guts.old.log")
    f = open(LOG, "a", encoding="utf-8", buffering=1)
    sys.stdout = f
    sys.stderr = f
    print(f"\n===== Guts start {time.strftime('%Y-%m-%d %H:%M:%S')} =====")


def internet_ok() -> bool:
    try:
        socket.create_connection(("generativelanguage.googleapis.com", 443), timeout=5).close()
        return True
    except OSError:
        return False


def wait_for_internet(max_wait: int = 90):
    if os.environ.get("GUTS_SKIP_NETWORK_WAIT"):
        return
    t0 = time.time()
    while time.time() - t0 < max_wait:
        if internet_ok():
            return
        time.sleep(5)
    print("[Launcher] No internet after 90 sec, starting anyway (Guts keeps retrying).")


def message(text: str):
    """A small window, because Guts.exe has no console."""
    try:
        import tkinter
        from tkinter import messagebox
        r = tkinter.Tk()
        r.withdraw()
        messagebox.showinfo("Guts AI", text)
        r.destroy()
    except Exception:
        print(text)


# ---------------- modes ----------------
def selftest() -> int:
    deps_file = APP / "_deps.json"
    mods = json.loads(deps_file.read_text(encoding="utf-8")) if deps_file.exists() else []
    lines, bad = [], 0
    for m in mods:
        try:
            importlib.import_module(m)
            lines.append(f"OK    {m}")
        except Exception as e:
            bad += 1
            lines.append(f"FAIL  {m}: {str(e)[:120]}")
    (APP / "selftest.txt").write_text("\n".join(lines) + f"\n\n{bad} problem(s)\n", encoding="utf-8")
    return 1 if bad else 0


def stop() -> int:
    if not PIDFILE.exists():
        message("Guts is not running.")
        return 0
    pid = PIDFILE.read_text().strip()
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", pid, "/F", "/T"], capture_output=True, creationflags=0x08000000)
    try:
        PIDFILE.unlink()
    except FileNotFoundError:
        pass
    return 0


def start_avatar():
    """The face on the screen (with the OFF button) is a small separate program."""
    try:
        import guts_settings
        if not guts_settings.get("show_avatar", True):
            return
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--avatar"]
        else:
            cmd = [sys.executable, str(Path(__file__).resolve()), "--avatar"]
        subprocess.Popen(cmd, close_fds=True)
        print("[Launcher] Face started.")
    except Exception as e:
        print(f"[Launcher] Could not start the face: {e}")


def status() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        running = False
    except OSError:
        running = True
    finally:
        s.close()
    message("Guts is RUNNING.\n\nTo turn him off: Start Menu, 'Guts AI - Stop'." if running
            else "Guts is OFF.\n\nTo turn him on: Start Menu, 'Guts AI'.")
    return 0


def run_wizard() -> bool:
    import guts_setup
    return bool(guts_setup.main())


def run_guts(login: bool) -> int:
    setup_log()
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        print("[Launcher] Guts is already running. Exiting this copy.")
        return 0
    PIDFILE.write_text(str(os.getpid()))
    atexit.register(lambda: PIDFILE.exists() and PIDFILE.unlink())

    import guts_settings
    if guts_settings.needs_setup():
        print("[Launcher] First run: opening the setup wizard.")
        if not run_wizard():
            print("[Launcher] Setup was not finished. Exiting.")
            return 0
    start_avatar()
    script = APP / MAIN_SCRIPT
    if not script.exists():
        message(f"{MAIN_SCRIPT} is missing from the app folder. Please reinstall Guts.")
        return 1
    # keys for this person's Guts
    try:
        from dotenv import load_dotenv
        load_dotenv(APP / ".env")
    except Exception:
        pass
    if login:
        print(f"[Launcher] Login start: waiting {LOGIN_DELAY} sec for mic, camera and network ...")
        time.sleep(LOGIN_DELAY)
    wait_for_internet()

    fails = 0
    while fails < MAX_QUICK_FAILS:
        started = time.time()
        print(f"[Launcher] Starting {script.name}")
        try:
            runpy.run_path(str(script), run_name="__main__")
            print("[Launcher] Guts stopped normally.")
            return 0
        except SystemExit:
            print("[Launcher] Guts exited.")
            return 0
        except BaseException:
            traceback.print_exc()
        fails = fails + 1 if time.time() - started < 60 else 1
        print(f"[Launcher] Crashed (quick fails: {fails}/{MAX_QUICK_FAILS}). Restarting in 10 sec ...")
        time.sleep(10)
    print("[Launcher] Too many quick crashes. Giving up. Read the lines above.")
    return 1


def main() -> int:
    args = [a.lower() for a in sys.argv[1:]]
    if "--selftest" in args:
        return selftest()
    if "--stop" in args:
        return stop()
    if "--status" in args:
        return status()
    if "--avatar" in args:
        import guts_avatar
        return guts_avatar.main(watch="--no-watch" not in args)
    if "--setup" in args:
        return 0 if run_wizard() else 1
    return run_guts(login="--login" in args)


if __name__ == "__main__":
    sys.exit(main())
