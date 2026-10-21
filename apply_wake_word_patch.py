"""apply_wake_word_patch.py - changes Guts's wake phrase to "black swordsman".

  asleep + you say "black swordsman" (or "black sword man")  -> Guts wakes up
  "Guts" no longer wakes him. It is only his name when he is awake.

It reads your newest file (live_voice_7.py, else live_voice_6.py) and creates a NEW file live_voice_8.py.
The file you start from is NOT changed, so it stays as your backup.

Run (in the Guts_AI folder):
  python apply_wake_word_patch.py
Optional:  python apply_wake_word_patch.py live_voice_6.py live_voice_8.py
"""
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
CANDIDATES = ["live_voice_7.py", "live_voice_6.py"]
if len(sys.argv) > 1:
    SRC = Path(sys.argv[1])
else:
    SRC = next((BASE / n for n in CANDIDATES if (BASE / n).exists()), BASE / CANDIDATES[0])
DST = Path(sys.argv[2]) if len(sys.argv) > 2 else BASE / "live_voice_8.py"

NEW_WAKE_BLOCK = r'''
# ---- wake phrase: "black swordsman" ----
WAKE_GRAMMAR = ["black", "swordsman", "sword", "man", "[unk]"]   # the only words the wake listener knows


def wake_match(words) -> bool:
    """True when 'black swordsman' was said (the listener may split it as 'black sword man')."""
    joined = "".join(words)
    return "blackswordsman" in joined or "blackswordman" in joined or "blackswordsmen" in joined
'''

# the line that decides "was the wake phrase said": two known forms
CHECK_FORMS = [
    ("ok = len(words) <= WAKE_MAX_WORDS and bool(WAKE_WORDS & set(words))",
     "ok = len(words) <= WAKE_MAX_WORDS and wake_match(words)"),
    ("if WAKE_WORDS & set(text.split()):",
     "if wake_match(text.split()):"),
]

TEXT_SWAPS = [
    ("Say Guts to wake him", "Say black swordsman to wake him"),
    ("say Guts to wake him", "say black swordsman to wake him"),
    ("Guts is asleep. Say Guts", "Guts is asleep. Say black swordsman"),
]


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run this from the Guts_AI folder.")
        return
    text = SRC.read_text(encoding="utf-8")
    if "def wake_match" in text:
        print("This file already uses the new wake phrase. Nothing to do.")
        return

    # 1) add the phrase matcher right after the old WAKE_WORDS line (the old line stays, harmless)
    pat_words = re.compile(r"^WAKE_WORDS = .*$", re.M)
    if len(pat_words.findall(text)) != 1:
        print("STOPPED. Could not find the WAKE_WORDS line (need live_voice_6.py or newer).")
        print("Nothing was written. Send me this message and the file you ran.")
        return
    text = pat_words.sub(lambda m: m.group(0) + "\n" + NEW_WAKE_BLOCK, text, count=1)

    # 2) the listener only knows the new words
    pat_rec = re.compile(r"KaldiRecognizer\(\s*(\w+)\s*,\s*SEND_RATE[^\n]*\)")
    if len(pat_rec.findall(text)) != 1:
        print("STOPPED. Could not find the KaldiRecognizer line.")
        print("Nothing was written. Send me this message and the file you ran.")
        return
    text = pat_rec.sub(lambda m: f"KaldiRecognizer({m.group(1)}, SEND_RATE, json.dumps(WAKE_GRAMMAR))", text, count=1)

    # 3) the check itself
    done = False
    for old, new in CHECK_FORMS:
        if text.count(old) == 1:
            text = text.replace(old, new)
            done = True
            break
    if not done:
        print("STOPPED. Could not find the line that checks the wake word.")
        print("Nothing was written. Send me this message and the file you ran.")
        return

    # 4) friendly messages (only if they exist)
    for old, new in TEXT_SWAPS:
        text = text.replace(old, new)

    compile(text, str(DST), "exec")          # syntax check before saving
    DST.write_text(text, encoding="utf-8")
    print(f"Done: {DST.name} created from {SRC.name}. {SRC.name} is untouched.")
    print('Wake phrase is now: "black swordsman". Next: python live_voice_8.py')
    print('Test: say "ok bye", wait 6 sec, then say "black swordsman". Watch the [Wake] heard: lines.')


if __name__ == "__main__":
    main()
