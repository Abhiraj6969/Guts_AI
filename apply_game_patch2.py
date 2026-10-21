"""apply_game_patch2.py - upgrades Guts to Game Buddy v2 (friend commentary, character names, quiet mode).

What changes in Guts:
  - his Tekken 8 knowledge (roster, Heat, Rage, Power Crush) goes into his prompt
  - game_buddy gets a boss_side option (left or right)
  - while the game buddy is on, his other auto-talk (idle chat, PC observations, visitor roasts) is OFF

You need: apply_game_patch.py already applied (your newest file has game_buddy), and the NEW game_buddy.py and
tekken8_knowledge.py in this folder.

It finds your NEWEST live_voice_N.py and creates the next number. Your file is NOT changed.

Run (in the Guts_AI folder):
  python apply_game_patch2.py
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

NEW_DECL = '''decl("game_buddy", "Friend commentary for Tekken 8. on = start, off = stop, status = the characters, health "
         "and rounds right now (use it to answer which character or who is winning).", _req=["mode"],
         mode="on, off or status", boss_side="left (default) or right: which side Boss plays on"),'''


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run this from the Guts_AI folder.")
        return
    for need in ("game_buddy.py", "tekken8_knowledge.py"):
        if not (BASE / need).exists():
            print(f"{need} is missing. Put it in this folder first.")
            return
    text = SRC.read_text(encoding="utf-8")
    if "GAME_PROMPT" in text:
        print("This file already has Game Buddy v2. Nothing to do.")
        return
    if "game_buddy" not in text:
        print("STOPPED. This file has no game buddy yet. Run apply_game_patch.py first. Nothing was written.")
        return

    # 1) import GAME_PROMPT too
    pat = re.compile(r"^from game_buddy import .*$", re.M)
    if len(pat.findall(text)) != 1:
        print("STOPPED. Could not find the game_buddy import. Nothing was written. Send me this message and your file.")
        return
    text = pat.sub("from game_buddy import open_tekken8, game_buddy, game_stream, GAME_PROMPT", text, count=1)

    # 2) new tool declaration (with boss_side)
    dec = re.compile(r'decl\("game_buddy",.*?mode="on, off or status"\),', re.S)
    if len(dec.findall(text)) != 1:
        print("STOPPED. Could not find the game_buddy declaration. Nothing was written. Send me this message and your file.")
        return
    text = dec.sub(lambda m: NEW_DECL, text, count=1)

    # 3) replace the old short Tekken text in the prompt with the full knowledge + commentary rules
    old = re.compile(r"TEKKEN 8: to start the game call open_tekken8\..*?game_buddy off\. ", re.S)
    if len(old.findall(text)) != 1:
        print("STOPPED. Could not find the old Tekken prompt text. Nothing was written. Send me this message and your file.")
        return
    text = old.sub(lambda m: '" + GAME_PROMPT + "', text, count=1)

    # 4) while the game buddy is on, the watcher stays quiet (no idle chat, no visitor roast, no PC notes)
    quiet = re.compile(r'^([ \t]*)silent = now - STATE\["last_activity"\]$', re.M)
    if len(quiet.findall(text)) != 1:
        print("STOPPED. Could not find the watcher loop. Nothing was written. Send me this message and your file.")
        return
    text = quiet.sub(lambda m: m.group(0) + "\n" + m.group(1) + 'if STATE.get("game_quiet"):\n'
                     + m.group(1) + "    continue", text, count=1)

    compile(text, str(DST), "exec")          # syntax check before saving
    DST.write_text(text, encoding="utf-8")
    print(f"Done: {DST.name} created from {SRC.name}. {SRC.name} is untouched.")
    print(f"Next: python {DST.name}")
    print("Test: 'Tekken 8 chalu karo', then 'game buddy on'. In menus he stays silent, in a fight he comments.")


if __name__ == "__main__":
    main()
