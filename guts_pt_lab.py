"""guts_pt_lab.py - Fully automated Cisco Packet Tracer Tool for Guts AI."""

import os
import pt_send
from pt_lab import make_lab, build, DEMO, DEMO2, to_js


def create_packet_tracer_lab(request: str) -> str:
    """Generates a Cisco Packet Tracer lab and automatically executes it live inside
    Packet Tracer using UI automation (Extensions > Builder Code Editor > Paste > Run).
    """
    try:
        req_low = request.lower().strip()

        # 1. Plan the topology
        if "demo1" in req_low or "simple demo" in req_low:
            res = build(DEMO)
        elif "demo2" in req_low or "ospf demo" in req_low:
            res = build(DEMO2)
        else:
            res = make_lab(request)

        if not res.get("ok"):
            err_msg = "\n".join(res.get("errors", ["Unknown planning error"])[:5])
            return f"Boss, lab planning me issue aaya:\n{err_msg}"

        spec = res["spec"]
        js_script = to_js(spec)

        # 2. AUTOMATION: Call pt_send to handle UI clicks, paste, and run
        print("\n🤖 [Guts AI] Sending script directly to Cisco Packet Tracer...")
        send_status = pt_send.send(js_script)

        # 3. Formulate response for Boss
        reply = (
            f"✅ Done Boss! '{spec.get('title')}' topology banayi aur Packet Tracer me load kar di.\n"
            f"• Execution Status: {send_status}\n"
            f"• Placed Devices: {res['devices']} | Cables Connected: {res['links']}\n\n"
            f"📋 IP Addressing Setup:\n"
        )

        for h in spec.get("hosts", []):
            reply += f"• {h['name']}: IP {h.get('ip', 'DHCP')} (GW: {h.get('gateway', 'N/A')})\n"

        for dev, iface, ip, mask in spec.get("_ips", []):
            reply += f"• {dev} [{iface}]: {ip} / {mask}\n"

        return reply

    except Exception as e:
        return f"Packet Tracer automation me error aaya: {str(e)}"