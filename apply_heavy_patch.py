"""apply_heavy_patch.py - connects heavy_brain.py (your 1 million token key) to Guts.

New Guts tools:
  heavy_task     big code, hard debugging, system design, deep analysis, long research, important documents
                 (Boss must say yes first, so tokens are never spent by accident)
  heavy_status   progress, the summary, and how many tokens are left

When the job finishes, Guts tells Boss by himself. The full answer is saved in projects\\heavy\\.
Casual talk, small code, IP plans and Packet Tracer labs do NOT use this key.

It finds your newest live_voice_N.py and creates live_voice_(N+1).py. Your old file is NOT changed.

Run (in the Guts_AI folder):
  python apply_heavy_patch.py
"""
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent


def pick_files():
    if len(sys.argv) > 2:
        return Path(sys.argv[1]), Path(sys.argv[2])
    nums = [int(m.group(1)) for f in BASE.glob("live_voice_*.py")
            if (m := re.fullmatch(r"live_voice_(\d+)\.py", f.name))]
    if not nums:
        return None, None
    n = max(nums)
    return BASE / f"live_voice_{n}.py", BASE / f"live_voice_{n + 1}.py"


HEAVY_BLOCK = r'''# ================= HEAVY BRAIN (second key, only for serious work) =================
import heavy_brain


def _heavy_precheck(task: str, kind: str, file_path: str) -> str:
    """Problems are reported BEFORE asking Boss for a yes."""
    cfg = heavy_brain._cfg()
    if not cfg:
        return "No heavy key yet. Boss must add HEAVY_API_KEY to the .env file, then restart Guts."
    if "error" in cfg:
        return cfg["error"]
    if not cfg.get("model"):
        return "HEAVY_MODEL is not set in .env. Boss can see the models with: python heavy_brain.py models"
    if (kind or "analysis").lower().strip() not in heavy_brain.KINDS:
        return f"kind must be one of: {', '.join(heavy_brain.KINDS)}."
    if len((task or "").strip()) < 20:
        return "That is too short for the heavy brain. Ask Boss for details first."
    if heavy_brain.JOB["state"] == "running":
        return "The heavy brain is already working. Use heavy_status."
    if file_path:
        try:
            heavy_brain._read_context(file_path)
        except Exception as e:
            return f"The file cannot be sent: {e}"
    return ""


def _do_heavy(task: str, kind: str, file_path: str) -> str:
    return heavy_brain.heavy_task(task, kind, file_path)


def heavy_task(task: str, kind: str = "analysis", file_path: str = "") -> str:
    """Send a serious task to the heavy brain. Needs Boss's spoken yes."""
    problem = _heavy_precheck(task, kind, file_path)
    if problem:
        return problem
    what = f"send a heavy {kind} task to the big brain (Boss's 1 million token key)"
    if file_path:
        what += f", together with the file {Path(file_path).name}"
    return _ask(what + f". Task: {task.strip()[:90]}", _do_heavy, task=task, kind=kind, file_path=file_path)


def heavy_status() -> str:
    """Progress of the heavy task, its summary when done, and the tokens left."""
    return heavy_brain.heavy_status()


# ================= TOOL REGISTRY ================='''

HEAVY_FUNCS = '''FUNCS += [heavy_task, heavy_status]
TOOL_FUNCS = {f.__name__: f for f in FUNCS}'''

HEAVY_DECLS = '''DECLS += [
    decl("heavy_task", "Send a SERIOUS task to the heavy brain (second api key, limited tokens). Only for: big or "
         "multi-file code, hard debugging, system design or architecture, deep analysis, long research, important "
         "documents. NEVER for chat, simple questions, small code, IP plans or Packet Tracer labs. Needs Boss's spoken yes.",
         _req=["task", "kind"],
         task="The full task with every detail Boss gave, in English, at least 20 characters",
         kind="One of: code, debug, architecture, research, analysis, planning, document",
         file_path="Optional full path of a text or code file to send along"),
    decl("heavy_status", "Progress of the heavy task, its summary when finished, and how many heavy tokens are left."),
]
assert {f.__name__ for f in FUNCS} == {d.name for d in DECLS}, "Tool function/declaration mismatch"'''

HEAVY_WATCH = '''job = heavy_brain.JOB
        if job["state"] in ("done", "failed") and STATE.get("heavy_told") != job["t0"]:
            STATE["heavy_told"] = job["t0"]
            if job["state"] == "done":
                text = ("[HEAVY DONE] The big brain finished. Say this summary in one or two short sentences: "
                        f"{job['summary']} Tell Boss the full answer is saved in {job['file']}.")
            else:
                text = f"[HEAVY FAILED] {job['msg']} Tell Boss in one short sentence."
            try:
                await session.send_realtime_input(text=text)
                STATE["last_activity"] = time.time()
                print(f"[Heavy] {job['state']}")
            except Exception as e:
                print(f"(heavy notice failed: {e})")
            continue
        if GUARD and silent > 3:'''

HEAVY_PROMPT = (
    "HEAVY BRAIN: for big or multi-file code, hard debugging, system design, deep analysis, long research or "
    "important documents (resume, report, assignment) call heavy_task with the full task in English and the right "
    "kind. It uses a limited-token key, so NEVER use it for chat, quick questions, small code (use write_code), "
    "IP plans or Packet Tracer labs. It only prepares the task and needs Boss's yes. It runs in the background: "
    "tell Boss it started and keep chatting. When a [HEAVY DONE] message arrives say its summary. "
    "For progress or tokens left call heavy_status. "
    "ACCESS: only Boss is in charge")

EDITS = [
    ("heavy tool code",
     "# ================= TOOL REGISTRY =================",
     HEAVY_BLOCK),
    ("heavy tool list",
     "TOOL_FUNCS = {f.__name__: f for f in FUNCS}",
     HEAVY_FUNCS),
    ("heavy tool declarations",
     'assert {f.__name__ for f in FUNCS} == {d.name for d in DECLS}, "Tool function/declaration mismatch"',
     HEAVY_DECLS),
    ("heavy rules in system prompt",
     "ACCESS: only Boss is in charge",
     HEAVY_PROMPT),
    ("heavy message tags",
     "[BOSS RECOGNIZED] or [WAKE] come from the system",
     "[BOSS RECOGNIZED], [WAKE], [HEAVY DONE] or [HEAVY FAILED] come from the system"),
    ("tell Boss when the heavy job ends",
     "if GUARD and silent > 3:",
     HEAVY_WATCH),
]


def main():
    src, dst = pick_files()
    if not src or not src.exists():
        print("Cannot find your live_voice file. Run this from the Guts_AI folder.")
        return
    if not (BASE / "heavy_brain.py").exists():
        print("Missing heavy_brain.py in this folder. Put it next to this patch first.")
        return
    text = src.read_text(encoding="utf-8")
    if "heavy_task" in text:
        print("This file already has the heavy brain. Nothing to do.")
        return
    for label, anchor, new in EDITS:
        n = text.count(anchor)
        if n != 1:
            print(f"STOPPED. Could not safely patch '{label}' (found {n} matches, need 1). Nothing was written.")
            print(f"Send me this message and your {src.name}.")
            return
        text = text.replace(anchor, new)
    compile(text, str(dst), "exec")          # syntax check before saving
    dst.write_text(text, encoding="utf-8")
    print(f"Done: {dst.name} created from {src.name} ({len(EDITS)} changes). {src.name} is untouched.")
    print(f"Next: put HEAVY_API_KEY and HEAVY_MODEL in .env, stop Guts, then  python {dst.name}")


if __name__ == "__main__":
    main()
