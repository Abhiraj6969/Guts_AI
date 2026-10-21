"""apply_pt_build_patch.py - Guts builds networks INSIDE Cisco Packet Tracer (not in VS Code).

New Guts tools:
  build_pt_lab     "Guts, 3 routers OSPF lab banao, har LAN mein 2 PC"
                   -> Gemini plans devices, cables, IPs and router/switch commands
                   -> a checker verifies them (duplicate IPs, wrong ports, missing no shutdown ...)
                   -> Boss says yes -> Guts opens Packet Tracer if needed, pastes and runs the script
  pt_send_demo     sends the small test network (1 switch, 2 PCs) into Packet Tracer

Needs in the Guts_AI folder: pt_lab.py, pt_send.py (calibrated once), pt_tools.py.

It finds your newest live_voice_N.py and creates live_voice_(N+1).py.
Your old file is NOT changed, so it stays as your backup.

Run (in the Guts_AI folder):
  python apply_pt_build_patch.py
or choose files yourself:
  python apply_pt_build_patch.py live_voice_11.py live_voice_12.py
"""
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent


def pick_files():
    if len(sys.argv) > 2:
        return Path(sys.argv[1]), Path(sys.argv[2])
    nums = []
    for f in BASE.glob("live_voice_*.py"):
        m = re.fullmatch(r"live_voice_(\d+)\.py", f.name)
        if m:
            nums.append(int(m.group(1)))
    if not nums:
        return None, None
    n = max(nums)
    return BASE / f"live_voice_{n}.py", BASE / f"live_voice_{n + 1}.py"


PT_BLOCK = r'''# ================= CISCO PACKET TRACER: BUILD LABS INSIDE PACKET TRACER =================
def _wait_for_pt(seconds: int = 45) -> bool:
    """Opens Packet Tracer if needed and waits until its window exists."""
    import pt_send
    if pt_send.find_pt_main():
        return True
    open_packet_tracer()
    end = time.time() + seconds
    while time.time() < end:
        time.sleep(2)
        if pt_send.find_pt_main():
            time.sleep(4)            # let it finish loading
            return True
    return False


def _do_pt_send(path: str) -> str:
    """Runs only after Boss says yes: puts the script into Packet Tracer and presses Run."""
    import pt_send
    from pt_tools import clean_js
    script = clean_js(Path(path).read_text(encoding="utf-8"))
    if not _wait_for_pt():
        return ("Packet Tracer did not open in time (it may be waiting for Boss to sign in). "
                f"The script is saved at {path}")
    return pt_send.send(script)


def build_pt_lab(request: str) -> str:
    """Plan and check a Packet Tracer lab, then prepare to build it inside Packet Tracer."""
    try:
        import pt_lab
        import pt_tools
        pt_lab.LAB_DIR = pt_tools.PT_DIR
        result = pt_lab.make_lab(request)
    except Exception as e:
        return f"Lab planning failed: {e}"
    if not result["ok"]:
        return "Could not make a clean lab. Problems: " + " | ".join(result["errors"][:3])
    spec = result["spec"]
    path = str(Path(result["folder"]) / "lab.js")
    routers = "; ".join(f"{d} {i} {ip}" for d, i, ip, _ in spec.get("_ips", [])[:6])
    hosts = "; ".join(f"{h['name']} {h.get('ip') or 'DHCP'}" for h in spec.get("hosts", [])[:6])
    msg = _ask(f"build the lab '{spec.get('title')}' ({result['devices']} devices, {result['links']} cables) "
               "inside Packet Tracer. Guts will use the mouse for about 15 seconds, so Boss should not touch it",
               _do_pt_send, path=path)
    return (msg + f" Router and switch IPs: {routers or 'none'}. PC IPs: {hosts or 'none'}. "
            f"Say only the most useful addresses. The full table is in addressing.txt in {result['folder']}.")


def pt_send_demo() -> str:
    """Send a small test network (1 switch, 2 PCs) into Packet Tracer."""
    try:
        import pt_tools
        pt_tools.save_pt_script("demo", pt_tools.DEMO_JS)
        path = str(pt_tools.PT_DIR / "demo.js")
    except Exception as e:
        return f"Demo failed: {e}"
    return _ask("send a small test network (1 switch, 2 PCs) into Packet Tracer. Guts will use the mouse "
                "for about 15 seconds, so Boss should not touch it", _do_pt_send, path=path)


# ================= TOOL REGISTRY ================='''

NEW_DECLS = '''decl("pt_demo_topology", "Save a small test network script for Packet Tracer and copy it to the clipboard."),
    decl("build_pt_lab", "Build a Cisco Packet Tracer network for Boss inside Packet Tracer: plans the devices, cables, "
         "IP addresses and router/switch commands, checks them, then builds it after Boss says yes. Use it for any "
         "request like a 3 router OSPF lab, a VLAN lab or a small office network.",
         request="Boss's request in English with every detail he gave: devices, counts, protocols, VLANs, IP ranges"),
    decl("pt_send_demo", "Send the small test network (1 switch, 2 PCs) into Packet Tracer. Needs Boss's spoken yes."),'''

EDITS = [
    ("tool code",
     "# ================= TOOL REGISTRY =================",
     PT_BLOCK),
    ("tool list",
     "open_packet_tracer, pt_demo_topology, ip_plan, subnet_info]",
     "open_packet_tracer, pt_demo_topology, ip_plan, subnet_info, build_pt_lab, pt_send_demo]"),
    ("tool declarations",
     'decl("pt_demo_topology", "Save a small test network script for Packet Tracer and copy it to the clipboard."),',
     NEW_DECLS),
    ("yes rule for the new tools",
     "write_file, delete_path, run_program and send_whatsapp only PREPARE",
     "write_file, delete_path, run_program, send_whatsapp, build_pt_lab and pt_send_demo only PREPARE"),
    ("system prompt",
     "For any Packet Tracer or Cisco question give exact IOS commands",
     "To BUILD a network or topology in Packet Tracer (routers, switches, PCs, cables, IP addresses, routing, VLANs) "
     "call build_pt_lab with Boss's whole request in English. It plans and checks the lab, and builds it inside "
     "Packet Tracer after Boss says yes. To send the small test network into Packet Tracer call pt_send_demo. "
     "After build_pt_lab say in one or two short sentences what the lab is and the most useful IP addresses, "
     "and never read the whole table. "
     "For any Packet Tracer or Cisco question give exact IOS commands"),
]


def main():
    SRC, DST = pick_files()
    if not SRC or not SRC.exists():
        print("Cannot find your live_voice file. Run this from the Guts_AI folder.")
        return
    for need in ("pt_lab.py", "pt_send.py", "pt_tools.py"):
        if not (BASE / need).exists():
            print(f"Missing {need} in this folder. Put it next to this patch first.")
            return
    text = SRC.read_text(encoding="utf-8")
    if "build_pt_lab" in text:
        print("This file already has build_pt_lab. Nothing to do.")
        return

    for label, anchor, new in EDITS:
        n = text.count(anchor)
        if n != 1:
            print(f"STOPPED. Could not safely patch '{label}' (found {n} matches, need 1).")
            print(f"Nothing was written. Send me this message and your {SRC.name}.")
            return
        text = text.replace(anchor, new)

    compile(text, str(DST), "exec")          # syntax check before saving
    DST.write_text(text, encoding="utf-8")
    print(f"Done: {DST.name} created from {SRC.name} ({len(EDITS)} changes). {SRC.name} is untouched.")
    print(f"Next: stop Guts, then  python {DST.name}")


if __name__ == "__main__":
    main()
