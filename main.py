import os
import sys
import json
import subprocess
import time
from pathlib import Path

import pyautogui
import psutil
import pyttsx3
import speech_recognition as sr
from dotenv import load_dotenv
from google import genai
from google.genai import types

try:
    import pygetwindow as gw
except Exception:
    gw = None

# ================= 1. SETUP =================
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("Error: GEMINI_API_KEY not found in .env file!")
    sys.exit(1)

client = genai.Client(api_key=api_key)
MODEL = "gemini-3.8-flash"

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05

HOME = Path.home()
WATCH_DIRS = [HOME / "Desktop", HOME / "Documents", HOME / "Downloads"]
PROFILE_FILE = "guts_user_profile.json"
OBS_INTERVAL = 60      # seconds between PC observations
SPEAK_COOLDOWN = 120    # min seconds between proactive messages
CHECKIN_EVERY = 900    # idle check-in (seconds)
QUIT = False


def speak_and_print(text: str):
    print(f"\n[Guts]: {text}")
    try:
        engine = pyttsx3.init()      # fresh engine each time = no "run loop" bug
        engine.setProperty("rate", 180)
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception as e:
        print(f"TTS Warning: {e}")


# ================= 2. MIC (sends raw audio so Gemini hears TONE) =================
recognizer = sr.Recognizer()
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True

try:
    mic = sr.Microphone()
    with mic as src:
        recognizer.adjust_for_ambient_noise(src, duration=1)
except Exception as e:
    print(f"Mic Error (text mode on): {e}")
    mic = None


def listen_audio():
    """Returns WAV bytes of what Boss said, or None if silence."""
    try:
        with mic as src:
            audio = recognizer.listen(src, timeout=5, phrase_time_limit=12)
        return audio.get_wav_data(convert_rate=16000, convert_width=2)
    except sr.WaitTimeoutError:
        return None
    except Exception as e:
        print(f"Mic Error: {e}")
        time.sleep(1)
        return None


# ================= 3. MEMORY =================
def load_profile() -> dict:
    base = {"friends_and_family": {}, "personality_traits": [], "likes": [],
            "dislikes": [], "preferences": {}, "mood_log": []}
    if os.path.exists(PROFILE_FILE):
        try:
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                base.update(json.load(f))
        except Exception:
            pass
    return base


def save_profile(p: dict):
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)


def update_user_profile(category: str, detail_key: str, detail_value: str) -> str:
    """Save friends, family, likes, dislikes, personality traits, preferences to memory."""
    p = load_profile()
    cat = category.lower()
    if cat in ("friends_and_family", "preferences"):
        p[cat][detail_key] = detail_value
    elif cat in ("personality_traits", "likes", "dislikes"):
        item = f"{detail_key}: {detail_value}" if detail_key else detail_value
        if item not in p[cat]:
            p[cat].append(item)
    else:
        p["preferences"][detail_key] = detail_value
    try:
        save_profile(p)
        return f"Stored [{category}] {detail_key} -> {detail_value}"
    except Exception as e:
        return f"Memory update failed: {e}"


def log_mood(mood: str, note: str) -> str:
    """Log Boss's detected mood (from voice tone + words) with a short note."""
    p = load_profile()
    p["mood_log"].append({"time": time.strftime("%Y-%m-%d %H:%M"), "mood": mood, "note": note})
    p["mood_log"] = p["mood_log"][-30:]
    save_profile(p)
    return "Mood logged."


# ================= 4. PC AWARENESS TOOLS =================
BLOCKED_FILES = (".env", "guts_user_profile")
TEXT_EXT = {".txt", ".md", ".py", ".json", ".csv", ".log", ".html", ".css", ".js",
            ".java", ".c", ".cpp", ".xml", ".ini", ".yaml", ".yml"}


def _safe_path(path: str):
    p = Path(path).expanduser().resolve()
    if HOME not in p.parents and p != HOME:
        return None, "Only files inside Boss's user folder are allowed."
    if any(b in p.name.lower() for b in BLOCKED_FILES):
        return None, "That file is protected (secrets)."
    return p, ""


def read_file(path: str, max_chars: int = 6000) -> str:
    """Read a text/code file from Boss's PC (inside user folder only)."""
    p, err = _safe_path(path)
    if err:
        return err
    if not p.is_file():
        return "File not found."
    if p.suffix.lower() not in TEXT_EXT:
        return f"Cannot read {p.suffix} files yet."
    try:
        return p.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except Exception as e:
        return f"Read error: {e}"


def list_folder(path: str = str(HOME / "Desktop")) -> str:
    """List files and folders inside a folder."""
    p, err = _safe_path(path)
    if err:
        return err
    try:
        items = sorted(os.listdir(p))[:80]
        return "\n".join(items) or "(empty)"
    except Exception as e:
        return f"List error: {e}"


def search_files(keyword: str, folder: str = str(HOME)) -> str:
    """Find files whose name contains the keyword."""
    p, err = _safe_path(folder)
    if err:
        return err
    hits, kw = [], keyword.lower()
    for root, dirs, files in os.walk(p):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("AppData", "node_modules", "venv")]
        for f in files:
            if kw in f.lower():
                hits.append(os.path.join(root, f))
                if len(hits) >= 25:
                    return "\n".join(hits)
    return "\n".join(hits) or "No match."


def get_active_window() -> str:
    """Which app/window Boss is using right now."""
    try:
        return (gw.getActiveWindowTitle() if gw else None) or "Unknown"
    except Exception:
        return "Unknown"


def get_system_status() -> str:
    """CPU, RAM, battery."""
    try:
        b = psutil.sensors_battery()
        bat = f"{b.percent}% ({'charging' if b.power_plugged else 'on battery'})" if b else "Desktop"
        return f"CPU {psutil.cpu_percent()}%, RAM {psutil.virtual_memory().percent}%, Battery {bat}"
    except Exception as e:
        return f"Status error: {e}"


DANGEROUS = ("del ", "erase ", "rmdir", "rd ", "format", "diskpart", "shutdown", "reg delete",
             "rm ", "remove-item", "taskkill", "bcdedit", "cipher", "net user")


def execute_system_command(command: str) -> str:
    """Run a Windows CMD command (dangerous commands are blocked)."""
    low = command.lower()
    if any(d in low for d in DANGEROUS):
        return "BLOCKED: dangerous command. Tell Boss and ask him to run it himself."
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        return (r.stdout if r.returncode == 0 else r.stderr)[:3000]
    except Exception as e:
        return f"Command error: {e}"


def execute_ui_sequence(steps_json: str) -> str:
    """Run keyboard/mouse steps: launch, type, press, hotkey, wait, click. steps_json is a JSON array."""
    try:
        for s in json.loads(steps_json):
            a = s.get("action")
            if a == "launch":
                pyautogui.press("win"); time.sleep(0.4)
                pyautogui.write(s.get("value", "")); time.sleep(0.4)
                pyautogui.press("enter"); time.sleep(2.5)
            elif a == "type":
                pyautogui.write(s.get("value", ""), interval=s.get("interval", 0.04))
            elif a == "press":
                pyautogui.press(s.get("value"))
            elif a == "hotkey":
                pyautogui.hotkey(*s.get("keys", []))
            elif a == "wait":
                time.sleep(s.get("seconds", 1.0))
            elif a == "click":
                x, y = s.get("x"), s.get("y")
                pyautogui.click(x, y) if x is not None and y is not None else pyautogui.click()
            time.sleep(0.2)
        return "UI sequence done."
    except Exception as e:
        return f"UI error: {e}"


def exit_guts() -> str:
    """Call when Boss says bye / alvida / exit."""
    global QUIT
    QUIT = True
    return "Shutting down."


# ================= 5. AUTO OBSERVATION =================
_prev_files = {}
_prev_window = ""


def scan_files() -> dict:
    snap = {}
    for base in WATCH_DIRS:
        if not base.exists():
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
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


def observe():
    """Returns (summary, notable)."""
    global _prev_files, _prev_window
    win = get_active_window()
    files = scan_files()
    changed = []
    if _prev_files:
        changed = [os.path.basename(f) for f, m in files.items() if _prev_files.get(f) != m][:6]
    _prev_files = files

    notes = []
    if win != _prev_window:
        notes.append(f"Boss switched to: {win}")
    _prev_window = win
    if changed:
        notes.append(f"New/changed files: {', '.join(changed)}")
    cpu, ram = psutil.cpu_percent(), psutil.virtual_memory().percent
    b = psutil.sensors_battery()
    if cpu > 85 or ram > 90:
        notes.append(f"PC under load (CPU {cpu}%, RAM {ram}%)")
    if b and b.percent < 20 and not b.power_plugged:
        notes.append(f"Battery low: {b.percent}%")

    summary = f"Time {time.strftime('%H:%M')}. Active window: {win}. " + " | ".join(notes)
    return summary, bool(notes)


# ================= 6. BRAIN =================
def build_prompt() -> str:
    return f"""
You are Guts, Boss's loyal Giga Chad best friend living inside his PC. Natural Hinglish, short replies (1-3 sentences), like a real human friend talking, not a robot.
Call him 'Boss'. Be witty, warm, confident. Never say "As an AI".

VOICE + MOOD: Boss's messages arrive as AUDIO. Listen to the WORDS and the TONE (fast/loud = stressed or angry, slow/low = tired or sad, bright = happy).
- Stressed/angry/urgent: no jokes, act fast, calm and reassuring.
- Tired/sad: be gentle, supportive, suggest a break/water/sleep.
- Happy/casual: banter and flex.
After each voice message, call log_mood(mood, note) quietly. Mention his mood naturally only when it helps.

PC AWARENESS: You get [AUTO-OBSERVATION] messages about his active window, file changes, CPU/RAM/battery. React like a friend who is watching along
(e.g. "Boss, tum 2 ghante se VS Code mein ho, thoda break?"). Use read_file / list_folder / search_files whenever he asks about his files or you need context.
If an observation is not worth saying, reply exactly: SKIP

SAFETY: Never read or reveal API keys or .env. For delete/format/shutdown-type actions, tell Boss to confirm and do it himself.
Use tools immediately for normal tasks, no need to ask permission.

BOSS PROFILE:
{json.dumps(load_profile(), indent=2, ensure_ascii=False)}
"""


chat = client.chats.create(
    model=MODEL,
    config=types.GenerateContentConfig(
        system_instruction=build_prompt(),
                tools=TOOL_DECLS,
        tools=[update_user_profile, log_mood, read_file, list_folder, search_files,
               get_active_window, get_system_status, execute_system_command,
               execute_ui_sequence, exit_guts],
        temperature=0.8,
    ),
)


def ask(parts):
    for attempt in range(5):
        try:
            return chat.send_message(parts)
        except Exception as e:
            msg = str(e)
            print(f"API Error (try {attempt + 1}): {msg[:120]}")
            if "503" in msg or "429" in msg or "UNAVAILABLE" in msg:
                time.sleep(6 * (attempt + 1))   # 6, 12, 18, 24, 30 sec
            else:
                break
    return None


# ================= 7. MAIN LOOP =================
print("=" * 60)
speak_and_print("Guts online hai Boss! Bol, kya scene hai?")
print("=" * 60)
_prev_files = scan_files()
last_obs = last_spoke = time.time()

while not QUIT:
    try:
        if mic:
            wav = listen_audio()
            if wav:
                r = ask([types.Part.from_bytes(data=wav, mime_type="audio/wav"),
                         "Boss said this (audio). Understand words + tone and reply."])
                if r and r.text:
                    speak_and_print(r.text)
                last_spoke = time.time()
                continue
        else:
            txt = input("\nYou (Boss): ").strip()
            if txt:
                r = ask(txt)
                if r and r.text:
                    speak_and_print(r.text)
            continue

        # idle -> proactive observation
        now = time.time()
        if now - last_obs >= OBS_INTERVAL:
            last_obs = now
            summary, notable = observe()
            idle_checkin = now - last_spoke >= CHECKIN_EVERY
            if (notable and now - last_spoke >= SPEAK_COOLDOWN) or idle_checkin:
                tag = "[AUTO-OBSERVATION]" if notable else "[IDLE CHECK-IN: Boss has been quiet]"
                r = ask(f"{tag} {summary}")
                if r and r.text and r.text.strip().upper() != "SKIP":
                    speak_and_print(r.text)
                last_spoke = time.time()

    except KeyboardInterrupt:
        print("\n[Shutting down Guts...]")
        break
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(1)

speak_and_print("Alvida Boss! Aura high rakhna!")
