"""apply_guts_patch.py - adds research, write_code and run_code to Guts.

It reads live_voice_3.py and creates a NEW file live_voice_4.py.
Your live_voice_3.py is NOT changed, so it stays as your backup.

Run (in the Guts_AI folder):
  python apply_guts_patch.py
"""
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "live_voice_3.py"
DST = Path(sys.argv[2]) if len(sys.argv) > 2 else BASE / "live_voice_4.py"
BRAIN = BASE / "guts_brain.py"

# ---------------------------------------------------------------- the new tools
NEW_TOOLS = r'''# ================= CODING AND RESEARCH (second Gemini key, see guts_brain.py) =================
def research(question: str) -> str:
    """Web research using the second Gemini key."""
    try:
        return guts_brain.research(question)
    except Exception as e:
        return f"Research failed: {e}"


def write_code(topic: str) -> str:
    """Write code into a NEW folder under projects and open it in VS Code. Does NOT run it."""
    try:
        return guts_brain.write_code(topic)
    except Exception as e:
        return f"Code writing failed: {e}"


def _run_code_forced() -> str:
    return guts_brain.run_code(force=True)


def run_code() -> str:
    """Run the last code that was written. Clean code runs now; risky code needs Boss's spoken yes."""
    try:
        result = guts_brain.run_code()
        if not result.startswith("NOT RUN"):
            return result
        path = Path(guts_brain.LAST.read_text(encoding="utf-8").strip())
        flags = guts_brain.check_code(path)
        return _ask(f"run {path.name} even though it uses risky things: {', '.join(flags)}. "
                    "Boss should have read the code in VS Code first", _run_code_forced)
    except Exception as e:
        return f"Run failed: {e}"


# ================= TOOL REGISTRY ================='''

NEW_DECLS = r'''"List the names of saved WhatsApp contacts (numbers are never shown)."),
    decl("research", "Research a question on the web and get a short answer. Use for news, facts, comparisons.",
         question="The question or topic to research"),
    decl("write_code", "Write code for a topic. Saves it in a new folder and opens it in VS Code. Does not run it.",
         topic="What the code should do, e.g. simple calculator in python with a window"),
    decl("run_code", "Run the last code that was written. Risky code needs Boss's spoken yes."),'''

NEW_PROMPT = r'''"When Boss tells you something personal worth keeping, call remember. "
        "CODING: when Boss asks you to write or make code or a program, call write_code with the topic. "
        "It saves the code and opens VS Code. Tell him to read it and do NOT say it has run. "
        "When Boss says run, call run_code. If it returns PENDING, say the risky words and ask yes or no. "
        "For anything needing research or the latest news, call research and answer from its result. "'''

EDITS = [
    ("import guts_brain",
     "file_info, search_files, run_program_now)",
     "file_info, search_files, run_program_now)\n\nimport guts_brain"),
    ("protect the Guts files",
     'PROTECTED_NAMES = {".env", "guts_user_profile.json", "contacts.json", "pc_tools.py"}',
     'PROTECTED_NAMES = {".env", "guts_user_profile.json", "contacts.json", "pc_tools.py", '
     '"guts_brain.py", "face_guard.py"}'),
    ("new tool functions",
     "# ================= TOOL REGISTRY =================",
     NEW_TOOLS),
    ("function list",
     "play_youtube, set_visitor_mode]",
     "play_youtube, set_visitor_mode,\n         research, write_code, run_code]"),
    ("tool declarations",
     '"List the names of saved WhatsApp contacts (numbers are never shown)."),',
     NEW_DECLS),
    ("system prompt",
     '"When Boss tells you something personal worth keeping, call remember. "',
     NEW_PROMPT),
]


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run this from the Guts_AI folder.")
        return
    text = SRC.read_text(encoding="utf-8")
    if "guts_brain" in text:
        print("This file already has the coding tools. Nothing to do.")
        return

    for label, anchor, new in EDITS:
        n = text.count(anchor)
        if n != 1:
            print(f"STOPPED. Could not safely patch '{label}' (found {n} matches, need 1).")
            print("Nothing was written. Send me this message and your live_voice_3.py.")
            return
        text = text.replace(anchor, new)

    compile(text, str(DST), "exec")          # syntax check before saving
    DST.write_text(text, encoding="utf-8")
    print(f"Done: {DST.name} created ({len(EDITS)} changes). {SRC.name} is untouched.")

    # make guts_brain.py always read the .env from its own folder (needed for auto-start later)
    if BRAIN.exists():
        b = BRAIN.read_text(encoding="utf-8")
        old = "load_dotenv()\nBASE = Path(__file__).resolve().parent"
        if b.count(old) == 1:
            shutil.copy2(BRAIN, BASE / "guts_brain_backup.py")
            b = b.replace(old, 'BASE = Path(__file__).resolve().parent\nload_dotenv(BASE / ".env")')
            BRAIN.write_text(b, encoding="utf-8")
            print("guts_brain.py updated (backup: guts_brain_backup.py).")
        else:
            print("guts_brain.py needs no change.")
    else:
        print("WARNING: guts_brain.py is not in this folder. Put it here before running Guts.")


if __name__ == "__main__":
    main()
