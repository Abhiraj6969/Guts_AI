"""guts_bridge.py - the link between the running Guts and the face on the screen.

Guts (live_voice) writes what he is doing into avatar_state.json four times a second:
  state: sleeping | speaking | listening | working | game | idle     text: what he is saying (subtitle)
The face (guts_avatar.py, a separate small program) reads that file and animates.
The face can also leave a command in avatar_cmd.json (sleep / wake), which this task reads.
No tkinter in here, so it is safe to import inside the main Guts program.
"""
import asyncio
import json
import os
import time
from pathlib import Path

APP_DIR = Path(os.environ.get("GUTS_APP_DIR") or Path(__file__).resolve().parent)
STATE_FILE = APP_DIR / "avatar_state.json"
CMD_FILE = APP_DIR / "avatar_cmd.json"


def current_state(STATE: dict, now: float) -> str:
    if STATE.get("asleep"):
        return "sleeping"
    if now - STATE.get("last_audio_out", 0) < 0.9:
        return "speaking"
    if STATE.get("pending") or now - STATE.get("last_tool", 0) < 2.5:
        return "working"
    if now - STATE.get("last_user_speech", 0) < 1.5:
        return "listening"
    if STATE.get("game_quiet"):
        return "game"
    return "idle"


def subtitle(STATE: dict, now: float) -> str:
    if now - STATE.get("subtitle_t", 0) > 7:
        return ""
    return STATE.get("subtitle", "")


def _write(data: dict):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def apply_command(STATE: dict):
    try:
        if not CMD_FILE.exists():
            return
        cmd = json.loads(CMD_FILE.read_text(encoding="utf-8")).get("cmd")
        CMD_FILE.unlink()
    except Exception:
        return
    if cmd == "sleep":
        STATE["asleep"] = True
        STATE["last_activity"] = time.time()
    elif cmd == "wake":
        STATE["asleep"] = False
        STATE["last_activity"] = time.time()
        STATE["idle_count"] = 0


async def avatar_bridge(STATE: dict):
    last, last_write = None, 0.0
    while True:
        await asyncio.sleep(0.25)
        now = time.time()
        try:
            apply_command(STATE)
            data = {"state": current_state(STATE, now), "text": subtitle(STATE, now)}
            if data != last or now - last_write > 1.0:
                data["t"] = now
                _write(data)
                last, last_write = {k: v for k, v in data.items() if k != "t"}, now
        except Exception as e:
            print(f"(avatar bridge: {e})")
            await asyncio.sleep(2)
