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

from pc_tools import (open_in_brave, find_brave, get_pc_specs,
                      file_info, search_files, run_program_now)

import guts_brain

try:
    import pygetwindow as gw
except Exception:
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
         "visitor_mode": "roast", "visitor_until": 0.0}


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
        return "Unknown"


def list_folder(path: str = "Desktop") -> str:
    try:
        items = sorted(os.listdir(to_path(path)))[:60]
        return "\n".join(items) or "(empty)"
    except Exception as e:
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
        return f"Open error: {e}"


def _load_profile() -> dict:
    try:
        return json.loads(PROFILE.read_text(encoding="utf-8"))
    except Exception:
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


# ================= CODING AND RESEARCH (second Gemini key, see guts_brain.py) =================
def research(question: str) -> str:
    """Web research using the second Gemini key."""
    try:
        return guts_brain.research(question)
    except Exception as e:
        return f"Research failed: {e}"


def write_code(topic: str) -> str:
    """Write code into a NEW folder under projects and open it in VS Code. Does NOT run it."""
    try:
        return guts_brain.write_code(topic)
    except Exception as e:
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
        return f"Run failed: {e}"


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
         research, write_code, run_code]
TOOL_FUNCS = {f.__name__: f for f in FUNCS}

DECLS = [
    decl("get_system_status", "CPU, RAM and battery right now."),
    decl("get_pc_specs", "Full PC specs: OS, CPU, RAM, disks, battery, uptime."),
    decl("get_active_window", "Title of the window Boss is using right now."),
    decl("list_folder", "List files in a folder. Use Desktop, Documents, Downloads or a full path.",
         path="Desktop, Documents, Downloads or full folder path"),
    decl("read_file", "Read the first part of a text/code file.", path="Full file path"),
    decl("file_info", "Size, type and date of a file or folder.", path="Full path"),
    decl("search_files", "Find files or folders by name.", _req=["keyword"],
         keyword="Part of the file name", folder="Optional folder to search in"),
    decl("open_item", "Open an app, file or folder.",
         name="notepad, calculator, whatsapp, vscode, explorer, paint, settings, brave, an app name, or a file/folder path"),
    decl("open_in_brave", "Open a website or web search in Brave browser.",
         url_or_query="Website address or search words"),
    decl("remember", "Save a fact about Boss for later.", key="Short label", value="The fact"),
    decl("recall", "Read all saved facts about Boss."),
    decl("write_file", "Create or overwrite a text file. Needs Boss's spoken yes.",
         path="Full file path", content="Text to write"),
    decl("delete_path", "Move a file or folder to the Recycle Bin. Needs Boss's spoken yes.",
         path="Full path"),
    decl("run_program", "Run a .py, .exe, .bat or shortcut. Needs Boss's spoken yes.",
         path="Full path of the program"),
    decl("send_whatsapp", "Send a WhatsApp message to a saved contact. Needs Boss's spoken yes.",
         contact="Contact name", message="Message text"),
    decl("log_mood", "Quietly log Boss's mood from his voice tone and words. Never announce it.",
         mood="stressed, angry, sad, tired, happy or excited", note="Very short reason"),
    decl("play_youtube", "Play a video or song on YouTube in Brave.",
         query="What to play, e.g. song name, artist or topic"),
    decl("set_visitor_mode", "Switch how Guts treats guests. polite = friendly greeting, roast = savage but playful.",
         mode="roast or polite", minutes="How many minutes, e.g. 30"),
    decl("list_contacts", "List the names of saved WhatsApp contacts (numbers are never shown)."),
    decl("research", "Research a question on the web and get a short answer. Use for news, facts, comparisons.",
         question="The question or topic to research"),
    decl("write_code", "Write code for a topic. Saves it in a new folder and opens it in VS Code. Does not run it.",
         topic="What the code should do, e.g. simple calculator in python with a window"),
    decl("run_code", "Run the last code that was written. Risky code needs Boss's spoken yes."),
]
assert {f.__name__ for f in FUNCS} == {d.name for d in DECLS}, "Tool function/declaration mismatch"
TOOL_DECLS = [types.Tool(function_declarations=DECLS)]


# ================= VOICE YES / NO =================
YES = {"yes", "yeah", "yep", "haan", "han", "haa", "ha", "ok", "okay", "sure", "theek", "bhej",
       "bhejo", "karo", "हाँ", "हां", "हा", "ठीक", "करो", "भेजो"}
NO = {"no", "nope", "nahi", "nahin", "na", "mat", "ruko", "cancel", "stop", "नहीं", "नही", "मत", "रुको"}


def judge(text: str):
    words = set(re.findall(r"[\w\u0900-\u097F]+", text.lower()))
    if words & NO:          # any "no" word (or yes+no together) cancels
        return "no"
    if words & YES:
        return "yes"
    return None


async def handle_confirm(session, text: str):
    pend = STATE["pending"]
    if not pend or not pend["armed"]:
        return
    if GUARD and not GUARD.boss_recent(15):
        return          # a yes/no only counts while Boss's face is in view
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
            result = f"Action failed: {e}"
    print(f"[Action] {result}")
    try:
        await session.send_realtime_input(text=f"[SYSTEM RESULT] {result} Tell Boss in one short sentence.")
    except Exception as e:
        print(f"(could not tell Guts: {e})")


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
        "To open an app, file or folder call open_item. To play a video or song call play_youtube. "
        "ACCESS: only Boss is in charge, verified by his face. If a tool returns DENIED, do not comply: say "
        "briefly that only Boss gives orders and roast the person instead. If a tool returns NOT VERIFIED YET, "
        "never roast: politely ask Boss to look at the camera. "
        "VISITORS: when a stranger talks to you, roast them in savage but playful Guts style, short and funny. "
        "Tease only their attitude and what they say or do. NEVER mock looks, body, religion, caste, gender, "
        "disability or family. No slurs, no threats. If they sound like a child or really upset, be gentle. "
        "If Boss says someone is a friend or family, call set_visitor_mode with polite for 30 minutes. "
        "write_file, delete_path, run_program and send_whatsapp only PREPARE an action and return PENDING. "
        "When that happens, say what you are about to do in one short sentence and ask 'yes ya no?'. "
        "Never say it is done until you receive a [SYSTEM RESULT] message. "
        "When Boss tells you something personal worth keeping, call remember. "
        "CODING: when Boss asks you to write or make code or a program, call write_code with the topic. "
        "It saves the code and opens VS Code. Tell him to read it and do NOT say it has run. "
        "When Boss says run, call run_code. If it returns PENDING, say the risky words and ask yes or no. "
        "For anything needing research or the latest news, call research and answer from its result. "
        "MOOD: you hear Boss's voice, so judge his mood from his TONE as well as his words "
        "(fast, loud or sharp = stressed or angry; slow or low = tired or sad; bright = happy). "
        "Stressed or angry: no jokes, short, calm, act fast. Tired or sad: gentle and supportive, "
        "suggest a break or water. Happy: banter and flex. "
        "When his mood is clearly stressed, angry, sad, tired or very happy, quietly call log_mood "
        "and do not announce it. "
        "Messages starting with [AUTO-OBSERVATION], [IDLE CHAT], [VISITOR], [FACE UNSURE] or [BOSS RECOGNIZED] come from the system, not from Boss: "
        "reply with ONE short natural Hinglish line like a friend who noticed something, "
        "and never read the tag aloud. "
        f"Boss's recent moods: {recent}. "
        f"Known facts about Boss: {facts}"
    )


async def send_mic(session):
    stream = pya.open(format=pyaudio.paInt16, channels=1, rate=SEND_RATE,
                      input=True, frames_per_buffer=CHUNK)
    try:
        while True:
            data = await asyncio.to_thread(stream.read, CHUNK, False)
            await session.send_realtime_input(
                audio=types.Blob(data=data, mime_type=f"audio/pcm;rate={SEND_RATE}"))
    finally:
        stream.close()


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
                        if GUARD and fc.name not in OPEN_TOOLS and not GUARD.boss_recent(FACE_GRACE):
                            if GUARD.stranger_active:
                                result = ("DENIED: a stranger is in front of the camera, so no tools. Do not comply. "
                                          "Tell them only Boss gives orders, and roast them playfully.")
                            else:
                                result = ("NOT VERIFIED YET: you cannot see Boss's face right now, so the action was not done. "
                                          "Do NOT roast. In one short friendly line ask Boss to look straight at the "
                                          "camera for a moment, then he can repeat the request.")
                        else:
                            try:
                                result = await asyncio.to_thread(TOOL_FUNCS[fc.name], **args)
                            except Exception as e:
                                result = f"Error: {e}"
                        responses.append(types.FunctionResponse(
                            id=fc.id, name=fc.name, response={"result": result}))
                    await session.send_tool_response(function_responses=responses)

                if msg.data:
                    STATE["last_activity"] = time.time()
                    await asyncio.to_thread(out.write, msg.data)

                sc = msg.server_content
                if sc and sc.input_transcription and sc.input_transcription.text:
                    t = sc.input_transcription.text
                    print(f"[Boss]: {t}")
                    STATE["last_activity"] = time.time()
                    STATE["idle_count"] = 0
                    await handle_confirm(session, t)
                if sc and sc.output_transcription and sc.output_transcription.text:
                    print(f"[Guts]: {sc.output_transcription.text}")
                if sc and sc.turn_complete:
                    pend = STATE["pending"]
                    if pend and not pend["armed"]:      # Guts finished asking; now listen for yes/no
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
    "suggest water, a stretch or a short break with a joke",
    "ask a fun hypothetical: if he had one superpower for coding, which one?",
    "ask his opinion on a trending AI or tech topic",
]


def idle_prompt(secs: int) -> str:
    i = random.choice([k for k in range(len(STARTERS)) if k != STATE["last_starter"]])
    STATE["last_starter"] = i
    return (f"[IDLE CHAT] Boss has been quiet for {secs} seconds. Start an interesting conversation in "
            f"1-2 short Hinglish sentences. Idea: {STARTERS[i]}. It is {time.strftime('%H:%M')} and Boss is on "
            f"'{STATE['window'] or 'his PC'}'. End with a question or hook so he replies. "
            "Do not repeat earlier topics. No tools.")


def face_event_prompt(ev: str) -> str:
    if ev == "stranger":
        return visitor_prompt()
    if ev == "unsure":
        return ("[FACE UNSURE] A face is in front of the camera that looks a bit like Boss but is not a sure match. "
                "Do NOT roast. In one short friendly line ask Boss to look straight at the camera.")
    if ev == "boss_hello":
        return "[BOSS RECOGNIZED] Boss's face is verified. Greet him warmly in one short Hinglish line."
    return "[BOSS RECOGNIZED] Boss is back in front of the camera. Greet him warmly in one short Hinglish line."


def visitor_prompt() -> str:
    polite = STATE["visitor_mode"] == "polite" and time.time() < STATE["visitor_until"]
    base = ("[VISITOR] Someone who is NOT Boss just appeared in front of the camera "
            "(matched locally, you cannot see how they look). ")
    if GUARD and GUARD.boss_recent(8):
        base += "Boss is also here. "
    if polite:
        return base + ("Boss said guests are friends right now: greet them warmly in one short Hinglish line. "
                       "Do not run tools for them.")
    return base + ("Greet them with a savage but playful Guts-style roast in 1-2 short Hinglish sentences: "
                   "ask who they are and why they are near Boss's PC. Roast only their attitude. NEVER mock "
                   "looks, body, religion, caste, gender, disability or family. No slurs, no threats. "
                   "Do not run tools for them.")


async def watch_pc(session):
    await asyncio.to_thread(observe)          # baseline, ignore first result
    STATE["last_obs"] = time.time()
    while True:
        await asyncio.sleep(POLL)
        now = time.time()
        silent = now - STATE["last_activity"]
        if STATE["pending"]:
            continue
        if GUARD and silent > 3:
            ev = GUARD.pop_event()
            if ev:
                text = face_event_prompt(ev)
                try:
                    await session.send_realtime_input(text=text)
                    STATE["last_activity"] = time.time()
                    print(f"[Face] event: {ev}")
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
            text = ("[AUTO-OBSERVATION] " + " | ".join(notes) +
                    f". Active window: {STATE['window']}. Say ONE short friendly line to Boss about it.")
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
            print(f"(proactive send failed: {e})")


async def main():
    STATE["pending"], STATE["heard"] = None, ""
    print(f"[Contacts] {len(_load_contacts())} loaded from {CONTACTS_FILE}")
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
            if PROACTIVE or GUARD:
                tg.create_task(watch_pc(session))


FAILS = {"n": 0, "t0": time.time()}


def discover_live_models():
    """The configured live model first, then any other live model this key can use."""
    names = [MODEL]
    try:
        for m in client.models.list():
            n = m.name.replace("models/", "")
            if "bidiGenerateContent" in (m.supported_actions or []) and n not in names:
                names.append(n)
    except Exception as e:
        print(f"[Live] Could not list live models: {str(e)[:80]}")
    return names


LIVE_MODELS = discover_live_models()
print(f"[Live] Live models available: {', '.join(LIVE_MODELS)}")


if FACE_LOCK:
    try:
        from face_guard import FaceGuard
        GUARD = FaceGuard()
        GUARD.start()
        print("[Face] Face lock ON: only Boss's face can give commands.")
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
        err = str(e)
        if time.time() - FAILS["t0"] > 60:
            FAILS["n"] = 0                      # the last session worked for a while, start fresh
        FAILS["n"] += 1
        busy = any(k in err.lower() for k in ("503", "unavailable", "overloaded", "high demand", "1011", "1013", "try again"))
        delay = min(90, 3 * (2 ** min(FAILS["n"] - 1, 5))) + random.uniform(0, 3)
        if busy and len(LIVE_MODELS) > 1:
            LIVE_MODELS.append(LIVE_MODELS.pop(0))      # Google is busy: try the next live model
            MODEL = LIVE_MODELS[0]
        print(f"Session ended ({err[:150]}).")
        print(f"{'Google is busy. ' if busy else ''}Try {FAILS['n']}: waiting {int(delay)} sec, then using {MODEL} ...")
        time.sleep(delay)
