"""apply_pt_patch.py - adds Cisco Packet Tracer tools (PART 1) to Guts.

New voice tools:
  open_packet_tracer   "Guts, packet tracer kholo"
  pt_demo_topology     "Guts, packet tracer ka test topology bhejo"

It reads your newest file (live_voice_9.py, else 8, else 7) and creates a NEW file live_voice_10.py.
The file you start from is NOT changed, so it stays as your backup.
pt_tools.py must be in the same folder.

Run (in the Guts_AI folder):
  python apply_pt_patch.py
Optional:  python apply_pt_patch.py live_voice_8.py live_voice_10.py
"""
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
CANDIDATES = ["live_voice_9.py", "live_voice_8.py", "live_voice_7.py"]
if len(sys.argv) > 1:
    SRC = Path(sys.argv[1])
else:
    SRC = next((BASE / n for n in CANDIDATES if (BASE / n).exists()), BASE / CANDIDATES[0])
DST = Path(sys.argv[2]) if len(sys.argv) > 2 else BASE / "live_voice_10.py"

IMPORT_LINE = "from pt_tools import open_packet_tracer, pt_demo_topology"
NEW_DECLS = '''decl("open_packet_tracer", "Open Cisco Packet Tracer."),
    decl("pt_demo_topology", "Save a small test network script for Packet Tracer and copy it to the clipboard."),
    '''
PROMPT_OLD = "To play a video or song call play_youtube. "
PROMPT_NEW = ("To play a video or song call play_youtube. "
              "CISCO PACKET TRACER: to open it call open_packet_tracer. To test the Packet Tracer setup call "
              "pt_demo_topology. For any Packet Tracer or Cisco question give exact IOS commands in the right "
              "order, short, and only commands Packet Tracer supports. Never invent a command, and say clearly "
              "when a feature is not available in Packet Tracer. ")


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run this from the Guts_AI folder.")
        return
    if not (BASE / "pt_tools.py").exists():
        print("pt_tools.py is missing. Put it in this folder first.")
        return
    text = SRC.read_text(encoding="utf-8")
    if "open_packet_tracer" in text:
        print("This file already has the Packet Tracer tools. Nothing to do.")
        return

    # 1) import
    pat = re.compile(r"^from google\.genai import types$", re.M)
    if len(pat.findall(text)) != 1:
        print("STOPPED. Could not find the import line. Nothing was written. Send me this message and your file.")
        return
    text = pat.sub(lambda m: m.group(0) + "\n" + IMPORT_LINE, text, count=1)

    # 2) tool list: put the new functions at the end of the list
    done = False
    for pattern in (r"force_close\]", r"close_item\]", r"run_code\]", r"send_whatsapp\]"):
        if len(re.findall(pattern, text)) == 1:
            text = re.sub(pattern, pattern[:-2] + ", open_packet_tracer, pt_demo_topology]", text, count=1)
            done = True
            break
    if not done:
        print("STOPPED. Could not find the tool list line. Nothing was written. Send me this message and your file.")
        return

    # 3) declarations
    if text.count('decl("send_whatsapp",') != 1:
        print("STOPPED. Could not find the send_whatsapp declaration. Nothing was written. Send me this message and your file.")
        return
    text = text.replace('decl("send_whatsapp",', NEW_DECLS + 'decl("send_whatsapp",', 1)

    # 4) system prompt
    if text.count(PROMPT_OLD) != 1:
        print("STOPPED. Could not find the system prompt line. Nothing was written. Send me this message and your file.")
        return
    text = text.replace(PROMPT_OLD, PROMPT_NEW)

    compile(text, str(DST), "exec")          # syntax check before saving
    DST.write_text(text, encoding="utf-8")
    print(f"Done: {DST.name} created from {SRC.name}. {SRC.name} is untouched.")
    print("Next: python live_voice_10.py   then say: Guts, packet tracer kholo")


if __name__ == "__main__":
    main()
