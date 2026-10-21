"""game_buddy.py - Guts plays Tekken 8 WITH you (PART 1, version 2: friend commentary).

How it works (so you know what he can and cannot do):
  1. It captures ONLY the Tekken 8 window.
  2. Every ~3 seconds a SEPARATE Gemini call reads the screen: screen type (fight / menu / loading / results),
     both character NAMES from the name tags, both health bars, Heat, round wins. (Your second key, GEMINI_WORK_KEY.)
  3. Python tracks the match: big hits, comebacks, low health, Heat on, round won, match end.
  4. Only then Guts gets a short [GAME EVENT] and says ONE friendly line about it.
  Menus and loading screens: Guts is silent. While the game buddy is on, his other auto-talk (idle chat, PC
  observations, visitor roasts) is switched off.

Limits: one picture every few seconds cannot see single moves (a Tekken move lasts a fraction of a second).
He comments on moments: big damage, comebacks, Heat, rounds. Health numbers are read from the picture (about +-8).

Needs:  python -m pip install pillow python-dotenv
"""
import io
import os
import re
import sys
import json
import time
import asyncio
import ctypes
import difflib
from ctypes import wintypes
from pathlib import Path

from tekken8_knowledge import ROSTER, game_prompt

BASE = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except Exception:
    pass

STEAM_APP_ID = "1778820"                 # TEKKEN 8 on Steam
WINDOW_WORD = "tekken 8"                 # part of the game window title
BOSS_SIDE = "left"                       # "left" = Player 1 side. Say boss_side right if you play on the right

FRAME_EVERY = 1.0                        # pictures sent to Guts (only during a fight)
ANALYZE_FIGHT = 3.0                      # seconds between screen readings in a fight
ANALYZE_OTHER = 8.0                      # ... in menus / loading
MIN_GAP = 7.0                            # at least this many seconds between two comments
FILLER_EVERY = 35.0                      # a short status comment when nothing big happens
BIG_HIT = 15                             # health points lost between two readings = big hit
LOW_HEALTH = 25
LOST_WINDOW_STOP = 90
MAX_MINUTES = 90
FRAME_WIDTH = 960
JPEG_QUALITY = 60
DEFAULT_MODELS = ["gemini-flash-lite-latest", "gemini-3-flash-preview", "gemini-flash-latest"]

GAME_PROMPT = game_prompt()
GAME = {"on": False, "since": 0.0, "last_capture": 0.0, "last_analyze": 0.0, "last_comment": 0.0, "lost_since": 0.0,
        "frames": 0, "readings": 0, "black": 0, "note": "off", "reset": False, "model": "", "errors": 0,
        "interval": ANALYZE_OTHER}

READ_PROMPT = (
    "You are reading a TEKKEN 8 screenshot. Image 1 is the TOP part of the screen in high detail, image 2 is the "
    "whole screen. HUD facts: each side has a YELLOW health bar at the top with a BLUE Heat bar just below it, "
    "round-win markers are near the middle and the fighters' names are written near the bars. LEFT is player 1, "
    "RIGHT is player 2.\n"
    "Roster for spelling: " + ", ".join(ROSTER) + ".\n"
    "Answer ONLY with JSON, no other text:\n"
    '{"screen":"fight|character_select|menu|loading|results|replay|other",'
    '"left_name":null,"right_name":null,"left_health":null,"right_health":null,'
    '"left_heat":false,"right_heat":false,"left_rounds":null,"right_rounds":null,"note":""}\n'
    "Rules: read names ONLY from the name tags (null if unreadable, never guess from looks). health = percent of the "
    "solid yellow/orange/red part of the bar that is still filled (0-100), ignore the white or grey recoverable part; "
    "null if there is no health bar. heat = true only if that side shows the Heat state (blue glow, Heat bar "
    "draining). rounds = number of rounds that side has won, null if not visible. screen is fight only when both "
    "health bars are visible during live action. note = ONE short factual sentence of what is visible."
)


# ================= window + pictures =================
def _u():
    return ctypes.windll.user32


def _find_window():
    """(left, top, right, bottom) of the Tekken 8 client area, or None."""
    u = _u()
    try:
        u.SetProcessDPIAware()
    except Exception:
        pass
    found = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if hwnd and u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd):
            n = u.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(hwnd, buf, n + 1)
                if WINDOW_WORD in buf.value.lower():
                    found.append(int(hwnd))
        return True

    u.EnumWindows(enum_proc(cb), 0)
    if not found:
        return None
    hwnd = found[0]
    rc = wintypes.RECT()
    u.GetClientRect(hwnd, ctypes.byref(rc))
    pt = wintypes.POINT(0, 0)
    u.ClientToScreen(hwnd, ctypes.byref(pt))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w < 200 or h < 200:
        return None
    return (pt.x, pt.y, pt.x + w, pt.y + h)


def _grab_bbox(bbox):
    from PIL import ImageGrab
    return ImageGrab.grab(bbox=bbox, all_screens=True)


def _jpeg(img, width: int, quality: int = JPEG_QUALITY) -> bytes:
    w, h = img.size
    if w != width:
        img = img.resize((width, max(1, int(h * width / w))))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def grab_images():
    """({'live': jpeg, 'top': jpeg, 'small': jpeg}, 'ok') or (None, reason)"""
    bbox = _find_window()
    if not bbox:
        return None, "window not found"
    try:
        from PIL import ImageStat
        img = _grab_bbox(bbox).convert("RGB")
        if sum(ImageStat.Stat(img).mean) / 3 < 3:
            return None, "black"
        w, h = img.size
        top = img.crop((0, 0, w, max(1, int(h * 0.25))))
        return {"live": _jpeg(img, FRAME_WIDTH), "top": _jpeg(top, 1280, 70), "small": _jpeg(img, 640)}, "ok"
    except Exception as e:
        return None, f"capture failed: {e}"


# ================= reading the screen (separate Gemini call) =================
_GOOD = {"model": None}


class Busy(Exception):
    """429 / 503: wait longer before the next reading."""


def _models():
    env = os.getenv("GUTS_VISION_MODELS", "").strip()
    return [m.strip() for m in env.split(",") if m.strip()] if env else DEFAULT_MODELS


def _parse_json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def analyze(imgs: dict):
    """One Gemini call that reads the screen. Returns a dict (see READ_PROMPT)."""
    from google import genai
    from google.genai import types
    key = os.getenv("GEMINI_WORK_KEY") or os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("No Gemini key in .env")
    client = genai.Client(api_key=key)
    parts = [types.Part.from_bytes(data=imgs["top"], mime_type="image/jpeg"),
             types.Part.from_bytes(data=imgs["small"], mime_type="image/jpeg"), READ_PROMPT]
    cfg = types.GenerateContentConfig(response_mime_type="application/json", temperature=0)
    order = ([_GOOD["model"]] if _GOOD["model"] else []) + [m for m in _models() if m != _GOOD["model"]]
    last = None
    for model in order:
        try:
            r = client.models.generate_content(model=model, contents=parts, config=cfg)
            data = _parse_json(r.text)
            _GOOD["model"], GAME["model"] = model, model
            return data
        except Exception as e:
            msg = str(e)
            last = e
            if "429" in msg or "503" in msg or "RESOURCE_EXHAUSTED" in msg or "UNAVAILABLE" in msg:
                if model == order[-1]:
                    raise Busy(msg[:120])
                continue
            if "404" in msg or "NOT_FOUND" in msg or "not found" in msg.lower():
                continue                                    # this model name does not exist for this key
            raise
    raise RuntimeError(f"no vision model worked ({str(last)[:120]}). Set GUTS_VISION_MODELS in .env")


# ================= names, numbers, match tracking =================
_NORM = {re.sub(r"[^a-z0-9]", "", r.lower()): r for r in ROSTER}


def match_name(raw):
    if not raw or not isinstance(raw, str):
        return None
    c = re.sub(r"[^a-z0-9]", "", raw.lower())
    if c in _NORM:
        return _NORM[c]
    if len(c) <= 4:
        return None                                         # short names (Lee, Law, Leo, Bob...) must match exactly
    close = difflib.get_close_matches(c, [k for k in _NORM if len(k) > 4], n=1, cutoff=0.85)
    return _NORM[close[0]] if close else None


def _num(v):
    try:
        return max(0, min(100, int(round(float(v)))))
    except Exception:
        return None


def _int(v):
    try:
        return max(0, min(5, int(v)))
    except Exception:
        return None


PRIORITY = {"match_end": 0, "round_won": 1, "heat_on": 2, "big_hit": 3, "low_health": 4, "match_start": 5, "status": 9}


class Tracker:
    """Turns a stream of screen readings into a few meaningful events."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.in_fight = False
        self.fight_reads = 0
        self.names = {"boss": None, "opp": None}
        self.health = {"boss": None, "opp": None}
        self.heat = {"boss": False, "opp": False}
        self.rounds = {"boss": 0, "opp": 0}
        self.low_warned = {"boss": False, "opp": False}
        self.started = False
        self.not_fight = 0

    def _side(self, left, right):
        return (left, right) if BOSS_SIDE == "left" else (right, left)

    def label(self, who):
        nm = self.names[who]
        return ("Boss" if who == "boss" else "Opponent") + (f" ({nm})" if nm else "")

    def summary(self):
        h = lambda w: f"{self.health[w]}%" if self.health[w] is not None else "?"
        return (f"{self.label('boss')} health {h('boss')}, heat {'ON' if self.heat['boss'] else 'off'} | "
                f"{self.label('opp')} health {h('opp')}, heat {'ON' if self.heat['opp'] else 'off'} | "
                f"rounds won: Boss {self.rounds['boss']} - Opponent {self.rounds['opp']}")

    def update(self, r: dict, now: float):
        ev = []
        screen = str(r.get("screen", "other")).lower()
        L, R = r.get("left_name"), r.get("right_name")
        bn, on = self._side(match_name(L), match_name(R))
        for who, nm in (("boss", bn), ("opp", on)):
            if nm:
                self.names[who] = nm
        if screen != "fight":
            self.fight_reads = 0
            self.not_fight += 1
            if screen == "results" and self.started:
                ev.append(("match_end", f"The match is over. {self.summary()}"))
                self.started = False
                self.in_fight = False
            elif self.not_fight >= 4:
                self.in_fight = False
                if self.not_fight >= 12:
                    self.reset()                           # long gap: forget the old match
            return ev
        self.not_fight = 0
        self.fight_reads += 1
        self.in_fight = True
        bh, oh = self._side(_num(r.get("left_health")), _num(r.get("right_health")))
        bheat, oheat = self._side(bool(r.get("left_heat")), bool(r.get("right_heat")))
        bro, oro = self._side(_int(r.get("left_rounds")), _int(r.get("right_rounds")))
        if not self.started and self.fight_reads >= 2:
            self.started = True
            ev.append(("match_start", f"A match is starting: {self.label('boss')} versus {self.label('opp')}."))
        for who, cur in (("boss", bh), ("opp", oh)):
            prev = self.health[who]
            if cur is None:
                continue
            if prev is not None and cur > prev + 35:       # health refilled = new round
                self.low_warned[who] = False
                self.heat[who] = False
            elif prev is not None and prev - cur >= BIG_HIT:
                who_hit = "Boss took" if who == "boss" else "Opponent took"
                ev.append(("big_hit", f"{who_hit} a big hit: {self.label(who)} health {prev}% to {cur}%."))
            if 3 < cur <= LOW_HEALTH and not self.low_warned[who] and prev is not None:
                self.low_warned[who] = True
                ev.append(("low_health", f"{self.label(who)} is on very low health ({cur}%)."))
            self.health[who] = cur
        for who, cur in (("boss", bheat), ("opp", oheat)):
            if cur and not self.heat[who]:
                ev.append(("heat_on", f"{self.label(who)} just activated Heat."))
            self.heat[who] = cur
        for who, cur in (("boss", bro), ("opp", oro)):
            if cur is not None and cur > self.rounds[who]:
                self.rounds[who] = cur
                ev.append(("round_won", f"{self.label(who)} won the round. {self.summary()}"))
        return ev


# ================= tools for Guts =================
TRACKER = Tracker()


def open_tekken8() -> str:
    """Start Tekken 8 through Steam."""
    try:
        os.startfile(f"steam://rungameid/{STEAM_APP_ID}")
        return "Launching Tekken 8 through Steam. Say nothing more than one short word."
    except Exception as e:
        return f"Could not start it through Steam ({e}). Try: open_item with the name tekken."


def game_buddy(mode: str = "status", boss_side: str = "") -> str:
    """on = friend commentary for Tekken 8, off = stop, status = names, health and rounds right now."""
    global BOSS_SIDE
    mode = (mode or "status").lower().strip()
    if boss_side and boss_side.lower().strip() in ("left", "right"):
        BOSS_SIDE = boss_side.lower().strip()
    if mode in ("on", "start", "chalu", "yes"):
        try:
            import PIL  # noqa: F401
        except Exception:
            return "Pillow is missing. Tell Boss to run: python -m pip install pillow"
        GAME.update(on=True, since=time.time(), last_capture=0.0, last_analyze=0.0, last_comment=time.time(),
                    lost_since=0.0, frames=0, readings=0, black=0, errors=0, note="starting", reset=True,
                    interval=ANALYZE_OTHER)
        extra = "" if _find_window() else " The Tekken 8 window is not open yet. Tell Boss: Borderless or Windowed mode."
        return f"Game buddy is ON (Boss is on the {BOSS_SIDE} side). Say at most one word, then stay silent.{extra}"
    if mode in ("off", "stop", "band"):
        GAME.update(on=False, note="off")
        return "Game buddy is OFF. Say at most one word."
    if not GAME["on"]:
        return "Game buddy is off."
    if not TRACKER.in_fight:
        return (f"Game buddy is ON but no fight is on screen right now ({GAME['note']}). Names last read: "
                f"Boss {TRACKER.names['boss'] or '?'}, Opponent {TRACKER.names['opp'] or '?'}.")
    return f"Right now: {TRACKER.summary()}."


# ================= the background task (runs inside the live session) =================
def _stop(reason: str):
    GAME.update(on=False, note=reason)
    print(f"[Game] stopped: {reason}")


async def game_stream(session, STATE):
    from google.genai import types
    queue = []                                        # (priority, created, kind, text)
    while True:
        await asyncio.sleep(0.4 if GAME["on"] else 1.5)
        STATE["game_quiet"] = bool(GAME["on"])        # switches the other auto-talk off while playing
        if not GAME["on"]:
            continue
        if GAME["reset"]:
            TRACKER.reset()
            queue.clear()
            GAME["reset"] = False
        if STATE.get("asleep"):
            continue
        now = time.time()
        if now - GAME["since"] > MAX_MINUTES * 60:
            _stop(f"auto stop after {MAX_MINUTES} minutes")
            continue

        # ---- look at the game ----
        gap = FRAME_EVERY if TRACKER.in_fight else GAME["interval"]
        if now - GAME["last_capture"] >= gap:
            GAME["last_capture"] = now
            imgs, why = await asyncio.to_thread(grab_images)
            if imgs is None:
                if why == "black":
                    GAME["black"] += 1
                    GAME["note"] = "the game picture is black"
                    if GAME["black"] == 3:
                        print("[Game] The Tekken picture is black. Set the game to Borderless or Windowed mode.")
                else:
                    GAME["note"] = why
                    GAME["lost_since"] = GAME["lost_since"] or now
                    if now - GAME["lost_since"] > LOST_WINDOW_STOP:
                        _stop("the Tekken 8 window was gone for too long")
                continue
            GAME["lost_since"], GAME["black"] = 0.0, 0
            if TRACKER.in_fight:                      # pictures to Guts only while a fight is on
                try:
                    blob = types.Blob(data=imgs["live"], mime_type="image/jpeg")
                    try:
                        await session.send_realtime_input(video=blob)
                    except TypeError:
                        await session.send_realtime_input(media=blob)
                    GAME["frames"] += 1
                except Exception as e:
                    print(f"(game picture not sent: {e})")
            if now - GAME["last_analyze"] >= GAME["interval"]:
                GAME["last_analyze"] = now
                try:
                    reading = await asyncio.to_thread(analyze, imgs)
                    GAME["readings"] += 1
                    GAME["errors"] = 0
                    GAME["note"] = str(reading.get("note") or reading.get("screen") or "watching")[:60]
                    for kind, text in TRACKER.update(reading, now):
                        queue.append((PRIORITY.get(kind, 9), now, kind, text))
                    GAME["interval"] = ANALYZE_FIGHT if TRACKER.in_fight else ANALYZE_OTHER
                except Busy as e:
                    GAME["errors"] += 1
                    GAME["interval"] = min(30.0, GAME["interval"] * 2)
                    print(f"[Game] reading is rate limited, slowing down ({e})")
                except Exception as e:
                    GAME["errors"] += 1
                    GAME["note"] = "reading failed"
                    print(f"[Game] could not read the screen: {str(e)[:150]}")
                    if GAME["errors"] >= 6:
                        _stop("the screen reading failed 6 times in a row")

        # ---- talk (only about the game, only in a fight or at the end of a match) ----
        queue[:] = [q for q in queue if now - q[1] < (20 if q[2] in ("match_end", "round_won") else 7)]
        if not queue and TRACKER.in_fight and TRACKER.started and now - GAME["last_comment"] >= FILLER_EVERY:
            queue.append((PRIORITY["status"], now, "status", f"Nothing big happened. {TRACKER.summary()}."))
        if (queue and now - GAME["last_comment"] >= MIN_GAP and not STATE.get("pending")
                and now - STATE.get("last_activity", 0) >= 2.5):
            queue.sort(key=lambda q: (q[0], q[1]))
            _, _, kind, text = queue.pop(0)
            queue.clear()
            msg = (f"[GAME EVENT] {text}\nMatch state: {TRACKER.summary()}\n"
                   "Say ONE short friendly Hinglish line (max 12 words) about this, like a friend commentating live. "
                   "Use only these facts. Do not read this tag aloud.")
            try:
                await session.send_realtime_input(text=msg)
                GAME["last_comment"] = STATE["last_activity"] = now
                print(f"[Game] {kind}: {text[:90]}")
            except Exception as e:
                print(f"(game event not sent: {e})")
