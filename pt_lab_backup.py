"""pt_lab.py - Guts builds Cisco Packet Tracer labs.

How it works (safe and reliable, no mouse clicking):
  1. Gemini plans the lab as DATA (devices, cables, IP addresses, router/switch commands).
  2. This file CHECKS the plan (duplicate IPs, wrong ports, missing 'no shutdown', bad masks ...)
     and asks Gemini to fix problems.
  3. This file writes a PTBuilder script (JavaScript) from the checked data and copies it.
  4. You paste it in Packet Tracer: Extensions > Builder Code Editor > Run.

Needs the free PTBuilder extension in Packet Tracer (https://github.com/kimmknight/PTBuilder).

Commands (run in the Guts_AI folder):
  python pt_lab.py --demo                 simple lab, NO Gemini needed (test the pipeline first)
  python pt_lab.py --demo2                2 routers + OSPF lab, NO Gemini needed
  python pt_lab.py "3 routers with OSPF and 2 PCs on each LAN"     Gemini plans it for you
  python pt_lab.py --spec pt_labs/some_lab/spec.json               rebuild from a saved plan

Everything is saved in the pt_labs folder: lab.js, spec.json and addressing.txt.
"""
import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
LAB_DIR = BASE / "pt_labs"
PT_MODEL = "gemini-3.8-flash"        # text model used for planning labs (change if you get 404/429)
KEY_NAMES = ["GEMINI_API_KEY_2", "GEMINI_API_KEY2", "GEMINI_BRAIN_KEY", "GEMINI_API_KEY"]   # tried in order
MAX_TRIES = 3

# ================= WHAT PHASE 1 SUPPORTS (Ethernet labs) =================
_SW_PORTS = [f"FastEthernet0/{i}" for i in range(1, 25)] + ["GigabitEthernet0/1", "GigabitEthernet0/2"]
PORTS = {
    # routers
    "2911": ["GigabitEthernet0/0", "GigabitEthernet0/1", "GigabitEthernet0/2"],
    "1941": ["GigabitEthernet0/0", "GigabitEthernet0/1"],
    "2901": ["GigabitEthernet0/0", "GigabitEthernet0/1"],
    "1841": ["FastEthernet0/0", "FastEthernet0/1"],
    "2811": ["FastEthernet0/0", "FastEthernet0/1"],
    # switches
    "2960-24TT": _SW_PORTS,
    "3560-24PS": _SW_PORTS,
    # end devices
    "PC-PT": ["FastEthernet0"],
    "Server-PT": ["FastEthernet0"],
    "Laptop-PT": ["FastEthernet0"],
}
KIND = {m: "router" for m in ("2911", "1941", "2901", "1841", "2811")}
KIND.update({m: "switch" for m in ("2960-24TT", "3560-24PS")})
KIND.update({m: "end" for m in ("PC-PT", "Server-PT", "Laptop-PT")})

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,19}$")
BAD_LINE = re.compile(r"^(enable|configure\s+terminal|conf\s+t|end|write|wr|copy|reload|erase|do)\b", re.I)
IFACE_RE = re.compile(r"^interface\s+(\S+)", re.I)
IP_RE = re.compile(r"^ip address (\d+\.\d+\.\d+\.\d+) (\d+\.\d+\.\d+\.\d+)", re.I)
TOP_RE = re.compile(r"^(router|line|ip dhcp|vlan|hostname|ip route|service|banner|access-list|ip access-list|"
                    r"username|enable|no ip domain|spanning-tree|ip routing|ip domain|crypto|ipv6|exit)\b", re.I)


# ================= PLAN CHECKER =================
def cable_for(kind_a: str, kind_b: str) -> str:
    """Switch-to-switch and router/PC-to-router/PC use cross-over; switch to anything else is straight."""
    return "cross" if (kind_a == "switch") == (kind_b == "switch") else "straight"


def validate(spec: dict):
    """Checks and tidies the plan in place. Returns (errors, warnings)."""
    errs, warns = [], []
    devs = {}
    spec["_ips"] = []

    for d in spec.get("devices", []):
        name, model = str(d.get("name", "")).strip(), str(d.get("model", "")).strip()
        if not NAME_RE.match(name):
            errs.append(f"Bad device name {name!r}: use letters, numbers, - or _ (start with a letter).")
            continue
        if name in devs:
            errs.append(f"Device name {name} is used twice.")
            continue
        if model not in PORTS:
            errs.append(f"{name}: model {model!r} is not supported. Use one of: {', '.join(PORTS)}.")
            continue
        d["name"], d["model"] = name, model
        devs[name] = {"model": model, "kind": KIND[model], "ports": PORTS[model], "used": set(), "blocks": {}}
    if not devs:
        errs.append("The plan has no valid devices.")
        return errs, warns

    # ---- cables ----
    for ln in spec.get("links", []):
        a, b = str(ln.get("a", "")), str(ln.get("b", ""))
        ok = True
        for dev, port in ((a, ln.get("a_if")), (b, ln.get("b_if"))):
            if dev not in devs:
                errs.append(f"Cable uses unknown device {dev!r}.")
                ok = False
            elif port not in devs[dev]["ports"]:
                errs.append(f"{dev} ({devs[dev]['model']}) has no port {port!r}. Use full names such as "
                            f"{devs[dev]['ports'][0]}. Valid ports: {', '.join(devs[dev]['ports'][:4])} ...")
                ok = False
            elif port in devs[dev]["used"]:
                errs.append(f"{dev} port {port} is used by two cables.")
                ok = False
            else:
                devs[dev]["used"].add(port)
        if ok:
            ln["type"] = cable_for(devs[a]["kind"], devs[b]["kind"])
    if len(devs) > 1 and not spec.get("links"):
        errs.append("The plan has devices but no cables.")

    # ---- IP bookkeeping ----
    seen = {}

    def add_ip(ip, where):
        if ip in seen:
            errs.append(f"Duplicate IP {ip}: {seen[ip]} and {where}.")
        else:
            seen[ip] = where

    # ---- router / switch commands ----
    for name, text in (spec.get("configs") or {}).items():
        if name not in devs or devs[name]["kind"] == "end":
            errs.append(f"Commands given for {name!r}, which is not a router or switch in the plan.")
            continue
        lines = [l.strip() for l in str(text).replace("\r", "").split("\n")]
        lines = [l for l in lines if l and not l.startswith("!") and not BAD_LINE.match(l)]
        spec["configs"][name] = "\n".join(lines)
        valid = {p.lower() for p in devs[name]["ports"]}
        cur = None
        blocks = devs[name]["blocks"]
        for line in lines:
            m = IFACE_RE.match(line)
            if m:
                cur = m.group(1).lower()
                cur_orig = m.group(1)
                if cur == "range":
                    cur = None
                else:
                    base = cur.split(".")[0]
                    if base not in valid and not base.startswith(("vlan", "loopback")):
                        errs.append(f"{name}: unknown interface {m.group(1)!r}. Use full names like "
                                    f"{devs[name]['ports'][0]}.")
                    blocks.setdefault(cur, {"ip": False, "noshut": False})
                continue
            if TOP_RE.match(line):
                cur = None
                continue
            if cur:
                ipm = IP_RE.match(line)
                if ipm:
                    ip, mask = ipm.groups()
                    try:
                        iface = ipaddress.IPv4Interface(f"{ip}/{mask}")
                        if iface.network.prefixlen < 31 and iface.ip in (iface.network.network_address,
                                                                       iface.network.broadcast_address):
                            errs.append(f"{name} {cur}: {ip}/{mask} is a network or broadcast address, not a host address.")
                    except ValueError:
                        errs.append(f"{name} {cur}: invalid IP or mask {ip} {mask}.")
                        continue
                    blocks[cur]["ip"] = True
                    add_ip(ip, f"{name} {cur}")
                    spec["_ips"].append((name, cur_orig, ip, mask))
                elif line.lower() == "no shutdown":
                    blocks[cur]["noshut"] = True
        for bname, flags in blocks.items():
            if devs[name]["kind"] == "router" and flags["ip"] and not flags["noshut"]:
                errs.append(f"{name} {bname} has an IP address but no 'no shutdown' (router ports start OFF).")

    # router ports that have a cable must be switched on
    for ln in spec.get("links", []):
        for dev, port in ((ln.get("a"), ln.get("a_if")), (ln.get("b"), ln.get("b_if"))):
            if dev in devs and devs[dev]["kind"] == "router" and port in devs[dev]["ports"]:
                if not devs[dev]["blocks"].get(port.lower(), {}).get("noshut"):
                    errs.append(f"{dev} {port} has a cable but no 'interface {port}' + 'no shutdown' in its commands.")

    # ---- PCs / servers / laptops ----
    host_names = set()
    for h in spec.get("hosts", []):
        name = str(h.get("name", "")).strip()
        if name not in devs or devs[name]["kind"] != "end":
            errs.append(f"IP settings given for {name!r}, which is not a PC, server or laptop in the plan.")
            continue
        host_names.add(name)
        if h.get("dhcp"):
            continue
        try:
            iface = ipaddress.IPv4Interface(f"{h.get('ip')}/{h.get('mask')}")
        except ValueError:
            errs.append(f"{name}: invalid IP or mask {h.get('ip')} {h.get('mask')}.")
            continue
        if iface.network.prefixlen < 31 and iface.ip in (iface.network.network_address, iface.network.broadcast_address):
            errs.append(f"{name}: {h.get('ip')} is a network or broadcast address.")
        add_ip(str(iface.ip), name)
        gw = h.get("gateway")
        if gw:
            try:
                if ipaddress.IPv4Address(gw) not in iface.network:
                    errs.append(f"{name}: gateway {gw} is not in the same subnet as {h.get('ip')}/{h.get('mask')}.")
            except ValueError:
                errs.append(f"{name}: invalid gateway {gw}.")
        else:
            warns.append(f"{name} has no default gateway (it can only talk inside its own LAN).")
    for name, d in devs.items():
        if d["kind"] == "end" and name not in host_names:
            warns.append(f"{name} has no IP settings in the plan.")
    for h in spec.get("hosts", []):
        gw = h.get("gateway")
        if gw and spec["_ips"] and gw not in seen:
            warns.append(f"{h.get('name')}: gateway {gw} is not configured on any router/switch in the plan.")

    # ---- screen positions ----
    rows = {"router": 150, "switch": 300, "end": 450}
    count = {"router": 0, "switch": 0, "end": 0}
    for d in spec.get("devices", []):
        if d["name"] not in devs:
            continue
        k = devs[d["name"]]["kind"]
        count[k] += 1
        try:
            d["x"] = max(40, min(1000, int(d["x"])))
            d["y"] = max(40, min(700, int(d["y"])))
        except (KeyError, TypeError, ValueError):
            d["x"], d["y"] = 100 + 150 * count[k], rows[k]
    return errs, warns


# ================= SCRIPT AND TABLE WRITERS =================
def q(s) -> str:
    """Safe JavaScript string (JSON is valid JavaScript). Nothing from the plan is ever run as code."""
    return json.dumps(str(s))


def to_js(spec: dict) -> str:
    # NO comments here: PTBuilder joins all lines into one line when you press Run,
    # so a // comment would swallow the whole script. Only plain statements, ASCII only.
    out = []
    for d in spec["devices"]:
        out.append(f'addDevice({q(d["name"])},{q(d["model"])},{d["x"]},{d["y"]});')
    for ln in spec.get("links", []):
        out.append(f'addLink({q(ln["a"])},{q(ln["a_if"])},{q(ln["b"])},{q(ln["b_if"])},{q(ln["type"])});')
    for name, text in (spec.get("configs") or {}).items():
        if text:
            out.append(f"configureIosDevice({q(name)}, {q(text)});")
    for h in spec.get("hosts", []):
        if h.get("dhcp"):
            out.append(f'configurePcIp({q(h["name"])}, true);')
            continue
        args = [q(h["name"]), "false", q(h["ip"]), q(h["mask"])]
        if h.get("gateway") or h.get("dns"):
            args.append(q(h.get("gateway", "")))
        if h.get("dns"):
            args.append(q(h["dns"]))
        out.append(f"configurePcIp({', '.join(args)});")
    return "\n".join(out) + "\n"


def addressing(spec: dict) -> str:
    rows = [("Device", "Interface", "IP address", "Subnet mask", "Gateway")]
    for dev, iface, ip, mask in spec.get("_ips", []):
        rows.append((dev, iface, ip, mask, ""))
    for h in spec.get("hosts", []):
        if h.get("dhcp"):
            rows.append((h["name"], "FastEthernet0", "DHCP", "", ""))
        else:
            rows.append((h["name"], "FastEthernet0", h.get("ip", ""), h.get("mask", ""), h.get("gateway", "")))
    widths = [max(len(str(r[i])) for r in rows) for i in range(5)]
    lines = ["  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)).rstrip() for r in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return f"{spec.get('title', 'Guts lab')}\n\n" + "\n".join(lines) + "\n"


# ================= GEMINI PLANNER =================
SYSTEM_PROMPT = f"""You plan Cisco Packet Tracer labs. Reply with ONE JSON object and nothing else.

JSON format:
{{
 "title": "short lab title",
 "devices": [{{"name": "R1", "model": "2911", "x": 300, "y": 150}}],
 "links": [{{"a": "R1", "a_if": "GigabitEthernet0/0", "b": "S1", "b_if": "FastEthernet0/1"}}],
 "hosts": [{{"name": "PC1", "dhcp": false, "ip": "192.168.1.10", "mask": "255.255.255.0", "gateway": "192.168.1.1", "dns": ""}}],
 "configs": {{"R1": "hostname R1\\ninterface GigabitEthernet0/0\\nip address 192.168.1.1 255.255.255.0\\nno shutdown"}}
}}

ALLOWED MODELS AND THEIR PORTS (use these exact names, never abbreviations like Gi0/0):
Routers: 2911 (GigabitEthernet0/0-0/2), 1941 and 2901 (GigabitEthernet0/0-0/1), 1841 and 2811 (FastEthernet0/0-0/1).
Switches: 2960-24TT and 3560-24PS (FastEthernet0/1 to FastEthernet0/24, GigabitEthernet0/1, GigabitEthernet0/2).
End devices: PC-PT, Server-PT, Laptop-PT (one port: FastEthernet0).
No serial links and no modules in this version: connect routers to each other with Ethernet ports.

RULES
- Every device has a short unique name (R1, S1, PC1 ...). x is 100-900, y is 100-600, spread them so nothing overlaps (routers on top, switches in the middle, PCs at the bottom).
- Each port is used by at most one cable. Do not set a cable type, the program does that.
- "hosts" has one entry for every PC, server and laptop. Use static IPs unless DHCP is asked for.
- Addressing: private ranges only. One subnet per LAN (use /24 mask 255.255.255.0 unless told otherwise) and a /30 (255.255.255.252) for each router-to-router link. The PC default gateway is the router (or layer 3 switch) interface IP on that LAN. No two interfaces share an IP.
- "configs" has IOS commands for each router and switch that needs them, as ONE string with \\n between lines.
  Commands are global-configuration commands only. NEVER write enable, configure terminal, end, write, copy, reload, erase or any show command.
  Always start with hostname. Every router interface that has a cable MUST have 'interface <full name>' followed by 'no shutdown' (ip address before it when it needs one).
  When there are 2 or more routers, add routing (static routes, RIPv2, OSPF or EIGRP, whatever the request names, OSPF if not named) so every LAN can reach every other LAN.
  For VLANs: create them on the switches, put ports in them with switchport access vlan, and make links between switches trunks. For several VLANs on one router port use router-on-a-stick subinterfaces (encapsulation dot1Q) and put 'no shutdown' on the physical port.
- Keep the lab as small as the request allows, but complete: if the request says 3 routers and 2 PCs per LAN, build exactly that.
"""


def _api_key():
    for n in KEY_NAMES:
        if os.getenv(n):
            return os.getenv(n), n
    return None, None


def ask_gemini(request: str, previous: dict = None, problems: list = None) -> dict:
    from dotenv import load_dotenv
    from google import genai
    from google.genai import types
    load_dotenv(BASE / ".env")
    key, name = _api_key()
    if not key:
        raise RuntimeError("No Gemini key found in .env. Names tried: " + ", ".join(KEY_NAMES) +
                           ". Edit KEY_NAMES at the top of pt_lab.py to match your .env.")
    prompt = request
    if previous and problems:
        clean = {k: v for k, v in previous.items() if not k.startswith("_")}
        prompt = (f"Request: {request}\n\nYour previous plan:\n{json.dumps(clean)}\n\n"
                  "A checker found these problems. Fix ALL of them and return the complete corrected JSON:\n- "
                  + "\n- ".join(problems))
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=PT_MODEL, contents=prompt,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0.2,
                                           response_mime_type="application/json"))
    text = (resp.text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    return json.loads(text)


# ================= DEMO PLANS (no Gemini needed) =================
DEMO = {
    "title": "Demo 1: one router, one switch, two PCs",
    "devices": [{"name": "R1", "model": "2911", "x": 300, "y": 150},
                {"name": "S1", "model": "2960-24TT", "x": 300, "y": 300},
                {"name": "PC1", "model": "PC-PT", "x": 200, "y": 450},
                {"name": "PC2", "model": "PC-PT", "x": 400, "y": 450}],
    "links": [{"a": "R1", "a_if": "GigabitEthernet0/0", "b": "S1", "b_if": "FastEthernet0/1"},
              {"a": "S1", "a_if": "FastEthernet0/2", "b": "PC1", "b_if": "FastEthernet0"},
              {"a": "S1", "a_if": "FastEthernet0/3", "b": "PC2", "b_if": "FastEthernet0"}],
    "hosts": [{"name": "PC1", "dhcp": False, "ip": "192.168.1.10", "mask": "255.255.255.0", "gateway": "192.168.1.1"},
              {"name": "PC2", "dhcp": False, "ip": "192.168.1.11", "mask": "255.255.255.0", "gateway": "192.168.1.1"}],
    "configs": {"R1": "hostname R1\ninterface GigabitEthernet0/0\nip address 192.168.1.1 255.255.255.0\nno shutdown",
                "S1": "hostname S1"},
}

DEMO2 = {
    "title": "Demo 2: two routers with OSPF, two LANs",
    "devices": [{"name": "R1", "model": "2911", "x": 250, "y": 150},
                {"name": "R2", "model": "2911", "x": 550, "y": 150},
                {"name": "S1", "model": "2960-24TT", "x": 250, "y": 300},
                {"name": "S2", "model": "2960-24TT", "x": 550, "y": 300},
                {"name": "PC1", "model": "PC-PT", "x": 250, "y": 450},
                {"name": "PC2", "model": "PC-PT", "x": 550, "y": 450}],
    "links": [{"a": "R1", "a_if": "GigabitEthernet0/1", "b": "R2", "b_if": "GigabitEthernet0/1"},
              {"a": "R1", "a_if": "GigabitEthernet0/0", "b": "S1", "b_if": "FastEthernet0/1"},
              {"a": "R2", "a_if": "GigabitEthernet0/0", "b": "S2", "b_if": "FastEthernet0/1"},
              {"a": "S1", "a_if": "FastEthernet0/2", "b": "PC1", "b_if": "FastEthernet0"},
              {"a": "S2", "a_if": "FastEthernet0/2", "b": "PC2", "b_if": "FastEthernet0"}],
    "hosts": [{"name": "PC1", "dhcp": False, "ip": "192.168.1.10", "mask": "255.255.255.0", "gateway": "192.168.1.1"},
              {"name": "PC2", "dhcp": False, "ip": "192.168.2.10", "mask": "255.255.255.0", "gateway": "192.168.2.1"}],
    "configs": {
        "R1": "hostname R1\ninterface GigabitEthernet0/0\nip address 192.168.1.1 255.255.255.0\nno shutdown\n"
              "interface GigabitEthernet0/1\nip address 10.0.0.1 255.255.255.252\nno shutdown\n"
              "router ospf 1\nnetwork 192.168.1.0 0.0.0.255 area 0\nnetwork 10.0.0.0 0.0.0.3 area 0",
        "R2": "hostname R2\ninterface GigabitEthernet0/0\nip address 192.168.2.1 255.255.255.0\nno shutdown\n"
              "interface GigabitEthernet0/1\nip address 10.0.0.2 255.255.255.252\nno shutdown\n"
              "router ospf 1\nnetwork 192.168.2.0 0.0.0.255 area 0\nnetwork 10.0.0.0 0.0.0.3 area 0",
        "S1": "hostname S1", "S2": "hostname S2"},
}


# ================= SAVE / COPY =================
def to_clipboard(text: str) -> bool:
    try:
        subprocess.run("clip", input=text.encode("ascii", "replace"), shell=True, check=True)
        return True
    except Exception:
        return False


def save_lab(spec: dict, js: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "_", str(spec.get("title", "lab")).lower()).strip("_")[:40] or "lab"
    folder = LAB_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in spec.items() if not k.startswith("_")}
    (folder / "spec.json").write_text(json.dumps(clean, indent=2), encoding="utf-8")
    (folder / "lab.js").write_text(js, encoding="utf-8")
    (folder / "addressing.txt").write_text(addressing(spec), encoding="utf-8")
    return folder


def build(spec: dict) -> dict:
    """Check, write files, copy script. Returns a short result dictionary (Guts uses this too)."""
    errs, warns = validate(spec)
    if errs:
        return {"ok": False, "errors": errs, "warnings": warns, "spec": spec}
    js = to_js(spec)
    folder = save_lab(spec, js)
    copied = to_clipboard(js)
    return {"ok": True, "errors": [], "warnings": warns, "folder": str(folder), "copied": copied,
            "devices": len(spec["devices"]), "links": len(spec.get("links", [])), "spec": spec}


def make_lab(request: str) -> dict:
    """Gemini plans, the checker verifies, up to MAX_TRIES rounds."""
    spec, problems, result = None, None, None
    for attempt in range(1, MAX_TRIES + 1):
        print(f"[Lab] Planning (try {attempt}/{MAX_TRIES}) ...")
        spec = ask_gemini(request, spec, problems)
        result = build(spec)
        if result["ok"]:
            return result
        problems = result["errors"]
        print(f"[Lab] Checker found {len(problems)} problem(s), asking Gemini to fix them:")
        for p in problems[:6]:
            print("   -", p)
    return result


def report(result: dict):
    if not result["ok"]:
        print("\nCould not make a clean lab. Problems left:")
        for p in result["errors"]:
            print("  -", p)
        return
    spec = result["spec"]
    print(f"\nLab ready: {spec.get('title')}  ({result['devices']} devices, {result['links']} cables)")
    print(f"Saved in: {result['folder']}")
    print(addressing(spec))
    for w in result["warnings"]:
        print("Note:", w)
    if result["copied"]:
        print("The script is COPIED. In Packet Tracer: Extensions > Builder Code Editor, click in the "
              "editor, press Ctrl+V, then press Run.")
    else:
        print("Could not copy automatically. Open lab.js from the folder above and copy it by hand.")


def send_to_pt(result: dict) -> str:
    """Pushes the finished script into Packet Tracer (see pt_send.py)."""
    import pt_send
    return pt_send.send((Path(result["folder"]) / "lab.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    args = sys.argv[1:]
    send = "--send" in args
    args = [a for a in args if a != "--send"]
    if not args:
        print(__doc__)
    else:
        if args[0] == "--demo":
            res = build(json.loads(json.dumps(DEMO)))
        elif args[0] == "--demo2":
            res = build(json.loads(json.dumps(DEMO2)))
        elif args[0] == "--spec" and len(args) > 1:
            res = build(json.loads(Path(args[1]).read_text(encoding="utf-8")))
        else:
            res = make_lab(" ".join(args))
        report(res)
        if send and res["ok"]:
            print("[Send]", send_to_pt(res))
