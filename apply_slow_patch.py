"""apply_slow_patch.py - stops the "keepalive ping timeout / 1011" disconnects during long jobs.

What went wrong in your log:
  Guts called build_pt_lab. The AI that plans the lab can take 30-90 seconds (it retries, and hits 429 limits).
  While Guts waited for that ONE tool, the live connection to Gemini went quiet and Google closed it:
  "sent 1011 (internal error) keepalive ping timeout". The answer then had nowhere to go.

The fix: slow tools run in the BACKGROUND.
  - the tool call is answered at once: "started, I will tell you when it is done"
  - the live connection stays busy and alive
  - when the job finishes, Guts gets a [TOOL DONE] message and tells you the result

Default slow tools: build_pt_lab, write_code. (Edit SLOW_TOOLS in the new file to add or remove.)

It reads your NEWEST live_voice_N.py and creates the next number. Your file is NOT changed.

Run (in the Guts_AI folder):
  python apply_slow_patch.py
Optional:  python apply_slow_patch.py live_voice_21.py live_voice_22.py
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

HELPER = '''# ================= SLOW TOOLS (run in the background so the live connection never waits) =================
SLOW_TOOLS = {"build_pt_lab", "write_code"}
_SLOW_JOBS = {}


def start_slow_tool(session, name, args):
    job = _SLOW_JOBS.get(name)
    if job is not None and not job.done():
        return (f"{name} is already running in the background. Tell Boss in one short sentence to wait, "
                "and do not start it again.")
    _SLOW_JOBS[name] = asyncio.create_task(_run_slow_tool(session, name, args))
    return ("STARTED in the background, it can take up to a minute. In ONE short sentence tell Boss it is running "
            "and that you will tell him when it is done. Do not call this tool again and do not wait.")


async def _run_slow_tool(session, name, args):
    try:
        result = await asyncio.to_thread(TOOL_FUNCS[name], **args)
    except Exception as e:
        result = f"Error: {e}"
    text = str(result)
    print(f"[Slow] {name} finished: {text[:200]}")
    try:
        await session.send_realtime_input(
            text=f"[TOOL DONE] {name} finished. Result: {text[:1500]} "
                 "Tell Boss the outcome in one or two short Hinglish sentences. Do not read the tag aloud.")
        STATE["last_activity"] = time.time()
    except Exception as e:
        print(f"[Slow] could not tell Guts (the connection changed): {e}. The result is printed above.")


'''


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run this from the Guts_AI folder.")
        return
    text = SRC.read_text(encoding="utf-8")
    if "SLOW_TOOLS" in text:
        print("This file already runs slow tools in the background. Nothing to do.")
        return

    call = re.compile(r"^([ \t]*)result = await asyncio\.to_thread\(TOOL_FUNCS\[fc\.name\], \*\*args\)[ \t]*$", re.M)
    if len(call.findall(text)) != 1:
        print(f"STOPPED. Found {len(call.findall(text))} places where tools are run, expected 1. Nothing was written.")
        print("Send me this message and the lines around 'asyncio.to_thread(TOOL_FUNCS' in your file.")
        return
    text = call.sub(lambda m: (f"{m.group(1)}if fc.name in SLOW_TOOLS:\n"
                               f"{m.group(1)}    result = start_slow_tool(session, fc.name, args)\n"
                               f"{m.group(1)}else:\n"
                               f"{m.group(1)}    result = await asyncio.to_thread(TOOL_FUNCS[fc.name], **args)"),
                    text, count=1)

    anchor = re.compile(r"^async def play_replies\(session\):", re.M)
    if len(anchor.findall(text)) != 1:
        print("STOPPED. Could not find play_replies. Nothing was written. Send me this message and your file.")
        return
    text = anchor.sub(lambda m: HELPER + m.group(0), text, count=1)

    compile(text, str(DST), "exec")          # syntax check before saving
    DST.write_text(text, encoding="utf-8")
    print(f"Done: {DST.name} created from {SRC.name}. {SRC.name} is untouched.")
    print(f"Next: python {DST.name}   then ask for a Packet Tracer lab again.")


if __name__ == "__main__":
    main()
