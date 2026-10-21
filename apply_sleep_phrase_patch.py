"""apply_sleep_phrase_patch.py - lets you put Guts to sleep by saying "Guts abhi band ho jao".

  say "Guts"                 -> he wakes up (already works)
  say "Guts abhi band ho jao" -> he says a short goodbye and goes to sleep
  (also works: "ok bye", "bye", "so jao")

It reads live_voice_5.py and creates a NEW file live_voice_6.py.
Your live_voice_5.py is NOT changed, so it stays as your backup.

Run (in the Guts_AI folder):
  python apply_sleep_phrase_patch.py
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "live_voice_5.py"
DST = Path(sys.argv[2]) if len(sys.argv) > 2 else BASE / "live_voice_6.py"

OLD_FUNC = r'''def is_goodbye(text: str) -> bool:
    words = set(re.findall(r"[\w\u0900-\u097F]+", text.lower()))
    return bool(words & {"bye", "बाय"})'''

NEW_FUNC = r'''# "band ho jao" / "बंद हो जाओ" / "so jao" (Latin or Devanagari spelling)
SLEEP_RE = re.compile(
    r"(band|bund|बंद|बन्द)\s*(ho|हो)\s*(jao|jaao|ja|जाओ|जा)|(so|सो)\s*(jao|jaao|ja|जाओ|जा)")
_RECENT = []   # (time, text) of the last few seconds, because the transcript arrives in pieces


def is_goodbye(text: str) -> bool:
    now = time.time()
    _RECENT.append((now, text.lower()))
    _RECENT[:] = [(t, s) for t, s in _RECENT if now - t < 8]
    low = " ".join(s for _, s in _RECENT)
    words = set(re.findall(r"[\w\u0900-\u097F]+", low))
    if (words & {"bye", "बाय"}) or SLEEP_RE.search(low):
        _RECENT.clear()
        return True
    return False'''

EDITS = [
    ("sleep phrases", OLD_FUNC, NEW_FUNC),
    ("system prompt",
     "SLEEP: when Boss says bye or ok bye,",
     'SLEEP: when Boss says bye, ok bye, or band ho jao (like Guts abhi band ho jao),'),
]


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run this from the Guts_AI folder.")
        return
    text = SRC.read_text(encoding="utf-8")
    if "SLEEP_RE" in text:
        print("This file already has the sleep phrase. Nothing to do.")
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
