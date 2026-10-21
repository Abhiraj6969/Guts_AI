"""pt_ip.py - exact IP addressing for Guts (Packet Tracer PART 2). All maths is done by Python, not guessed.

  ip_plan(...)      VLSM plan: "Sales:50, HR:20, IT:10" + 2 router links -> subnets, masks, gateways, ranges
  subnet_info(...)  "192.168.1.130/26" -> network, mask, wildcard, broadcast, host range, next subnet

Plans are saved in projects\\packet_tracer\\ as <name>_addressing.md and <name>_plan.json
(Part 3 will read the .json to build the topology and the configs).
"""
import os
import re
import sys
import json
import math
import ipaddress
from pathlib import Path

BASE = Path(__file__).resolve().parent
PT_DIR = BASE / "projects" / "packet_tracer"
OPEN_TABLE = False   # True = also open the table file in your default editor (VS Code). Packet Tracer cannot show tables.


# ---------- helpers ----------
def _prefix_for_hosts(hosts: int) -> int:
    """Smallest block that fits `hosts` usable addresses (network and broadcast are extra)."""
    need = hosts + 2
    return 32 - max(2, math.ceil(math.log2(need)))        # never smaller than /30


def _usable(net: ipaddress.IPv4Network) -> int:
    if net.prefixlen == 32:
        return 1
    if net.prefixlen == 31:
        return 2
    return net.num_addresses - 2


def _host_range(net: ipaddress.IPv4Network):
    if net.prefixlen >= 31:
        hs = list(net)
        return hs[0], hs[-1]
    return net.network_address + 1, net.broadcast_address - 1


def parse_lans(text: str):
    """'Sales:50, HR 20; IT=10' -> [('Sales', 50), ('HR', 20), ('IT', 10)]"""
    out = []
    for part in re.split(r"[,;\n]+", text or ""):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(.+?)\s*[:= ]\s*(\d+)\s*(?:hosts?|pcs?|computers?|devices?)?$", part, re.I)
        if not m:
            m2 = re.match(r"^(\d+)\s*(?:hosts?|pcs?|computers?|devices?)?\s+(.+)$", part, re.I)
            if not m2:
                raise ValueError(f"Cannot read '{part}'. Use the form Name:Hosts, for example Sales:50")
            name, hosts = m2.group(2).strip(), int(m2.group(1))
        else:
            name, hosts = m.group(1).strip(), int(m.group(2))
        if hosts < 1:
            raise ValueError(f"'{name}' needs at least 1 host")
        out.append((name, hosts))
    if not out:
        raise ValueError("No LANs given. Use the form Sales:50, HR:20")
    return out


def _auto_base(total_addresses: int) -> str:
    for cidr in ("192.168.0.0/24", "192.168.0.0/23", "192.168.0.0/22", "192.168.0.0/20", "192.168.0.0/16",
                 "172.16.0.0/12", "10.0.0.0/8"):
        if ipaddress.ip_network(cidr).num_addresses >= total_addresses:
            return cidr
    raise ValueError("Too many addresses needed for a private block")


def vlsm(base: str, lans, links: int = 0):
    """Core VLSM allocation. Returns (list_of_subnet_dicts, base_network)."""
    items = [{"name": n, "hosts": h, "kind": "lan"} for n, h in lans]
    items += [{"name": f"Link{i + 1}", "hosts": 2, "kind": "link"} for i in range(links)]
    for it in items:
        it["prefix"] = _prefix_for_hosts(it["hosts"])
    total = sum(2 ** (32 - it["prefix"]) for it in items)
    base_net = ipaddress.ip_network(_auto_base(total) if not base else base, strict=False)
    if base_net.num_addresses < total:
        raise ValueError(f"{base_net} has {base_net.num_addresses} addresses but this plan needs {total}. "
                         f"Use a bigger block, for example /{32 - math.ceil(math.log2(total))} or larger.")
    cur = int(base_net.network_address)
    end = int(base_net.broadcast_address) + 1
    out = []
    # biggest first keeps every block aligned and wastes nothing; links (/30) end up last
    for it in sorted(items, key=lambda x: (x["prefix"], 0 if x["kind"] == "lan" else 1)):
        size = 2 ** (32 - it["prefix"])
        cur = (cur + size - 1) // size * size
        if cur + size > end:
            raise ValueError(f"Ran out of space in {base_net} while placing {it['name']}.")
        net = ipaddress.ip_network((cur, it["prefix"]))
        first, last = _host_range(net)
        out.append({
            "name": it["name"], "kind": it["kind"], "hosts_needed": it["hosts"],
            "network": str(net.network_address), "prefix": net.prefixlen, "mask": str(net.netmask),
            "first_host": str(first), "last_host": str(last), "broadcast": str(net.broadcast_address),
            "usable": _usable(net),
            "gateway": str(first) if it["kind"] == "lan" else None,
        })
        cur += size
    return out, base_net


def _markdown(title: str, base_net, subnets) -> str:
    used = sum(2 ** (32 - s["prefix"]) for s in subnets)
    lines = [f"# {title}", "", f"Base network: **{base_net}**  |  addresses used: {used} of {base_net.num_addresses} "
             f"({used * 100 // base_net.num_addresses}%)", "",
             "| Subnet | Hosts needed | Network | Mask | Gateway / first host | Usable range | Broadcast | Usable |",
             "|---|---|---|---|---|---|---|---|"]
    for s in subnets:
        gw = s["gateway"] or s["first_host"]
        lines.append(f"| {s['name']} | {s['hosts_needed']} | {s['network']}/{s['prefix']} | {s['mask']} | {gw} | "
                     f"{s['first_host']} - {s['last_host']} | {s['broadcast']} | {s['usable']} |")
    lines += ["", "Rules used: biggest subnet first (VLSM), gateway = first usable address, "
              "router links use /30 (R1 = first host, R2 = second host)."]
    return "\n".join(lines) + "\n"


# ---------- tools for Guts ----------
def ip_plan(lans: str, base_network: str = "", links: str = "0", name: str = "plan") -> str:
    """VLSM IP plan. lans like 'Sales:50, HR:20, IT:10'. links = number of router-to-router /30 links."""
    try:
        n_links = int(float(links)) if str(links).strip() else 0
        subnets, base_net = vlsm(base_network.strip(), parse_lans(lans), max(0, n_links))
    except Exception as e:
        return f"PLAN ERROR: {e}"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "plan"
    PT_DIR.mkdir(parents=True, exist_ok=True)
    md = PT_DIR / f"{safe}_addressing.md"
    md.write_text(_markdown(f"IP plan: {safe}", base_net, subnets), encoding="utf-8")
    (PT_DIR / f"{safe}_plan.json").write_text(
        json.dumps({"name": safe, "base": str(base_net), "subnets": subnets}, indent=2), encoding="utf-8")
    opened = ""
    if OPEN_TABLE and sys.platform == "win32":
        try:
            os.startfile(str(md))
            opened = " The table is open on screen."
        except Exception:
            pass
    rows = "\n".join(f"{s['name']}: {s['network']}/{s['prefix']}  mask {s['mask']}  "
                     f"{'gateway ' + s['gateway'] + '  ' if s['gateway'] else ''}range {s['first_host']} to {s['last_host']}"
                     for s in subnets)
    return (f"Plan inside {base_net} (exact, calculated by code). Full table saved in {md}.{opened}\n{rows}\n"
            "Read only the subnet names with their network/prefix and gateway to Boss. Do not read the whole table.")


def subnet_info(address: str) -> str:
    """Details of one address or subnet. Accepts '192.168.1.130/26' or '192.168.1.130 255.255.255.192'."""
    try:
        txt = address.strip()
        m = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)$", txt)
        iface = ipaddress.ip_interface(f"{m.group(1)}/{m.group(2)}" if m else txt)
        if not isinstance(iface, ipaddress.IPv4Interface):
            return "Only IPv4 is supported here."
        net = iface.network
        first, last = _host_range(net)
        nxt = ""
        try:
            nxt = str(ipaddress.ip_network((int(net.broadcast_address) + 1, net.prefixlen)))
        except Exception:
            pass
        kind = "private" if iface.ip.is_private else "public"
        return (f"Address {iface.ip}/{net.prefixlen}\n"
                f"Network {net.network_address}  Mask {net.netmask}  Wildcard {net.hostmask}\n"
                f"Broadcast {net.broadcast_address}\n"
                f"Hosts {first} to {last}  (usable {_usable(net)})\n"
                f"Next subnet {nxt}  Type {kind}"
                + ("  This address is the network address itself." if iface.ip == net.network_address and net.prefixlen < 31 else "")
                + ("  This address is the broadcast address." if iface.ip == net.broadcast_address and net.prefixlen < 31 else ""))
    except Exception as e:
        return f"Cannot read '{address}': {e}"
