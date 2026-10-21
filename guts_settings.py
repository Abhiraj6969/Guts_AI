"""guts_settings.py - everything that belongs to ONE person (one install = one Boss).

Stored next to the program (the install is per Windows user, so the folder is writable and private):
  guts_settings.json   name, language, personality, browser, camera, switches
  .env                 the person's own Gemini key(s)
  contacts.json        the person's WhatsApp contacts
  boss_face.npy        the person's face (made by face_guard.py enroll)
Nothing personal is ever put in the installer.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

APP_DIR = Path(os.environ.get("GUTS_APP_DIR") or Path(__file__).resolve().parent)
SETTINGS_FILE = APP_DIR / "guts_settings.json"
ENV_FILE = APP_DIR / ".env"
CONTACTS_FILE = APP_DIR / "contacts.json"

DEFAULTS = {
    "boss_name": "Boss",          # what Guts calls the user
    "guts_name": "Guts",          # the name of the assistant (the user can change it)
    "show_avatar": True,          # the face on the screen with the OFF button
    "avatar_x": -1,               # -1 = bottom right corner
    "avatar_y": -1,
    "language": "hinglish",
    "persona": "giga_chad",
    "browser": "auto",            # auto = keep Guts's normal choice (Brave if installed, else the default browser)
    "face_lock": True,
    "proactive": True,
    "camera_index": 0,
    "first_run_done": False,
    "consent": False,
}

LANGUAGES = {
    "hinglish": "natural Hinglish (Hindi and English mixed, written in Roman letters)",
    "english": "simple, clear English",
    "hindi": "Hindi written in Roman letters",
}
PERSONAS = {
    "giga_chad": "Giga Chad best friend (confident, witty, memes)",
    "calm": "Calm friendly assistant (polite, no slang, no roasting)",
    "pro": "Professional assistant (short, direct, no jokes)",
}
PERSONA_RULES = {
    "giga_chad": "",
    "calm": ("Ignore the Giga Chad style. Speak as a calm, warm, polite assistant: no slang, no memes, no "
             "flexing, and never roast or tease anyone, including visitors."),
    "pro": ("Ignore the Giga Chad style. Speak as a concise professional assistant: short, direct, no jokes, no "
            "slang, and never roast or tease anyone, including visitors."),
}

BROWSERS = {
    "brave": [r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
              r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
              r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"],
    "chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
               r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
               r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"],
    "edge": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
    "firefox": [r"C:\Program Files\Mozilla Firefox\firefox.exe",
                r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"],
}


# ---------------- settings file ----------------
def load() -> dict:
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return s


def save(s: dict):
    out = load()                 # keep what is already stored, change only what is given
    out.update(s)
    SETTINGS_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


def get(key: str, default=None):
    return load().get(key, DEFAULTS.get(key, default))


def needs_setup() -> bool:
    return not load().get("first_run_done") or not has_key()


# ---------------- the Guts prompt addon ----------------
def prompt_addon() -> str:
    """Extra instructions appended to Guts's system prompt, so each person gets their own Guts."""
    s = load()
    parts = []
    gname = (s.get("guts_name") or "Guts").strip()
    if gname.lower() != "guts":
        parts.append(f"Your name is {gname}, not Guts. Always call yourself {gname}, answer when the owner calls you "
                     f"{gname}, and never say the name Guts about yourself.")
    name = (s.get("boss_name") or "").strip()
    if name and name.lower() != "boss":
        parts.append(f"The owner's real name is {name}. When you speak to the owner, call them {name} instead of "
                     "Boss (Boss is only your internal word for the owner).")
    parts.append("Speak in " + LANGUAGES.get(s.get("language"), LANGUAGES["hinglish"]) + ".")
    rule = PERSONA_RULES.get(s.get("persona"), "")
    if rule:
        parts.append(rule)
    return " " + " ".join(parts) + " "


def set_assistant_name(name: str) -> str:
    """Change the name of the assistant. Used by the voice tool, the face's menu and the setup wizard."""
    n = re.sub(r"[^\w \-]", "", name or "").strip()[:20]
    if len(n) < 2:
        return "The name must have 2 to 20 letters. Nothing was changed."
    save({"guts_name": n})
    return (f"Done. From now on my name is {n}. The face on the screen changed at once, and my voice uses the new "
            "name from the next start. Say that in one short sentence.")


# ---------------- browser ----------------
def detect_browsers() -> dict:
    found = {}
    for name, paths in BROWSERS.items():
        for p in paths:
            p = os.path.expandvars(p)
            if os.path.exists(p):
                found[name] = p
                break
    return found


def browser_path():
    """Path of the browser the person chose, or None (= keep Guts's normal behaviour)."""
    choice = str(load().get("browser", "auto")).lower()
    if choice == "auto":
        return None
    return detect_browsers().get(choice)


# ---------------- .env (keys) ----------------
def read_env() -> dict:
    out = {}
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
            if m:
                out[m.group(1)] = m.group(2).strip().strip("\"'")
    except Exception:
        pass
    return out


def has_key() -> bool:
    return bool(read_env().get("GEMINI_API_KEY"))


def write_env(updates: dict):
    """Adds or changes lines in .env and keeps every other line as it is."""
    clean = {k: str(v).strip().strip("\"'") for k, v in updates.items()}
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    out, seen = [], set()
    for line in lines:
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and m.group(1) in clean:
            out.append(f"{m.group(1)}={clean[m.group(1)]}")
            seen.add(m.group(1))
        else:
            out.append(line)
    for k, v in clean.items():
        if k not in seen:
            out.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")


def validate_gemini_key(key: str, base: str = "https://generativelanguage.googleapis.com"):
    """(True, msg) key works | (False, msg) key is wrong | (None, msg) could not check (no internet)."""
    key = (key or "").strip().strip("\"'")
    if len(key) < 20 or " " in key:
        return False, "That does not look like a Gemini key (it is a long text without spaces)."
    try:
        req = urllib.request.Request(f"{base}/v1beta/models?pageSize=1&key={key}")
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status == 200:
                return True, "The key works."
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            return False, "Google says this key is not valid. Copy it again from Google AI Studio."
        if e.code == 429:
            return True, "The key is valid, but its free limit is used up right now."
        return None, f"Google answered with error {e.code}. Try again in a minute."
    except Exception as e:
        return None, f"Could not reach Google ({str(e)[:60]}). Check the internet."
    return None, "Could not check the key."


# ---------------- contacts ----------------
def normalize_phone(number: str, default_cc: str = "91"):
    """Digits only with country code, or None if it cannot be a phone number."""
    raw = (number or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if not raw.startswith("+"):
        digits = digits.lstrip("0")
        if len(digits) == 10:
            digits = re.sub(r"\D", "", default_cc) + digits
    return digits if 8 <= len(digits) <= 15 else None


def save_contacts(rows, default_cc: str = "91"):
    """rows = [(name, number), ...]. Returns (saved_count, problems)."""
    data, problems = {}, []
    for name, number in rows:
        name = (name or "").strip().lower()
        if not name and not (number or "").strip():
            continue
        phone = normalize_phone(number, default_cc)
        if not name or not phone:
            problems.append(f"{name or '(no name)'}: number not valid")
            continue
        data[name] = phone
    CONTACTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(data), problems


# ---------------- start with Windows ----------------
def set_autostart(enabled: bool, exe_path: str = "") -> bool:
    """Adds or removes Guts from the current user's Windows start-up list."""
    if sys.platform != "win32":
        return False
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                         winreg.KEY_SET_VALUE)
    try:
        if enabled:
            winreg.SetValueEx(key, "GutsAI", 0, winreg.REG_SZ, f'"{exe_path}" --login')
        else:
            try:
                winreg.DeleteValue(key, "GutsAI")
            except FileNotFoundError:
                pass
        return True
    finally:
        winreg.CloseKey(key)
