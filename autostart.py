"""autostart.py - make Guts start by himself when you log in to Windows (no terminal window).

  python autostart.py install   -> create the Startup shortcut
  python autostart.py remove    -> delete it
  python autostart.py status    -> show what is set up
  python autostart.py stop      -> stop the running Guts

Run it with the SAME python you use for Guts (the venv one if you made guts_env).
"""
import os
import sys
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent
LAUNCHER = BASE / "start_guts.pyw"
PIDFILE = BASE / "guts.pid"
STARTUP = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
LNK = STARTUP / "Guts AI.lnk"


def pythonw() -> Path:
    venv = BASE / "guts_env" / "Scripts" / "pythonw.exe"
    if venv.exists():
        return venv
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return cand if cand.exists() else exe


def ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def shortcut_script() -> str:
    return (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(" + ps_quote(str(LNK)) + ");"
        "$s.TargetPath=" + ps_quote(str(pythonw())) + ";"
        "$s.Arguments=" + ps_quote(f'"{LAUNCHER}" --login') + ";"
        "$s.WorkingDirectory=" + ps_quote(str(BASE)) + ";"
        "$s.WindowStyle=7;$s.Description='Guts AI';$s.Save()"
    )


def install():
    if sys.platform != "win32":
        print("This works on Windows only.")
        return
    if not LAUNCHER.exists():
        print(f"Cannot find {LAUNCHER}. Put start_guts.pyw in this folder.")
        return
    STARTUP.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["powershell", "-NoProfile", "-Command", shortcut_script()],
                       capture_output=True, text=True)
    if r.returncode != 0 or not LNK.exists():
        print("Could not create the shortcut:", r.stderr.strip() or r.stdout.strip())
        return
    print(f"Done. Guts will start at login using:\n  {pythonw()}\n  {LAUNCHER}")
    print("Test now without restarting:  double-click 'Guts AI' in the Startup folder, or run:")
    print(f'  "{pythonw()}" "{LAUNCHER}"')
    print("Then read guts.log in this folder.")


def remove():
    if LNK.exists():
        LNK.unlink()
        print("Removed. Guts will no longer start at login.")
    else:
        print("Nothing to remove.")


def pid_running(pid: int) -> bool:
    try:
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
        return str(pid) in r.stdout
    except Exception:
        return False


def status():
    print(f"Startup shortcut : {'YES' if LNK.exists() else 'no'}  ({LNK})")
    print(f"Launcher         : {'found' if LAUNCHER.exists() else 'MISSING'}")
    print(f"Python used      : {pythonw()}")
    pid = int(PIDFILE.read_text()) if PIDFILE.exists() and PIDFILE.read_text().strip().isdigit() else None
    print(f"Guts running now : {'YES (pid ' + str(pid) + ')' if pid and pid_running(pid) else 'no'}")
    print(f"Log file         : {BASE / 'guts.log'}")


def stop():
    if not PIDFILE.exists():
        print("Guts is not running (no guts.pid).")
        return
    pid = PIDFILE.read_text().strip()
    r = subprocess.run(["taskkill", "/PID", pid, "/F", "/T"], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    try:
        PIDFILE.unlink()
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"install": install, "remove": remove, "status": status, "stop": stop}.get(cmd, lambda: print(__doc__))()
