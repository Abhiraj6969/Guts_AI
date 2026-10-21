"""apply_video2_patch.py - adds video editing PART 2 (zoom, captions, hook title) to Guts.

New voice tools:
  video_pro_edit      "Guts, isko pro edit kar do, captions aur zoom ke saath"
  video_add_captions  "Guts, is video pe sirf captions laga do"
(video_status, from Part 1, shows the progress of both.)

Needs Part 1 already applied (apply_video_patch.py) and video_pro.py in the same folder.
It finds your NEWEST live_voice_N.py (the highest number) and creates the next number.
Your file is NOT changed, so it stays as your backup.

Run (in the Guts_AI folder):
  python apply_video2_patch.py
Optional:  python apply_video2_patch.py live_voice_15.py live_voice_16.py
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

NEW_DECLS = '''decl("video_pro_edit", "Full professional edit in the background: cuts silent gaps, 9:16 reel, zoom punch-ins "
         "on every second clip, Hinglish captions with the spoken word highlighted, a hook title, colour and loudness.",
         _req=["path"], path="Full path of the video",
         hook="auto to write a hook title, an empty string for none, or the exact hook text",
         style="reel for vertical 9:16 (default) or original to keep the size"),
    decl("video_add_captions", "Only add captions (and an optional hook title) to a video that is already edited. "
         "No cutting.", _req=["path"], path="Full path of the video", hook="Optional hook title text"),
    '''
PROMPT_ANCHOR = "Never say the video is finished until video_status says DONE. "
PROMPT_NEW = (PROMPT_ANCHOR + "PRO VIDEO EDIT: when Boss asks for captions, subtitles, zoom, a hook title or a pro "
              "edit, call video_pro_edit (not video_auto_edit). To only add captions to a finished video call "
              "video_add_captions. Both run in the background and take a few minutes, so say it started and use "
              "video_status when Boss asks if it is done. ")


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run this from the Guts_AI folder.")
        return
    if not (BASE / "video_pro.py").exists():
        print("video_pro.py is missing. Put it in this folder first.")
        return
    text = SRC.read_text(encoding="utf-8")
    if "video_pro_edit" in text:
        print("This file already has the pro video tools. Nothing to do.")
        return
    if "video_auto_edit" not in text:
        print("STOPPED. This file does not have video editing Part 1 yet. Run apply_video_patch.py first.")
        return

    pat = re.compile(r"^(from video_edit import .*)$", re.M)
    if len(pat.findall(text)) != 1:
        print("STOPPED. Could not find the video_edit import line. Nothing was written.")
        return
    text = pat.sub(lambda m: m.group(1) + "\nfrom video_pro import video_pro_edit, video_add_captions", text, count=1)

    lst = re.compile(r"(FUNCS = \[.*?)(\s*)\]\nTOOL_FUNCS", re.S)
    if len(lst.findall(text)) != 1:
        print("STOPPED. Could not find the tool list. Nothing was written. Send me this message and your file.")
        return
    text = lst.sub(lambda m: m.group(1) + ", video_pro_edit, video_add_captions]\nTOOL_FUNCS", text, count=1)

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
    print(f"Done: {DST.name} created from {SRC.name}. {SRC.name} is untouched.")
    print(f"Next: python {DST.name}   then say: Guts, meri latest video pro edit kar do")


if __name__ == "__main__":
    main()
