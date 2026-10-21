"""pt_tools.py - Cisco Packet Tracer helpers for Guts (PART 1).

  open_packet_tracer()   opens Packet Tracer
  pt_demo_topology()     saves a tiny test network script (PTBuilder JavaScript) and copies it to the clipboard

Put this file in the Guts_AI folder. Scripts are saved in projects\\packet_tracer\\.
"""
import os
import re
import sys
import glob
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent
PT_DIR = BASE / "projects" / "packet_tracer"

# PTBuilder functions (confirmed from the PTBuilder project):
#   addDevice(name, model, x, y)
#   addLink(dev1, port1, dev2, port2, "straight")
#   configurePcIp(name, dhcp, ip, mask, gateway, dns)
#   configureIosDevice(name, commands)
# IMPORTANT: PTBuilder deletes every line break before it runs the code, so a // comment would swallow
# the whole script and cause "parse error". Scripts must NEVER contain // comments (clean_js removes them).
DEMO_JS = """addDevice("S1", "2960-24TT", 200, 150);
addDevice("PC1", "PC-PT", 100, 280);
addDevice("PC2", "PC-PT", 300, 280);
addLink("S1", "FastEthernet0/1", "PC1", "FastEthernet0", "straight");
addLink("S1", "FastEthernet0/2", "PC2", "FastEthernet0", "straight");
configurePcIp("PC1", false, "192.168.1.10", "255.255.255.0", "192.168.1.1");
configurePcIp("PC2", false, "192.168.1.11", "255.255.255.0", "192.168.1.1");
"""


def _find_pt():
    skip = ("uninstall", "help", "readme", "license")
    roots = [os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
             os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")]
    for r in roots:
        for dp, _, fs in os.walk(r):
            for f in fs:
                low = f.lower()
                if low.endswith(".lnk") and "packet tracer" in low and not any(s in low for s in skip):
                    return os.path.join(dp, f)
    for pat in (r"C:\Program Files\Cisco Packet Tracer*\bin\PacketTracer*.exe",
                r"C:\Program Files (x86)\Cisco Packet Tracer*\bin\PacketTracer*.exe"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return None


def open_packet_tracer() -> str:
    """Open Cisco Packet Tracer."""
    p = _find_pt()
    if not p:
        return ("Packet Tracer was not found on this PC. Install it from Cisco Networking Academy "
                "(netacad.com), then try again.")
    try:
        os.startfile(p)
        return "Opening Packet Tracer. It takes 10 to 20 seconds, and it may ask Boss to sign in."
    except Exception as e:
        return f"Could not open Packet Tracer: {e}"


def _copy_to_clipboard(text: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        subprocess.run(["clip"], input=text.encode("utf-16"), check=True)
        return True
    except Exception:
        pass
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                       input=text.encode("utf-8"), check=True)
        return True
    except Exception:
        return False


def clean_js(js: str) -> str:
    """Make a script safe for PTBuilder: no comments, no BOM, plain ASCII, one statement per line."""
    js = js.replace("\ufeff", "")
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)          # /* block comments */
    out_lines = []
    for line in js.splitlines():
        res, quote, i = [], None, 0
        while i < len(line):
            ch = line[i]
            if quote:
                res.append(ch)
                if ch == "\\" and i + 1 < len(line):
                    res.append(line[i + 1])
                    i += 1
                elif ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
                res.append(ch)
            elif ch == "/" and line[i:i + 2] == "//":
                break                                      # rest of the line is a comment
            else:
                res.append(ch)
            i += 1
        text = "".join(res).rstrip()
        if text.strip():
            out_lines.append(text)
    cleaned = "\n".join(out_lines) + "\n"
    return cleaned.encode("ascii", "ignore").decode("ascii")


def save_pt_script(name: str, js: str) -> str:
    """Save a PTBuilder script in projects\\packet_tracer and copy it to the clipboard."""
    js = clean_js(js)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "topology"
    PT_DIR.mkdir(parents=True, exist_ok=True)
    path = PT_DIR / f"{safe}.js"
    path.write_text(js, encoding="utf-8")
    copied = _copy_to_clipboard(js)
    return f"Saved {path}. " + ("Copied to the clipboard." if copied else "Could not copy to the clipboard, open the file and copy it.")


def pt_demo_topology() -> str:
    """Test the Packet Tracer setup: saves a small test network script and copies it to the clipboard."""
    r = save_pt_script("demo", DEMO_JS)
    return (r + " Tell Boss: in Packet Tracer click Extensions, then Builder Code Editor, press Ctrl+V to paste, "
            "then click Run. A switch with two PCs should appear. If the Builder Code Editor is missing, "
            "PTBuilder is not installed yet.")
