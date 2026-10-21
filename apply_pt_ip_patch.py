"""apply_pt_ip_patch.py - adds the IP planner (Packet Tracer PART 2) to Guts.

New voice tools:
  ip_plan      "Guts, IP plan bana: Sales 50, HR 20, IT 10 aur 2 router links"
  subnet_info  "Guts, 192.168.1.130/26 ka network aur broadcast batao"

It reads your newest file (live_voice_10.py, else 9) and creates a NEW file live_voice_11.py.
The file you start from is NOT changed, so it stays as your backup.
pt_ip.py must be in the same folder.

Run (in the Guts_AI folder):
  python apply_pt_ip_patch.py
Optional:  python apply_pt_ip_patch.py live_voice_10.py live_voice_11.py
"""
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
CANDIDATES = ["live_voice_10.py", "live_voice_9.py"]
if len(sys.argv) > 1:
    SRC = Path(sys.argv[1])
else:
    SRC = next((BASE / n for n in CANDIDATES if (BASE / n).exists()), BASE / CANDIDATES[0])
DST = Path(sys.argv[2]) if len(sys.argv) > 2 else BASE / "live_voice_11.py"

NEW_DECLS = '''decl("ip_plan", "Make an exact VLSM IP addressing plan with subnets, masks, gateways and ranges. "
         "Saves a table and opens it on screen.", _req=["lans"],
         lans="LANs and host counts, like Sales:50, HR:20, IT:10",
         base_network="Optional starting network like 192.168.10.0/24. Leave empty to choose automatically",
         links="Number of router to router links, like 2. Use 0 if none",
         name="Short name for the plan, like office"),
    decl("subnet_info", "Exact details of one IP address or subnet: network, mask, wildcard, broadcast, host range.",
         address="Like 192.168.1.130/26 or 192.168.1.130 255.255.255.192"),
    '''
PROMPT_ANCHOR = "pt_demo_topology. For any Packet Tracer"
PROMPT_NEW = ("pt_demo_topology. For IP addressing or subnetting always call ip_plan or subnet_info and use "
              "its exact result, never calculate IP addresses yourself. For any Packet Tracer")


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run apply_pt_patch.py first, in the Guts_AI folder.")
        return
    if not (BASE / "pt_ip.py").exists():
        print("pt_ip.py is missing. Put it in this folder first.")
        return
    text = SRC.read_text(encoding="utf-8")
    if "ip_plan, subnet_info" in text:
        print("This file already has the IP planner. Nothing to do.")
        return

    pat = re.compile(r"^from pt_tools import .*$", re.M)
    if len(pat.findall(text)) != 1:
        print("STOPPED. Could not find the pt_tools import (run apply_pt_patch.py first). Nothing was written.")
        print("Send me this message and your file.")
        return
    text = pat.sub(lambda m: m.group(0) + "\nfrom pt_ip import ip_plan, subnet_info", text, count=1)

    if len(re.findall(r"pt_demo_topology\]", text)) != 1:
        print("STOPPED. Could not find the tool list line. Nothing was written. Send me this message and your file.")
        return
    text = re.sub(r"pt_demo_topology\]", "pt_demo_topology, ip_plan, subnet_info]", text, count=1)

    if text.count('decl("pt_demo_topology",') != 1:
        print("STOPPED. Could not find the declaration spot. Nothing was written. Send me this message and your file.")
        return
    text = text.replace('decl("pt_demo_topology",', NEW_DECLS + 'decl("pt_demo_topology",', 1)

    if text.count(PROMPT_ANCHOR) != 1:
        print("STOPPED. Could not find the system prompt line. Nothing was written. Send me this message and your file.")
        return
    text = text.replace(PROMPT_ANCHOR, PROMPT_NEW)

    compile(text, str(DST), "exec")          # syntax check before saving
    DST.write_text(text, encoding="utf-8")
    print(f"Done: {DST.name} created from {SRC.name}. {SRC.name} is untouched.")
    print("Next: python live_voice_11.py")
    print('Test: say "Guts, IP plan bana: Sales 50, HR 20, IT 10 aur 2 router links, base 192.168.10.0/24"')


if __name__ == "__main__":
    main()
