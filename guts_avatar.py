"""guts_avatar.py - the face of Guts on your screen (a small always-on-top window).

  - eyes and a glowing ring show what he is doing: idle, listening, speaking (mouth moves), working, sleeping, game
  - a subtitle bubble shows the words he is saying
  - the red power button at the top right is the OFF button: tap it twice (the first tap asks 'sure?')
  - the small moon button at the top left puts him to sleep / wakes him
  - drag the face anywhere; right-click for the menu (sleep, rename, settings, small face, turn OFF)
It runs as its own small program (Guts.exe --avatar) and talks to Guts through avatar_state.json and
avatar_cmd.json, so it can never freeze or crash the voice part. The picture is drawn with simple shapes
(an original helmet-and-visor face, not a copy of any character).
"""
import json
import math
import os
import signal
import socket
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import simpledialog

APP_DIR = Path(os.environ.get("GUTS_APP_DIR") or Path(__file__).resolve().parent)
STATE_FILE = APP_DIR / "avatar_state.json"
CMD_FILE = APP_DIR / "avatar_cmd.json"
PID_FILE = APP_DIR / "guts.pid"
LOCK_PORT = 47655

TRANSPARENT = "#010101"
COLORS = {                      # ring and eyes
    "idle": "#33c6ff", "listening": "#6f8cff", "speaking": "#3dffb0",
    "working": "#ffc933", "game": "#ff4d4d", "sleeping": "#59606e", "off": "#59606e",
}
BIG, COMPACT = (260, 310), (104, 104)


def _settings():
    import guts_settings
    return guts_settings


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259                                         # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_pid():
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None


def kill_guts():
    """Turns Guts OFF: stops the Guts program and everything it started."""
    pid = read_pid()
    if pid:
        if sys.platform == "win32":
            subprocess.Popen(["taskkill", "/PID", str(pid), "/F", "/T"], creationflags=0x08000000)
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    for f in (PID_FILE, STATE_FILE, CMD_FILE):
        try:
            f.unlink()
        except Exception:
            pass


class Avatar:
    def __init__(self, watch: bool = True):
        self.watch = watch
        self.root = tk.Tk()
        self.root.title("Guts")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        self.root.configure(bg=TRANSPARENT)
        self.compact = False
        self.subtitles = True
        self.hover = False
        self.armed_until = 0.0
        self.state, self.text, self.name = "idle", "", "Guts"
        self.state_seen = time.time()
        self.t0 = time.time()
        self.blink_until = 0.0
        self.next_blink = time.time() + 3
        self.pid_missing_since = 0.0
        self.drag = None
        self.last_pos = (0, 0)
        self.canvas = tk.Canvas(self.root, width=BIG[0], height=BIG[1], bg=TRANSPARENT, highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", self.on_menu)
        self.canvas.bind("<Enter>", lambda e: setattr(self, "hover", True))
        self.canvas.bind("<Leave>", lambda e: setattr(self, "hover", False))
        self.canvas.bind("<Double-Button-1>", lambda e: self.toggle_compact())
        self.menu = tk.Menu(self.root, tearoff=0)
        self.build_menu()
        self.apply_size(initial=True)
        self.load_name()
        self.root.after(33, self.tick)
        self.root.after(150, self.poll)

    # ---------- window ----------
    def apply_size(self, initial=False):
        w, h = COMPACT if self.compact else BIG
        self.canvas.config(width=w, height=h)
        x, y = self.root.winfo_x(), self.root.winfo_y()
        if initial:
            s = _settings().load()
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            x = s["avatar_x"] if s["avatar_x"] >= 0 else sw - w - 24
            y = s["avatar_y"] if s["avatar_y"] >= 0 else sh - h - 90
        self.root.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")

    def toggle_compact(self):
        self.compact = not self.compact
        self.apply_size()

    def build_menu(self):
        self.menu.delete(0, "end")
        self.menu.add_command(label="Wake up" if self.state == "sleeping" else "Sleep", command=self.toggle_sleep)
        self.menu.add_command(label="Rename ...", command=self.rename)
        self.menu.add_command(label="Settings ...", command=self.open_settings)
        self.menu.add_command(label="Subtitles on/off", command=lambda: setattr(self, "subtitles", not self.subtitles))
        self.menu.add_command(label="Big / small face", command=self.toggle_compact)
        self.menu.add_separator()
        self.menu.add_command(label="Turn OFF Guts", command=self.turn_off)
        self.menu.add_command(label="Close this face only", command=self.root.destroy)

    # ---------- actions ----------
    def send_cmd(self, cmd: str):
        try:
            CMD_FILE.write_text(json.dumps({"cmd": cmd, "t": time.time()}), encoding="utf-8")
        except Exception:
            pass

    def toggle_sleep(self):
        self.send_cmd("wake" if self.state == "sleeping" else "sleep")

    def turn_off(self):
        kill_guts()
        self.root.destroy()
        os._exit(0)

    def rename(self):
        n = simpledialog.askstring("Rename", "New name for your assistant:", parent=self.root, initialvalue=self.name)
        if n:
            msg = _settings().set_assistant_name(n)
            self.load_name()
            print(msg)

    def open_settings(self):
        exe = sys.executable
        cmd = [exe, "--setup"] if getattr(sys, "frozen", False) else [exe, str(APP_DIR / "guts_launcher.py"), "--setup"]
        subprocess.Popen(cmd)

    # ---------- mouse ----------
    def button_at(self, x, y):
        if self.compact:
            return None
        cx, cy = BIG[0] // 2, 196
        if (x - (cx + 66)) ** 2 + (y - (cy - 66)) ** 2 <= 15 ** 2:
            return "off"
        if (x - (cx - 66)) ** 2 + (y - (cy - 66)) ** 2 <= 15 ** 2:
            return "sleep"
        return None

    def on_press(self, e):
        self.drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y(), e.x, e.y, False)

    def on_drag(self, e):
        if not self.drag:
            return
        ox, oy, sx, sy, _ = self.drag
        if abs(e.x - sx) + abs(e.y - sy) > 4 or self.drag[4]:
            self.drag = (ox, oy, sx, sy, True)
            self.last_pos = (max(0, e.x_root - ox), max(0, e.y_root - oy))
            self.root.geometry(f"+{self.last_pos[0]}+{self.last_pos[1]}")

    def on_release(self, e):
        if not self.drag:
            return
        moved = self.drag[4]
        self.drag = None
        if moved:
            try:
                _settings().save({"avatar_x": self.last_pos[0], "avatar_y": self.last_pos[1]})
            except Exception:
                pass
            return
        b = self.button_at(e.x, e.y)
        if b == "sleep":
            self.toggle_sleep()
        elif b == "off":
            if time.time() < self.armed_until:
                self.turn_off()
            else:
                self.armed_until = time.time() + 3

    def on_menu(self, e):
        self.build_menu()
        self.menu.tk_popup(e.x_root, e.y_root)

    # ---------- data ----------
    def load_name(self):
        try:
            self.name = _settings().load().get("guts_name") or "Guts"
        except Exception:
            self.name = "Guts"

    def poll(self):
        now = time.time()
        try:
            d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if now - float(d.get("t", 0)) < 6:
                self.state, self.text, self.state_seen = d.get("state", "idle"), d.get("text", ""), now
            else:
                self.state, self.text = "idle", ""
        except Exception:
            if now - self.state_seen > 6:
                self.state, self.text = "idle", ""
        if int(now) % 3 == 0:
            self.load_name()
        if self.watch:
            pid = read_pid()
            if pid and pid_alive(pid):
                self.pid_missing_since = 0.0
            else:
                self.pid_missing_since = self.pid_missing_since or now
                if now - self.pid_missing_since > 5:        # Guts is gone: close the face too
                    self.root.destroy()
                    return
        self.root.after(150, self.poll)

    # ---------- drawing ----------
    def tick(self):
        try:
            self.draw(time.time())
        except tk.TclError:
            return
        self.root.after(33, self.tick)

    def draw(self, now: float):
        c = self.canvas
        c.delete("all")
        t = now - self.t0
        k = 0.36 if self.compact else 1.0
        w, h = COMPACT if self.compact else BIG
        cx, cy = w // 2, (h // 2 if self.compact else 196)
        color = COLORS.get(self.state, COLORS["idle"])
        asleep = self.state == "sleeping"

        # subtitle bubble
        if self.subtitles and self.text and not self.compact:
            tid = c.create_text(cx, 96, text=self.text[-170:], width=228, fill="#eef2f8", font=("Segoe UI", 10), justify="center", anchor="s")
            x1, y1, x2, y2 = c.bbox(tid)
            c.create_rectangle(x1 - 10, y1 - 7, x2 + 10, y2 + 7, fill="#1b2030", outline=color, width=2, tags="bubble")
            c.tag_lower("bubble", tid)

        # ring (pulses while listening, spins while working)
        r_ring = 74 * k
        pulse = 5 * k * math.sin(t * 7) if self.state == "listening" else 0
        c.create_oval(cx - r_ring - pulse, cy - r_ring - pulse, cx + r_ring + pulse, cy + r_ring + pulse,
                      outline=color, width=max(2, int(4 * k + 1)))
        if self.state == "working":
            c.create_arc(cx - r_ring, cy - r_ring, cx + r_ring, cy + r_ring, start=(t * 260) % 360, extent=80,
                         style="arc", outline="#ffffff", width=max(2, int(5 * k)))
        # face disc
        r = 64 * k
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#141720", outline="#262c3d", width=2)
        # visor line
        c.create_rectangle(cx - 52 * k, cy - 20 * k, cx + 52 * k, cy + 2 * k, fill="#0c0e14", outline="")

        # eyes (angular visor eyes; blink; look sideways while working; shut when asleep)
        if now > self.next_blink:
            self.blink_until, self.next_blink = now + 0.13, now + 2.5 + (hash(int(now)) % 30) / 10
        blinking = now < self.blink_until
        look = 5 * k * math.sin(t * 3) if self.state == "working" else 0
        eye_color = "#7a8294" if asleep else color
        for sign in (-1, 1):
            ex = cx + sign * 27 * k + look
            ey = cy - 9 * k
            if asleep or blinking:
                c.create_line(ex - 14 * k, ey + 2 * k, ex + 14 * k, ey + 2 * k, fill=eye_color, width=max(2, int(3 * k + 1)))
            else:
                top = 10 * k if self.state in ("listening", "game") else 8 * k
                a, b = (0.4, 1.0) if sign < 0 else (1.0, 0.4)          # inner corner higher = angry visor look
                pts = [ex - 14 * k, ey - top * a, ex + 14 * k, ey - top * b,
                       ex + 12 * k, ey + 7 * k, ex - 12 * k, ey + 7 * k]
                c.create_polygon(pts, fill=eye_color, outline="")
        # mouth
        my = cy + 30 * k
        if self.state == "speaking":
            hgt = (3 + 11 * abs(math.sin(t * 13)) * abs(math.sin(t * 5.3 + 1))) * k
            c.create_rectangle(cx - 14 * k, my - hgt / 2, cx + 14 * k, my + hgt / 2, fill=color, outline="")
        else:
            c.create_rectangle(cx - 12 * k, my - 1.5 * k, cx + 12 * k, my + 1.5 * k, fill="#3a4152" if asleep else "#566079", outline="")
        if asleep and not self.compact:
            for i in range(3):
                zz = (t * 0.6 + i / 3.0) % 1
                c.create_text(cx + 40 + zz * 26, cy - 50 - zz * 40, text="z", fill="#9aa3b5", font=("Segoe UI", int(10 + 6 * zz), "bold"))

        if self.compact:
            return
        # name tag
        tid = c.create_text(cx, h - 16, text=self.name, fill="#ffffff", font=("Segoe UI", 11, "bold"))
        x1, y1, x2, y2 = c.bbox(tid)
        c.create_rectangle(x1 - 10, y1 - 2, x2 + 10, y2 + 2, fill="#1b2030", outline=color, width=1, tags="tag")
        c.tag_lower("tag", tid)
        # buttons (clear when the mouse is on the face, faint otherwise)
        armed = now < self.armed_until
        a = 1.0 if (self.hover or armed) else 0.0
        bx, by = cx + 66, cy - 66
        c.create_oval(bx - 15, by - 15, bx + 15, by + 15, fill="#ff3b3b" if armed else ("#3a1114" if a else "#22141a"),
                      outline="#ff8a8a" if a else "#4a2a2f", width=2)
        c.create_arc(bx - 7, by - 6, bx + 7, by + 8, start=125, extent=290, style="arc", outline="#ffffff" if a else "#8a6a6e", width=2)
        c.create_line(bx, by - 9, bx, by - 1, fill="#ffffff" if a else "#8a6a6e", width=2)
        if armed:
            c.create_text(bx - 20, by + 28, text="tap again to turn OFF", fill="#ff9a9a", font=("Segoe UI", 8, "bold"), anchor="e")
        sx, sy = cx - 66, cy - 66
        c.create_oval(sx - 15, sy - 15, sx + 15, sy + 15, fill="#1d2233" if a else "#171b29", outline="#7f8bb0" if a else "#343b52", width=2)
        if asleep:
            c.create_oval(sx - 6, sy - 6, sx + 6, sy + 6, fill="#ffd66b" if a else "#8a7a4a", outline="")
        else:
            c.create_oval(sx - 7, sy - 7, sx + 7, sy + 7, fill="#cfd8f5" if a else "#7a829c", outline="")
            c.create_oval(sx - 2, sy - 9, sx + 10, sy + 5, fill="#1d2233" if a else "#171b29", outline="")

    def run(self):
        self.root.mainloop()


def main(watch: bool = True) -> int:
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        return 0                     # a face is already on the screen
    Avatar(watch=watch).run()
    return 0


if __name__ == "__main__":
    sys.exit(main(watch="--no-watch" not in sys.argv))
