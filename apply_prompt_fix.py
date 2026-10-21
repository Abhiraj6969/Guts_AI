"""apply_prompt_fix.py - repairs a sentence that was cut in half inside Guts's instructions.

In the JARVIS HANDS part of the system prompt, the text said
   "... set_brightness for brightness 0-100, take_sc (a file is closed by its name, ..."
so two things were lost: the tools after take_sc (screenshot, power, media keys, hotkeys, typing)
and the instruction "to close an app, call close_item". Without them Guts often does not call those tools.

It reads your NEWEST live_voice_N.py and creates the next number. Your file is NOT changed.

Run (in the Guts_AI folder):
  python apply_prompt_fix.py
Optional:  python apply_prompt_fix.py live_voice_21.py live_voice_22.py
"""
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent


def newest():
    nums = []
    for p in BASE.glob("live_voice_*.py"):
        m = re.fullmatch(r"live_voice_(\d+)\.py", p.name)
        if m:
            nums.append(int(m.group(1)))
    return max(nums) if nums else None


if len(sys.argv) > 2:
    SRC, DST = Path(sys.argv[1]), Path(sys.argv[2])
else:
    n = newest()
    SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else (BASE / f"live_voice_{n}.py" if n else BASE / "live_voice_3.py")
    m = re.fullmatch(r"live_voice_(\d+)\.py", SRC.name)
    DST = BASE / (f"live_voice_{int(m.group(1)) + 1}.py" if m else "live_voice_new.py")

BROKEN = "take_sc (a file is closed by its name, because its window shows the name)."
FIXED = ("take_screenshot for a screenshot, system_power for lock, sleep, shutdown or restart, media_control for "
         "play, pause, next and previous, press_hotkey for keyboard shortcuts like win+d, type_text to type text. "
         "To close an app, window, file or folder call close_item (a file is closed by its name, because its "
         "window shows the name).")


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run this from the Guts_AI folder.")
        return
    text = SRC.read_text(encoding="utf-8")
    n = text.count(BROKEN)
    if n == 0:
        print("The damaged sentence is not in this file. Nothing to do.")
        return
    if n != 1:
        print(f"STOPPED. Found {n} places, expected 1. Nothing was written.")
        return
    text = text.replace(BROKEN, FIXED)
    compile(text, str(DST), "exec")          # syntax check before saving
    DST.write_text(text, encoding="utf-8")
    print(f"Done: {DST.name} created from {SRC.name}. {SRC.name} is untouched.")
    print(f"Next: python {DST.name}")


if __name__ == "__main__":
    main()
