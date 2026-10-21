"""pt_check.py - finds out WHY Cisco Packet Tracer does not work with Guts.
Run it, then paste everything it prints.

  python pt_check.py            checks files, imports, Packet Tracer, the lab checker (no internet, no mouse)
  python pt_check.py --plan     also asks the AI to plan a tiny lab (uses a little quota, still no mouse)

It never clicks anything and never changes your files.
"""
import copy
import importlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
os.chdir(BASE)
rows = []


def ok(name, detail=""):
    rows.append(("OK  ", name, detail))


def bad(name, detail=""):
    rows.append(("FAIL", name, detail))


def note(name, detail=""):
    rows.append(("NOTE", name, detail))


def first_line(e) -> str:
    return (str(e).strip().splitlines() or [type(e).__name__])[0][:140]


# ---------------------------------------------------------------- .env
try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except Exception:
    pass

# ---------------------------------------------------------------- 1. files
for f in ("pt_tools.py", "pt_lab.py", "pt_send.py", "pt_ip.py", "guts_brain.py", ".env"):
    (ok if (BASE / f).exists() else bad)(f"file {f}", "found" if (BASE / f).exists() else "MISSING in the Guts_AI folder")

# ---------------------------------------------------------------- 2. imports and functions
mods = {}
need = {
    "pt_tools": ["open_packet_tracer", "pt_demo_topology", "clean_js", "save_pt_script", "PT_DIR", "DEMO_JS"],
    "pt_send": ["find_pt_main", "send"],
    "pt_lab": ["make_lab", "build", "validate", "to_js", "DEMO2"],
    "pt_ip": ["ip_plan", "subnet_info"],
}
for m, names in need.items():
    try:
        mods[m] = importlib.import_module(m)
        missing = [n for n in names if not hasattr(mods[m], n)]
        if missing:
            bad(f"import {m}", "works, but these are missing: " + ", ".join(missing))
        else:
            ok(f"import {m}", "all needed functions are there")
    except Exception as e:
        bad(f"import {m}", first_line(e))

# ---------------------------------------------------------------- 3. which planner version
pl = mods.get("pt_lab")
if pl:
    if hasattr(pl, "_json_from"):
        ok("lab planner", "new version (uses guts_brain with model fallback)")
    else:
        note("lab planner", "OLD version: one Gemini model only, so busy errors. Run: python apply_lab_fix.py")

# ---------------------------------------------------------------- 4. lab checker, offline
if pl and hasattr(pl, "validate") and hasattr(pl, "DEMO2"):
    try:
        spec = copy.deepcopy(pl.DEMO2)
        errs, warns = pl.validate(spec)
        if errs:
            bad("lab checker", "the built-in demo lab has problems: " + "; ".join(errs[:2]))
        else:
            js = pl.to_js(spec)
            ok("lab checker", f"demo lab is clean: {len(spec['devices'])} devices, script is {len(js)} characters")
    except Exception as e:
        bad("lab checker", first_line(e))

# ---------------------------------------------------------------- 5. Packet Tracer itself
try:
    import psutil
    procs = [p.info["name"] for p in psutil.process_iter(["name"]) if "packettracer" in (p.info["name"] or "").lower()]
    if procs:
        ok("Packet Tracer running", procs[0])
    else:
        note("Packet Tracer running", "not running right now (Guts opens it; it may then wait for your Cisco sign-in)")
except Exception as e:
    note("Packet Tracer running", "could not check: " + first_line(e))

lnk = None
for root in (os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
             os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")):
    if os.path.isdir(root):
        for dp, _, fs in os.walk(root):
            for f in fs:
                if f.lower().endswith(".lnk") and "packet tracer" in f.lower() and "uninstall" not in f.lower():
                    lnk = os.path.join(dp, f)
if lnk:
    ok("Packet Tracer installed", Path(lnk).stem)
else:
    note("Packet Tracer installed", "no Start Menu shortcut with 'Packet Tracer' in its name was found")

if "pt_send" in mods and hasattr(mods["pt_send"], "find_pt_main"):
    try:
        w = mods["pt_send"].find_pt_main()
        if w:
            ok("Packet Tracer main window", "found, so Guts can send a lab into it")
        else:
            note("Packet Tracer main window", "NOT found. If Packet Tracer is open, it is probably on its sign-in "
                 "screen. Sign in until you see the empty workspace, then try again")
    except Exception as e:
        bad("Packet Tracer main window", first_line(e))

# ---------------------------------------------------------------- 6. keys
for k in ("GEMINI_WORK_KEY", "GEMINI_API_KEY", "GROQ_API_KEY"):
    (ok if os.getenv(k) else note)(f"key {k}", "present" if os.getenv(k) else "not set")

# ---------------------------------------------------------------- 7. the newest voice file
nums = [int(m.group(1)) for p in BASE.glob("live_voice_*.py") if (m := re.fullmatch(r"live_voice_(\d+)\.py", p.name))]
if nums:
    name = f"live_voice_{max(nums)}.py"
    t = (BASE / name).read_text(encoding="utf-8", errors="replace")
    ok("newest voice file", name)
    if "take_sc (" in t:
        bad("voice prompt", "DAMAGED: a sentence was cut in half (take_sc), so Guts lost the close_item and "
            "screenshot instructions. Run: python apply_prompt_fix.py")
    else:
        ok("voice prompt", "no damaged sentence found")
    if t.count("build_pt_lab") >= 4 and "CISCO PACKET TRACER" in t:
        ok("Cisco tools in the voice file", "build_pt_lab is listed, declared and explained to Guts")
    else:
        bad("Cisco tools in the voice file", "build_pt_lab or its instructions are missing")
    note("face lock", "ON: every tool except status needs your face in the camera" if re.search(r"^FACE_LOCK = True", t, re.M)
         else "OFF")
else:
    bad("newest voice file", "no live_voice_N.py found in this folder")

# ---------------------------------------------------------------- 8. optional: ask the AI for a tiny lab
if "--plan" in sys.argv and pl:
    try:
        pl.LAB_DIR = Path(tempfile.mkdtemp(prefix="ptcheck_"))
        r = pl.make_lab("1 router, 1 switch and 2 PCs in one LAN")
        if r.get("ok"):
            ok("AI lab planning", f"worked: {r['devices']} devices, {r['links']} cables")
        else:
            bad("AI lab planning", " | ".join(r.get("errors", []))[:300])
    except Exception as e:
        bad("AI lab planning", first_line(e))
elif "--plan" in sys.argv:
    bad("AI lab planning", "skipped: pt_lab could not be imported")

# ---------------------------------------------------------------- report
print("\n" + "=" * 70)
for tag, name, detail in rows:
    print(f"{tag}  {name:34} {detail}")
print("=" * 70)
fails = [r for r in rows if r[0] == "FAIL"]
print(f"{len(fails)} problem(s) found." if fails else "No hard problems found in the files.")
print("Now paste this whole screen into the chat." if fails or "--plan" not in sys.argv else "")
if not fails:
    print("Next: ask Guts for a lab and paste the lines that start with [Tool], [Lab], [Brain] and [Action].")
