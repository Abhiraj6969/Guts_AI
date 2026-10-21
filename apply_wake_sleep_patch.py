"""apply_wake_sleep_patch.py - adds wake word + sleep phrase to Guts in ONE step.

  say "Guts"                  -> a small offline listener hears it and wakes him up
  say "Guts abhi band ho jao" -> he says a short goodbye and goes to sleep
  (also works: "ok bye", "bye", "so jao"; while asleep NOTHING is sent to Gemini)

It reads live_voice_4.py and creates a NEW file live_voice_5.py.
Your live_voice_4.py is NOT changed, so it stays as your backup.

Run (in the Guts_AI folder):
  python apply_wake_sleep_patch.py
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "live_voice_4.py"
DST = Path(sys.argv[2]) if len(sys.argv) > 2 else BASE / "live_voice_5.py"

NEW_WAKE = r'''# ================= WAKE WORD (offline, uses Vosk) =================
WAKE_ENABLED = True
WAKE = {"rec": None, "tried": False}


def init_wake():
    """Load the offline wake-word listener once. If it fails, Guts simply never sleeps."""
    if not WAKE_ENABLED or WAKE["tried"]:
        return
    WAKE["tried"] = True
    try:
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
        print("[Wake] Loading wake-word model (the first time it downloads about 40 MB) ...")
        model = Model(lang="en-us")
        WAKE["rec"] = KaldiRecognizer(model, SEND_RATE, '["guts", "[unk]"]')
        print("[Wake] Wake word ON. Say 'Guts abhi band ho jao' to sleep, then say Guts to wake him.")
    except Exception as e:
        print(f"[Wake] Wake word OFF, so he will never sleep: {e}")


def heard_wake(data: bytes) -> bool:
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
    return False


# "band ho jao" / "बंद हो जाओ" / "so jao" (Latin or Devanagari spelling)
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
    return False


# ================= LIVE SESSION ================='''

SEND_MIC_BLOCK = r'''data = await asyncio.to_thread(stream.read, CHUNK, False)
            if STATE["asleep"]:
                # asleep: nothing goes to Gemini, the offline listener only waits for the name
                if await asyncio.to_thread(heard_wake, data):
                    STATE["asleep"] = False
                    STATE["last_activity"] = time.time()
                    STATE["idle_count"] = 0
                    print("[Wake] Guts is awake.")
                    try:
                        await session.send_realtime_input(
                            text="[WAKE] Boss just called you by name. Reply with ONE very short Hinglish line.")
                    except Exception as e:
                        print(f"(wake message failed: {e})")
                continue'''

GOODBYE_BLOCK = r'''await handle_confirm(session, t)
                    if is_goodbye(t) and WAKE["rec"] is not None:
                        STATE["sleep_after_turn"] = True
                        print("[Wake] Goodbye heard. Sleeping after his reply.")'''

TURN_BLOCK = r'''if sc and sc.turn_complete:
                    if STATE["sleep_after_turn"]:
                        STATE["sleep_after_turn"] = False
                        STATE["asleep"] = True
                        print("[Wake] Guts is asleep. Say Guts to wake him.")'''

WATCH_BLOCK = r'''if STATE["asleep"]:
            while GUARD and GUARD.pop_event():
                pass
            continue
        if STATE["pending"]:'''

EDITS = [
    ("sleep state",
     '"visitor_mode": "roast", "visitor_until": 0.0}',
     '"visitor_mode": "roast", "visitor_until": 0.0,\n         "asleep": False, "sleep_after_turn": False}'),
    ("wake word code",
     "# ================= LIVE SESSION =================",
     NEW_WAKE),
    ("microphone loop",
     "data = await asyncio.to_thread(stream.read, CHUNK, False)",
     SEND_MIC_BLOCK),
    ("goodbye detection",
     "await handle_confirm(session, t)",
     GOODBYE_BLOCK),
    ("fall asleep after reply",
     "if sc and sc.turn_complete:",
     TURN_BLOCK),
    ("watcher stays quiet while asleep",
     'if STATE["pending"]:',
     WATCH_BLOCK),
    ("system message tags",
     "[FACE UNSURE] or [BOSS RECOGNIZED] come from the system",
     "[FACE UNSURE], [BOSS RECOGNIZED] or [WAKE] come from the system"),
    ("system prompt",
     'call research and answer from its result. "',
     'call research and answer from its result. "\n'
     '        "SLEEP: when Boss says bye, ok bye, or band ho jao (like Guts abhi band ho jao), '
     'reply with ONE very short goodbye line and nothing else. "'),
    ("load wake word at start",
     'print(f"[Contacts] {len(_load_contacts())} loaded from {CONTACTS_FILE}")',
     'print(f"[Contacts] {len(_load_contacts())} loaded from {CONTACTS_FILE}")\n    init_wake()'),
]


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run this from the Guts_AI folder.")
        return
    text = SRC.read_text(encoding="utf-8")
    if "WAKE WORD" in text:
        print("This file already has the wake word. Nothing to do.")
        return

    for label, anchor, new in EDITS:
        n = text.count(anchor)
        if n != 1:
            print(f"STOPPED. Could not safely patch '{label}' (found {n} matches, need 1).")
            print("Nothing was written. Send me this message and your live_voice_4.py.")
            return
        text = text.replace(anchor, new)

    compile(text, str(DST), "exec")          # syntax check before saving
    DST.write_text(text, encoding="utf-8")
    print(f"Done: {DST.name} created ({len(EDITS)} changes). {SRC.name} is untouched.")
    print("Next: pip install vosk   then   python live_voice_5.py")


if __name__ == "__main__":
    main()
