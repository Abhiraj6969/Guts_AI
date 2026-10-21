"""guts_setup.py - the first-run wizard. It makes this PC's user the Boss of this Guts.

Pages: 1 who you are + consent | 2 your Gemini key | 3 browser and country code | 4 contacts |
       5 face lock | 6 microphone | 7 finish
Everything is saved only on this PC (guts_settings.json, .env, contacts.json, boss_face.npy).
"""
import contextlib
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from pathlib import Path

import guts_settings as gs

KEY_URL = "https://aistudio.google.com/apikey"


def _no_window():
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}


class _QueueWriter:
    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(s)

    def flush(self):
        pass


class Wizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Guts AI setup")
        self.geometry("680x560")
        self.resizable(False, False)
        self.s = gs.load()
        self.done = False
        self.q = queue.Queue()
        self.vars = {}
        self.idx = 0
        self.pages = [self.page_welcome, self.page_key, self.page_browser, self.page_contacts,
                      self.page_face, self.page_mic, self.page_finish]
        self.body = ttk.Frame(self, padding=18)
        self.body.pack(fill="both", expand=True)
        nav = ttk.Frame(self, padding=(18, 0, 18, 14))
        nav.pack(fill="x")
        self.step = ttk.Label(nav, text="")
        self.step.pack(side="left")
        self.btn_next = ttk.Button(nav, text="Next", command=self.go_next)
        self.btn_next.pack(side="right")
        self.btn_back = ttk.Button(nav, text="Back", command=self.go_back)
        self.btn_back.pack(side="right", padx=8)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(150, self.pump)
        self.show(0)

    # ---------- plumbing ----------
    def pump(self):
        try:
            while True:
                item = self.q.get_nowait()
                item()
        except queue.Empty:
            pass
        self.after(150, self.pump)

    def call_ui(self, fn):
        self.q.put(fn)

    def clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def title_label(self, text, sub=""):
        ttk.Label(self.body, text=text, font=("Segoe UI", 15, "bold")).pack(anchor="w")
        if sub:
            ttk.Label(self.body, text=sub, wraplength=620, justify="left").pack(anchor="w", pady=(4, 12))

    def show(self, i):
        self.idx = i
        self.clear()
        self.validate = self.pages[i]()
        self.step.config(text=f"Step {i + 1} of {len(self.pages)}")
        self.btn_back.state(["!disabled"] if i > 0 else ["disabled"])
        self.btn_next.config(text="Finish" if i == len(self.pages) - 1 else "Next")

    def go_next(self):
        if self.validate and not self.validate():
            return
        if self.idx == len(self.pages) - 1:
            self.finish()
        else:
            self.show(self.idx + 1)

    def go_back(self):
        if self.idx > 0:
            self.show(self.idx - 1)

    def on_close(self):
        if messagebox.askyesno("Guts AI", "Stop the setup? Guts cannot start until it is finished."):
            self.destroy()

    # ---------- page 1 ----------
    def page_welcome(self):
        self.title_label("Welcome. Who is the Boss?",
                         "Guts belongs to ONE person: you. He will call you by the name you choose, and only "
                         "your face (if you turn face lock on) can give him orders.")
        f = ttk.Frame(self.body)
        f.pack(fill="x")
        v_name = self.vars.setdefault("name", tk.StringVar(value="" if self.s["boss_name"] == "Boss" else self.s["boss_name"]))
        v_gname = self.vars.setdefault("gname", tk.StringVar(value=self.s.get("guts_name", "Guts")))
        v_lang = self.vars.setdefault("lang", tk.StringVar(value=self.s["language"]))
        v_pers = self.vars.setdefault("pers", tk.StringVar(value=self.s["persona"]))
        v_cons = self.vars.setdefault("consent", tk.BooleanVar(value=bool(self.s["consent"])))
        ttk.Label(f, text="What should Guts call you?").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=v_name, width=30).grid(row=0, column=1, sticky="w", padx=10)
        ttk.Label(f, text="Name of your assistant").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=v_gname, width=30).grid(row=1, column=1, sticky="w", padx=10)
        ttk.Label(f, text="Language").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Combobox(f, textvariable=v_lang, values=list(gs.LANGUAGES), state="readonly", width=28).grid(row=2, column=1, sticky="w", padx=10)
        ttk.Label(f, text="Personality").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Combobox(f, textvariable=v_pers, values=list(gs.PERSONAS), state="readonly", width=28).grid(row=3, column=1, sticky="w", padx=10)
        self.persona_note = ttk.Label(self.body, text="", wraplength=620, foreground="#555")
        self.persona_note.pack(anchor="w", pady=(2, 10))
        v_pers.trace_add("write", lambda *a: self.persona_note.config(text=gs.PERSONAS.get(v_pers.get(), "")))
        self.persona_note.config(text=gs.PERSONAS.get(v_pers.get(), ""))
        tk.Checkbutton(self.body, variable=v_cons, wraplength=600, justify="left", anchor="w",
                       text="I understand: Guts uses my microphone and sends my voice to Google Gemini, and uses my "
                            "camera on this PC (the face check stays on this PC).").pack(anchor="w", pady=10)

        def ok():
            if not self.vars["name"].get().strip():
                messagebox.showwarning("Guts AI", "Please type the name Guts should call you.")
                return False
            g = self.vars["gname"].get().strip()
            if not (2 <= len(g) <= 20):
                messagebox.showwarning("Guts AI", "The assistant's name needs 2 to 20 letters (you can keep Guts).")
                return False
            if not self.vars["consent"].get():
                messagebox.showwarning("Guts AI", "Please tick the box to continue.")
                return False
            return True
        return ok

    # ---------- page 2 ----------
    def page_key(self):
        self.title_label("Your Gemini key",
                         "Guts thinks with Google Gemini. Every person uses their OWN free key, so nobody shares "
                         "limits. Click the button, sign in with Google, press Create API key, copy it and paste it here.")
        ttk.Button(self.body, text="Open Google AI Studio (get a free key)", command=lambda: webbrowser.open(KEY_URL)).pack(anchor="w")
        env = gs.read_env()
        v1 = self.vars.setdefault("key1", tk.StringVar(value=env.get("GEMINI_API_KEY", "")))
        v2 = self.vars.setdefault("key2", tk.StringVar(value=env.get("GEMINI_WORK_KEY", "")))
        f = ttk.Frame(self.body)
        f.pack(fill="x", pady=12)
        ttk.Label(f, text="Gemini key").grid(row=0, column=0, sticky="w", pady=6)
        e1 = ttk.Entry(f, textvariable=v1, width=52, show="*")
        e1.grid(row=0, column=1, padx=10)
        ttk.Label(f, text="Second key (optional)").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=v2, width=52, show="*").grid(row=1, column=1, padx=10)
        show = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Show the key", variable=show, command=lambda: e1.config(show="" if show.get() else "*")).grid(row=2, column=1, sticky="w", padx=10)
        self.key_msg = ttk.Label(self.body, text="", wraplength=620)
        self.key_msg.pack(anchor="w", pady=6)
        ttk.Label(self.body, text="The second key is only for heavy jobs (coding, game reading). Leave it empty to use the first one.",
                  wraplength=620, foreground="#555").pack(anchor="w")

        def ok():
            key = self.vars["key1"].get().strip()
            self.key_msg.config(text="Checking the key ...")
            self.update_idletasks()
            good, msg = gs.validate_gemini_key(key)
            self.key_msg.config(text=msg)
            if good is False:
                return False
            if good is None and not messagebox.askyesno("Guts AI", msg + "\n\nContinue anyway?"):
                return False
            return True
        return ok

    # ---------- page 3 ----------
    def page_browser(self):
        self.title_label("Browser and phone country code",
                         "Guts opens websites and YouTube in this browser. The country code is used for WhatsApp contacts.")
        found = gs.detect_browsers()
        choices = ["auto"] + list(found)
        cur = self.s["browser"] if self.s["browser"] in choices else "auto"
        v_br = self.vars.setdefault("browser", tk.StringVar(value=cur))
        v_cc = self.vars.setdefault("cc", tk.StringVar(value=self.s.get("country_code", "91")))
        f = ttk.Frame(self.body)
        f.pack(fill="x")
        ttk.Label(f, text="Browser").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Combobox(f, textvariable=v_br, values=choices, state="readonly", width=20).grid(row=0, column=1, padx=10)
        ttk.Label(f, text="Country code (91 = India)").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=v_cc, width=8).grid(row=1, column=1, sticky="w", padx=10)
        ttk.Label(self.body, text="Found on this PC: " + (", ".join(found) or "no known browser, the default one will be used")
                  + ".  'auto' means Brave if you have it, otherwise your default browser.", wraplength=620,
                  foreground="#555").pack(anchor="w", pady=12)
        return lambda: True

    # ---------- page 4 ----------
    def page_contacts(self):
        self.title_label("WhatsApp contacts (optional)",
                         "Type the name you will SAY to Guts and the phone number. Example: mummy, 98xxxxxxxx. "
                         "You can leave this empty and add contacts later in contacts.json.")
        self.contact_rows = []
        grid = ttk.Frame(self.body)
        grid.pack(fill="x")
        ttk.Label(grid, text="Name (say it like this)").grid(row=0, column=0, sticky="w")
        ttk.Label(grid, text="Phone number").grid(row=0, column=1, sticky="w", padx=10)
        existing = []
        try:
            import json
            existing = list(json.loads(gs.CONTACTS_FILE.read_text(encoding="utf-8")).items())
        except Exception:
            pass

        def add_row(name="", num=""):
            r = len(self.contact_rows) + 1
            a, b = tk.StringVar(value=name), tk.StringVar(value=num)
            ttk.Entry(grid, textvariable=a, width=24).grid(row=r, column=0, pady=3)
            ttk.Entry(grid, textvariable=b, width=24).grid(row=r, column=1, padx=10, pady=3)
            self.contact_rows.append((a, b))
        for n, p in (existing or [("", "")] * 3):
            add_row(n, p)
        ttk.Button(self.body, text="Add another contact", command=add_row).pack(anchor="w", pady=10)

        def ok():
            rows = [(a.get(), b.get()) for a, b in self.contact_rows]
            count, problems = gs.save_contacts(rows, self.vars["cc"].get() or "91")
            if problems:
                return messagebox.askyesno("Guts AI", "These contacts were skipped:\n" + "\n".join(problems[:6]) + "\n\nContinue?")
            return True
        return ok

    # ---------- page 5 ----------
    def page_face(self):
        self.title_label("Face lock (recommended)",
                         "With face lock, only YOUR face can give Guts orders. The face check runs only on this PC.")
        v_lock = self.vars.setdefault("face_lock", tk.BooleanVar(value=bool(self.s["face_lock"])))
        v_cam = self.vars.setdefault("cam", tk.IntVar(value=int(self.s["camera_index"])))
        ttk.Checkbutton(self.body, text="Turn face lock on", variable=v_lock).pack(anchor="w")
        f = ttk.Frame(self.body)
        f.pack(fill="x", pady=8)
        ttk.Label(f, text="Camera number").grid(row=0, column=0)
        ttk.Spinbox(f, from_=0, to=4, textvariable=v_cam, width=4).grid(row=0, column=1, padx=8)
        ttk.Button(f, text="Test camera", command=self.test_camera).grid(row=0, column=2)
        self.btn_enroll = ttk.Button(f, text="Enroll my face", command=self.enroll_face)
        self.btn_enroll.grid(row=0, column=3, padx=12)
        self.preview = ttk.Label(self.body, text="(camera picture shows here)")
        self.preview.pack(anchor="w")
        self.face_log = scrolledtext.ScrolledText(self.body, height=7, width=78, state="disabled")
        self.face_log.pack(anchor="w", pady=6)
        ttk.Label(self.body, text="Enrolling: sit where you normally sit, with normal light, only you in the picture, "
                  "and follow the pose messages.", wraplength=620, foreground="#555").pack(anchor="w")

        def ok():
            if self.vars["face_lock"].get() and not (gs.APP_DIR / "boss_face.npy").exists():
                return messagebox.askyesno("Guts AI", "Your face is not enrolled yet. Without it face lock stays OFF.\n\nContinue anyway?")
            return True
        return ok

    def log_face(self, text):
        self.face_log.config(state="normal")
        self.face_log.insert("end", text)
        self.face_log.see("end")
        self.face_log.config(state="disabled")

    def test_camera(self):
        idx = int(self.vars["cam"].get())

        def work():
            try:
                import cv2
                from PIL import Image, ImageTk
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(idx)
                ok, frame = (cap.read() if cap.isOpened() else (False, None))
                cap.release()
                if not ok:
                    self.call_ui(lambda: self.preview.config(text=f"Camera {idx} did not give a picture. Try another number."))
                    return
                img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).resize((240, 180))

                def show():
                    self._photo = ImageTk.PhotoImage(img)
                    self.preview.config(image=self._photo, text="")
                self.call_ui(show)
            except Exception as e:
                self.call_ui(lambda: self.preview.config(text=f"Camera test failed: {str(e)[:80]}"))
        threading.Thread(target=work, daemon=True).start()

    def enroll_face(self):
        idx = int(self.vars["cam"].get())
        self.btn_enroll.state(["disabled"])
        self.log_face("Loading face models (the first time this downloads about 40 MB) ...\n")
        out = queue.Queue()

        def work():
            try:
                import face_guard
                face_guard.CAMERA_INDEX = idx
                with contextlib.redirect_stdout(_QueueWriter(out)):
                    face_guard.enroll()
            except Exception as e:
                out.put(f"\nEnroll failed: {e}\n")
            out.put(None)
        threading.Thread(target=work, daemon=True).start()

        def drain():
            try:
                while True:
                    item = out.get_nowait()
                    if item is None:
                        self.btn_enroll.state(["!disabled"])
                        return
                    self.log_face(item)
            except queue.Empty:
                pass
            self.after(300, drain)
        drain()

    # ---------- page 6 ----------
    def page_mic(self):
        self.title_label("Microphone check", "Click the button, then say something for 2 seconds. Use headphones with Guts, "
                         "otherwise he hears himself.")
        ttk.Button(self.body, text="Test microphone", command=self.test_mic).pack(anchor="w")
        self.mic_bar = ttk.Progressbar(self.body, length=300, maximum=100)
        self.mic_bar.pack(anchor="w", pady=10)
        self.mic_msg = ttk.Label(self.body, text="", wraplength=620)
        self.mic_msg.pack(anchor="w")
        return lambda: True

    def test_mic(self):
        def work():
            try:
                import array
                import math
                import pyaudio
                pa = pyaudio.PyAudio()
                st = pa.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
                peak = 0
                t0 = time.time()
                while time.time() - t0 < 2:
                    samples = array.array('h', st.read(1024, False))
                    rms = math.sqrt(sum(x * x for x in samples) / max(1, len(samples)))
                    peak = max(peak, rms)
                st.close()
                pa.terminate()
                pct = min(100, int(peak / 80))
                msg = "I hear you. The microphone works." if pct > 8 else "Very quiet. Speak louder, or choose the right microphone in Windows Sound settings."
                self.call_ui(lambda: (self.mic_bar.config(value=pct), self.mic_msg.config(text=msg)))
            except Exception as e:
                self.call_ui(lambda: self.mic_msg.config(text=f"Microphone test failed: {str(e)[:90]}"))
        threading.Thread(target=work, daemon=True).start()

    # ---------- page 7 ----------
    def page_finish(self):
        self.title_label("All set", "Last choices. You can change everything later from the Guts_AI settings file.")
        v_auto = self.vars.setdefault("auto", tk.BooleanVar(value=False))
        v_ff = self.vars.setdefault("ffmpeg", tk.BooleanVar(value=False))
        v_go = self.vars.setdefault("go", tk.BooleanVar(value=True))
        v_face = self.vars.setdefault("avatar", tk.BooleanVar(value=bool(self.s.get("show_avatar", True))))
        ttk.Checkbutton(self.body, text="Show my assistant's face on the screen (with an OFF button)", variable=v_face).pack(anchor="w", pady=4)
        ttk.Checkbutton(self.body, text="Start Guts when I log in to Windows", variable=v_auto).pack(anchor="w", pady=4)
        ttk.Checkbutton(self.body, text="Install the video tools (FFmpeg) now, needed for video editing", variable=v_ff).pack(anchor="w", pady=4)
        ttk.Checkbutton(self.body, text="Start Guts now", variable=v_go).pack(anchor="w", pady=4)
        ttk.Label(self.body, text=f"Boss: {self.vars['name'].get()}   |   Assistant: {self.vars['gname'].get()}   |   Language: {self.vars['lang'].get()}   |   "
                  f"Personality: {self.vars['pers'].get()}   |   Face lock: {'on' if self.vars['face_lock'].get() else 'off'}",
                  wraplength=620, foreground="#555").pack(anchor="w", pady=14)
        return lambda: True

    # ---------- finish ----------
    def finish(self):
        v = self.vars
        face_ok = (gs.APP_DIR / "boss_face.npy").exists()
        s = gs.load()
        s.update(boss_name=v["name"].get().strip(), guts_name=v["gname"].get().strip() or "Guts",
                 show_avatar=bool(v["avatar"].get()), language=v["lang"].get(), persona=v["pers"].get(),
                 browser=v["browser"].get(), country_code=v["cc"].get().strip() or "91",
                 face_lock=bool(v["face_lock"].get() and face_ok), camera_index=int(v["cam"].get()),
                 consent=True, first_run_done=True)
        gs.save(s)
        keys = {"GEMINI_API_KEY": v["key1"].get().strip()}
        keys["GEMINI_WORK_KEY"] = v["key2"].get().strip() or keys["GEMINI_API_KEY"]
        gs.write_env(keys)
        exe = sys.executable if getattr(sys, "frozen", False) else ""
        if v["auto"].get() and exe:
            try:
                gs.set_autostart(True, exe)
            except Exception as e:
                messagebox.showwarning("Guts AI", f"Could not set start-up: {e}")
        elif exe:
            try:
                gs.set_autostart(False, exe)
            except Exception:
                pass
        if v["ffmpeg"].get() and sys.platform == "win32":
            subprocess.Popen(["winget", "install", "--id", "Gyan.FFmpeg", "-e", "--accept-source-agreements",
                              "--accept-package-agreements"], **_no_window())
        self.done = True
        if v["go"].get() and exe and "--run-after" in sys.argv:
            subprocess.Popen([exe], close_fds=True)
        self.destroy()


def main() -> bool:
    w = Wizard()
    w.mainloop()
    return w.done


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
