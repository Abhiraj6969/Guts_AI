"""apply_video3_patch.py - adds video editing PART 3 (music) to Guts.

  "Guts, is video ko music ke saath pro edit karo"   -> video_pro_edit with music (zoom on the beat)
  "Guts, is video pe music laga do"                   -> video_add_music (video that is already edited)
  "Guts, kaun kaun se gaane hain?"                    -> music_list

Needs Part 2 already applied (apply_video2_patch.py) and video_music.py + video_pro.py in the same folder.
It finds your NEWEST live_voice_N.py (the highest number) and creates the next number.
Your file is NOT changed, so it stays as your backup.

Run (in the Guts_AI folder):
  python apply_video3_patch.py
Optional:  python apply_video3_patch.py live_voice_16.py live_voice_17.py
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

NEW_DECLS = '''decl("video_add_music", "Add background music to a video that is already edited. The music gets quieter "
         "while Boss speaks, fades in and out, and the loudness is fixed.", _req=["path"],
         path="Full path of the video",
         music="auto for a random song from the music folder, part of a song name, or a full file path"),
    decl("music_list", "List the songs in the music folder."),
    '''
MUSIC_PARAM = ('music="Empty for no music, auto for a random song from the music folder, part of a song name, '
               'or a file path"')
PROMPT_ANCHOR = ("call video_add_captions. Both run in the background and take a few minutes, so say it started "
                 "and use video_status when Boss asks if it is done. ")
PROMPT_NEW = (PROMPT_ANCHOR + "MUSIC: when Boss wants background music, call video_pro_edit with music set (auto "
              "picks a random song from the music folder, or use part of a song name), or call video_add_music for a "
              "video that is already edited. To see the songs call music_list. The music gets quieter while Boss "
              "speaks, and with music the zoom follows the beat. ")


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run this from the Guts_AI folder.")
        return
    for need in ("video_music.py", "video_pro.py"):
        if not (BASE / need).exists():
            print(f"{need} is missing. Put it in this folder first.")
            return
    text = SRC.read_text(encoding="utf-8")
    if "video_add_music" in text:
        print("This file already has the music tools. Nothing to do.")
        return
    if "video_pro_edit" not in text:
        print("STOPPED. This file does not have video editing Part 2 yet. Run apply_video2_patch.py first.")
        return

    pat = re.compile(r"^(from video_pro import .*)$", re.M)
    if len(pat.findall(text)) != 1:
        print("STOPPED. Could not find the video_pro import line. Nothing was written.")
        return
    text = pat.sub(lambda m: m.group(1) + "\nfrom video_music import video_add_music, music_list", text, count=1)

    lst = re.compile(r"(FUNCS = \[.*?)(\s*)\]\nTOOL_FUNCS", re.S)
    if len(lst.findall(text)) != 1:
        print("STOPPED. Could not find the tool list. Nothing was written. Send me this message and your file.")
        return
    text = lst.sub(lambda m: m.group(1) + ", video_add_music, music_list]\nTOOL_FUNCS", text, count=1)

    dec = re.compile(r'hook="auto to write a hook title[^"]*",\s*style="[^"]*"\)')
    found = dec.findall(text)
    if len(found) != 1:
        print("STOPPED. Could not find the video_pro_edit declaration. Nothing was written. Send me this message and your file.")
        return
    text = dec.sub(lambda m: m.group(0)[:-1] + ",\n         " + MUSIC_PARAM + ")", text, count=1)

    if text.count('decl("send_whatsapp",') != 1:
        print("STOPPED. Could not find the declaration spot. Nothing was written. Send me this message and your file.")
        return
    text = text.replace('decl("send_whatsapp",', NEW_DECLS + 'decl("send_whatsapp",', 1)

    if text.count(PROMPT_ANCHOR) != 1:
        print("STOPPED. Could not find the system prompt line. Nothing was written. Send me this message and your file.")
        return
    text = text.replace(PROMPT_ANCHOR, PROMPT_NEW)

    compile(text, str(DST), "exec")          # syntax check before saving
    DST.write_text(text, encoding="utf-8")
    (BASE / "music").mkdir(exist_ok=True)
    print(f"Done: {DST.name} created from {SRC.name}. {SRC.name} is untouched.")
    print(f"A folder called music was created. Put your songs (mp3, wav, m4a) in it.")
    print(f"Next: python {DST.name}   then say: Guts, meri latest video music ke saath pro edit karo")


if __name__ == "__main__":
    main()
