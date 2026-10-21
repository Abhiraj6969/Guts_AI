"""apply_game_patch.py - adds Tekken 8 + Game Buddy (PART 1) to Guts.

New voice tools:
  open_tekken8   "Guts, tekken 8 chalu karo"
  game_buddy     "Guts, game buddy on"  /  "game buddy off"   (he watches the game window and talks)

It finds your NEWEST live_voice_N.py (the highest number) and creates the next number.
Your file is NOT changed, so it stays as your backup. game_buddy.py must be in the same folder.

Run (in the Guts_AI folder):
  python apply_game_patch.py
Optional:  python apply_game_patch.py live_voice_12.py live_voice_13.py
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

NEW_FUNCS = "open_tekken8, game_buddy"
NEW_DECLS = '''decl("open_tekken8", "Start Tekken 8 through Steam."),
    decl("game_buddy", "Turn game buddy on or off. On: Guts watches the Tekken 8 window and comments like a friend.",
         _req=["mode"], mode="on, off or status"),
    '''
PROMPT_ANCHOR = "To play a video or song call play_youtube. "
PROMPT_NEW = ("To play a video or song call play_youtube. TEKKEN 8: to start the game call open_tekken8. To be "
              "Boss's game buddy call game_buddy with on. While it is on you see the Tekken window and a "
              "[GAME TICK] message arrives every few seconds: answer a tick with ONE very short Hinglish line "
              "(maximum 12 words): hype, call-out, trash talk or a tip. Never invent frame data or move names "
              "you are not sure of; say you are not sure instead. When Boss asks for a tip or what just "
              "happened, answer from what you see. On a menu or loading screen make a tiny joke. Stop with "
              "game_buddy off. ")


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run this from the Guts_AI folder.")
        return
    if not (BASE / "game_buddy.py").exists():
        print("game_buddy.py is missing. Put it in this folder first.")
        return
    text = SRC.read_text(encoding="utf-8")
    if "game_buddy" in text:
        print("This file already has the game buddy. Nothing to do.")
        return

    pat = re.compile(r"^from google\.genai import types$", re.M)
    if len(pat.findall(text)) != 1:
        print("STOPPED. Could not find the import line. Nothing was written. Send me this message and your file.")
        return
    text = pat.sub(lambda m: m.group(0) + "\nfrom game_buddy import " + NEW_FUNCS + ", game_stream", text, count=1)

    lst = re.compile(r"(FUNCS = \[.*?)(\s*)\]\nTOOL_FUNCS", re.S)
    if len(lst.findall(text)) != 1:
        print("STOPPED. Could not find the tool list. Nothing was written. Send me this message and your file.")
        return
    text = lst.sub(lambda m: m.group(1) + ", " + NEW_FUNCS + "]\nTOOL_FUNCS", text, count=1)

    if text.count('decl("send_whatsapp",') != 1:
        print("STOPPED. Could not find the declaration spot. Nothing was written. Send me this message and your file.")
        return
    text = text.replace('decl("send_whatsapp",', NEW_DECLS + 'decl("send_whatsapp",', 1)

    if text.count(PROMPT_ANCHOR) != 1:
        print("STOPPED. Could not find the system prompt line. Nothing was written. Send me this message and your file.")
        return
    text = text.replace(PROMPT_ANCHOR, PROMPT_NEW)

    task = re.compile(r"^([ \t]*)tg\.create_task\(play_replies\(session\)\)$", re.M)
    if len(task.findall(text)) != 1:
        print("STOPPED. Could not find where the live tasks start. Nothing was written. Send me this message and your file.")
        return
    text = task.sub(lambda m: m.group(0) + "\n" + m.group(1) + "tg.create_task(game_stream(session, STATE))", text, count=1)

    compile(text, str(DST), "exec")          # syntax check before saving
    DST.write_text(text, encoding="utf-8")
    print(f"Done: {DST.name} created from {SRC.name}. {SRC.name} is untouched.")
    print(f"Next: python -m pip install pillow   then   python {DST.name}")
    print("Test: say 'Guts, tekken 8 chalu karo', then 'game buddy on'.")


if __name__ == "__main__":
    main()
