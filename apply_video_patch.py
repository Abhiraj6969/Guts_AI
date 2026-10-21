"""apply_video_patch.py - adds video editing (PART 1) to Guts.

New voice tools:
  latest_video      "Guts, meri latest video dhundo"
  video_info        "is video ki length batao"
  video_auto_edit   "Guts, isko reel bana do"      (runs in the background)
  video_status      "edit ho gaya?"

It finds your NEWEST live_voice_N.py (the highest number) and creates the next number.
Your file is NOT changed, so it stays as your backup. video_edit.py must be in the same folder.

Run (in the Guts_AI folder):
  python apply_video_patch.py
Optional:  python apply_video_patch.py live_voice_11.py live_voice_12.py
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

NEW_FUNCS = "latest_video, video_info, video_auto_edit, video_status"
NEW_DECLS = '''decl("latest_video", "Find the newest video file in Downloads, Desktop, Documents, Videos or a folder path."
         , _req=[], folder="Downloads, Desktop, Documents, Videos or a folder path. Default Downloads"),
    decl("video_info", "Length, size, fps and audio of a video file.", path="Full path of the video"),
    decl("video_auto_edit", "Professional auto edit in the background: cuts silent gaps, makes a 9:16 reel with "
         "a blurred background, fixes colour and loudness, exports mp4.", _req=["path"],
         path="Full path of the video", style="reel for vertical 9:16 (default) or original to keep the size"),
    decl("video_status", "Progress or result of the running video edit."),
    '''
PROMPT_ANCHOR = "To play a video or song call play_youtube. "
PROMPT_NEW = ("To play a video or song call play_youtube. VIDEO EDITING: to find Boss's newest video call "
              "latest_video. To edit a video call video_auto_edit (reel means vertical 9:16 for Instagram Reels and "
              "YouTube Shorts). It runs in the background, so say it started and use video_status when Boss asks "
              "if it is done. Never say the video is finished until video_status says DONE. ")


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run this from the Guts_AI folder.")
        return
    if not (BASE / "video_edit.py").exists():
        print("video_edit.py is missing. Put it in this folder first.")
        return
    text = SRC.read_text(encoding="utf-8")
    if "video_auto_edit" in text:
        print("This file already has the video tools. Nothing to do.")
        return

    pat = re.compile(r"^from google\.genai import types$", re.M)
    if len(pat.findall(text)) != 1:
        print("STOPPED. Could not find the import line. Nothing was written. Send me this message and your file.")
        return
    text = pat.sub(lambda m: m.group(0) + "\nfrom video_edit import " + NEW_FUNCS, text, count=1)

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

    compile(text, str(DST), "exec")          # syntax check before saving
    DST.write_text(text, encoding="utf-8")
    print(f"Done: {DST.name} created from {SRC.name}. {SRC.name} is untouched.")
    print(f"Next: python {DST.name}   then say: Guts, meri latest video reel bana do")


if __name__ == "__main__":
    main()
