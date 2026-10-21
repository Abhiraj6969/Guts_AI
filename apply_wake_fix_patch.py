"""apply_wake_fix_patch.py - stops Guts from waking up on ANY speech.

Cause: the wake listener was told "only listen for the word guts", so it forced every
sound to become "guts". Now it listens normally and wakes only when it really hears the
word. It also ignores the first 4 seconds after he falls asleep (his own goodbye voice),
and prints what it hears while he sleeps, so we can tune it.

It reads live_voice_5.py and creates a NEW file live_voice_6.py.
Your live_voice_5.py is NOT changed.

Run (in the Guts_AI folder):
  python apply_wake_fix_patch.py
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "live_voice_5.py"
DST = Path(sys.argv[2]) if len(sys.argv) > 2 else BASE / "live_voice_6.py"

OLD_HEARD = r'''def heard_wake(data: bytes) -> bool:
    rec = WAKE["rec"]
    if rec is None:
        return False
    if rec.AcceptWaveform(data):
        text = json.loads(rec.Result()).get("text", "")
    else:
        text = json.loads(rec.PartialResult()).get("partial", "")
    if "guts" in text.split():
        rec.Reset()
        return True
    return False'''

NEW_HEARD = r'''WAKE_WORDS = {"guts", "gut", "gutts", "gats"}   # spellings the listener may give for "Guts"
WAKE_DEBUG = True                                # prints what he hears while asleep


def heard_wake(data: bytes) -> bool:
    rec = WAKE["rec"]
    if rec is None:
        return False
    if time.time() < WAKE.get("ignore_until", 0):
        WAKE["need_reset"] = True          # still in the quiet time after falling asleep
        return False
    if WAKE.get("need_reset"):
        rec.Reset()
        WAKE["need_reset"] = False
    if rec.AcceptWaveform(data):
        text = json.loads(rec.Result()).get("text", "")
        if text and WAKE_DEBUG:
            print(f"[Wake] heard: {text}")
    else:
        text = json.loads(rec.PartialResult()).get("partial", "")
    if WAKE_WORDS & set(text.split()):
        rec.Reset()
        return True
    return False'''

EDITS = [
    ("listen normally, not only for the word guts",
     '''WAKE["rec"] = KaldiRecognizer(model, SEND_RATE, '["guts", "[unk]"]')''',
     'WAKE["rec"] = KaldiRecognizer(model, SEND_RATE)'),
    ("wake check", OLD_HEARD, NEW_HEARD),
    ("quiet time after falling asleep",
     'STATE["asleep"] = True',
     'STATE["asleep"] = True\n                        WAKE["ignore_until"] = time.time() + 4'),
]


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run this from the Guts_AI folder.")
        return
    text = SRC.read_text(encoding="utf-8")
    if "WAKE_WORDS" in text:
        print("This file already has the fix. Nothing to do.")
        return

    for label, anchor, new in EDITS:
        n = text.count(anchor)
        if n != 1:
            print(f"STOPPED. Could not safely patch '{label}' (found {n} matches, need 1).")
            print("Nothing was written. Send me this message and your live_voice_5.py.")
            return
        text = text.replace(anchor, new)

    compile(text, str(DST), "exec")          # syntax check before saving
    DST.write_text(text, encoding="utf-8")
    print(f"Done: {DST.name} created ({len(EDITS)} changes). {SRC.name} is untouched.")
    print("Next: python live_voice_6.py")


if __name__ == "__main__":
    main()
