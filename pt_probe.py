"""pt_probe.py - asks Packet Tracer what a script is allowed to do (needed for the ping test).

Why: the official Packet Tracer API can run commands on a device and write files, but I cannot
tell from here whether the Builder Code Editor lets scripts use them in YOUR version.
This probe adds ONE extra PC to your workspace, tries each feature, writes the answers into
pt_probe_result.txt, and explains the result in plain words.

Run (Packet Tracer open, pt_send.py already calibrated and working):
  python pt_probe.py
"""
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
RESULT = BASE / "pt_probe_result.txt"

TEMPLATE = r"""addDevice("NAME","PC-PT",600,120);
var __r = [];
function __t(n, f) { try { __r.push(n + ": " + f()); } catch (e) { __r.push(n + ": FAIL " + e); } }
__t("ipc", function () { return typeof ipc; });
__t("network", function () { return typeof ipc.network(); });
__t("getDevice", function () { return ipc.network().getDevice("NAME") ? "found" : "not found"; });
__t("getCommandLine", function () { return ipc.network().getDevice("NAME").getCommandLine() ? "ok" : "null"; });
__t("registerEvent", function () { return typeof ipc.network().getDevice("NAME").getCommandLine().registerEvent; });
__t("setTimeout", function () { return typeof setTimeout; });
__t("fileManager", function () { return typeof ipc.systemFileManager(); });
__t("write", function () { return ipc.systemFileManager().writePlainTextToFile(PATHJSON, __r.join("\n")); });
"""


def probe_script(result_path: Path, name: str) -> str:
    """The test script. No // comments (PTBuilder joins all lines into one line), ASCII only."""
    path_js = json.dumps(str(result_path).replace("\\", "/"))
    return TEMPLATE.replace("PATHJSON", path_js).replace("NAME", name)


def parse(text: str) -> dict:
    res = {}
    for line in text.splitlines():
        if ": " in line:
            k, v = line.split(": ", 1)
            res[k.strip()] = v.strip()
    return res


def interpret(text: str) -> list:
    """Plain-words verdict from the probe file."""
    r = parse(text)

    def good(k):
        v = r.get(k)
        return v is not None and not v.startswith("FAIL") and v not in ("undefined", "null", "not found")

    out = []
    if not good("ipc") or r.get("ipc") == "undefined":
        return ["Scripts in this editor cannot reach Packet Tracer's internal API ('ipc' is missing). "
                "Ping from a script is NOT possible this way. Fallback: Guts checks the plan in Python instead."]
    for key, label in (("network", "network access"), ("getDevice", "finding a device by name"),
                       ("getCommandLine", "a device's command line"), ("fileManager", "file writing")):
        out.append(f"{'OK  ' if good(key) else 'FAIL'} {label}: {r.get(key, 'no answer')}")
    out.append(f"{'OK  ' if r.get('registerEvent') == 'function' else 'NOTE'} reading command output (events): "
               f"{r.get('registerEvent', 'no answer')}")
    out.append(f"{'OK  ' if r.get('setTimeout') == 'function' else 'NOTE'} waiting (timers): "
               f"{r.get('setTimeout', 'no answer')}")
    if good("getDevice") and good("getCommandLine") and good("fileManager"):
        out.append("VERDICT: a script can type commands (like ping) into a PC and write results to a file. "
                   "The ping test CAN be built.")
        if r.get("registerEvent") != "function":
            out.append("But reading the command output needs another method. I will adapt the ping script.")
        if r.get("setTimeout") != "function":
            out.append("There are no timers, so the ping script must check for results in a different way.")
    else:
        out.append("VERDICT: some pieces are missing, so a full ping test is not possible yet. "
                   "Paste this report to me and I will pick the best fallback.")
    return out


def run() -> None:
    import pt_send
    if RESULT.exists():
        RESULT.unlink()
    name = f"PROBE{int(time.time()) % 10000}"
    print("[Probe] Sending the test script into Packet Tracer (it adds one PC named", name + ") ...")
    print("[Probe]", pt_send.send(probe_script(RESULT, name)))
    for _ in range(20):
        if RESULT.exists():
            break
        time.sleep(1)
    if not RESULT.exists():
        print("\nNo result file appeared. Possible reasons:")
        print(" - the script had an error: look at the Builder Code Editor for a message and paste it to me")
        print(" - scripts cannot write files or use ipc in this version")
        print(" - pt_send did not reach the editor (see the [Probe] line above)")
        return
    text = RESULT.read_text(encoding="utf-8", errors="ignore")
    print("\nWhat Packet Tracer answered:\n" + text)
    print("What it means:")
    for line in interpret(text):
        print(" -", line)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--explain":
        print("\n".join(interpret(Path(sys.argv[2]).read_text(encoding="utf-8"))))
    else:
        run()
