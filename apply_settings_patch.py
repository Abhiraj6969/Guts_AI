"""apply_settings_patch.py - makes Guts personal: he reads guts_settings.json (one Boss per install).

What it changes in the Guts main file:
  - the user's name, language and personality are added to his instructions
  - FACE_LOCK and PROACTIVE come from the settings
  - with the calm or professional personality he is polite to visitors, never roasting
  - the face on the screen: he reports what he is doing (speaking, listening, working, sleeping) and his words,
    and a voice tool lets the owner rename him
The build script also uses the two helper functions below on staged copies of pc_tools.py (browser choice)
and face_guard.py (camera number), so your own pc_tools.py and face_guard.py are never touched.

Standalone use (optional, to try the settings on your own PC):
  python apply_settings_patch.py            newest live_voice_N.py -> next number, your file stays as backup
"""
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent


def _sub_one(text, pattern, repl, flags=re.M):
    pat = re.compile(pattern, flags)
    if len(pat.findall(text)) != 1:
        return text, False
    return pat.sub(lambda m: repl(m) if callable(repl) else repl, text, count=1), True


def _after_line(text, pattern, extra_lines):
    """Adds lines right after the ONE line that matches (same indentation + 4 if the line ends a block opener)."""
    pat = re.compile(pattern, re.M)
    found = pat.findall(text)
    if len(found) != 1:
        return text, False
    def add(m):
        indent = m.group(1)
        if m.group(0).rstrip().endswith(":"):
            indent += "    "
        return m.group(0) + "".join("\n" + indent + ln for ln in extra_lines)
    return pat.sub(add, text, count=1), True


AVATAR_NOTE = ("the face on the screen needs these hooks; each one that is missing only makes the face less lively, "
               "the OFF button always works")


def add_avatar(text: str):
    """Hooks that tell the face what Guts is doing, the bridge task, and the rename tool. All optional."""
    notes = []
    text, ok = _sub_one(text, r"^import guts_settings$", lambda m: m.group(0) +
                        "\nfrom guts_settings import set_assistant_name\nfrom guts_bridge import avatar_bridge")
    if not ok:
        return text, ["face: skipped (import line missing)"]
    text, ok = _after_line(text, r"^([ \t]*)if msg\.data:[ \t]*$", ['STATE["last_audio_out"] = time.time()'])
    notes.append("face speaking hook: " + ("yes" if ok else "skipped"))
    text, ok = _after_line(text, r'^([ \t]*)print\(f"\[Boss\]: \{t\}"\)[ \t]*$', ['STATE["last_user_speech"] = time.time()'])
    notes.append("face listening hook: " + ("yes" if ok else "skipped"))
    text, ok = _after_line(text, r'^([ \t]*)print\(f"\[Tool\]: .*\)[ \t]*$', ['STATE["last_tool"] = time.time()'])
    notes.append("face working hook: " + ("yes" if ok else "skipped"))
    text, ok = _after_line(text, r'^([ \t]*)print\(f"\[Guts\]: \{sc\.output_transcription\.text\}"\)[ \t]*$', [
        "_st = time.time()",
        'if _st - STATE.get("subtitle_t", 0) > 3: STATE["subtitle"] = ""',
        'STATE["subtitle"] = (STATE.get("subtitle", "") + sc.output_transcription.text)[-200:]',
        'STATE["subtitle_t"] = _st'])
    notes.append("face subtitle hook: " + ("yes" if ok else "skipped"))
    text, ok = _sub_one(text, r"^([ \t]*)tg\.create_task\(play_replies\(session\)\)[ \t]*$",
                        lambda m: m.group(0) + "\n" + m.group(1) + "tg.create_task(avatar_bridge(STATE))")
    notes.append("face state task: " + ("yes" if ok else "skipped (the face will always look idle)"))
    # the rename tool: both the list entry and the declaration, or neither
    lst = re.compile(r"(FUNCS = \[.*?)(\s*)\]\nTOOL_FUNCS", re.S)
    if len(lst.findall(text)) == 1 and text.count('decl("send_whatsapp",') == 1:
        text = lst.sub(lambda m: m.group(1) + ", set_assistant_name]\nTOOL_FUNCS", text, count=1)
        text = text.replace('decl("send_whatsapp",',
                            'decl("set_assistant_name", "Change the name of the assistant when the owner chooses a new name for him.",\n'
                            '         name="The new name, 2 to 20 letters"),\n    decl("send_whatsapp",', 1)
        notes.append("rename by voice: yes")
    else:
        notes.append("rename by voice: skipped (tool list not found; rename still works from the face's menu)")
    return text, notes


def patch_main(text: str):
    """Returns (new_text or None, notes). None = a REQUIRED anchor was missing, nothing was changed."""
    notes = []
    if "guts_settings" in text:
        return text, ["already patched"]
    text, ok = _sub_one(text, r"^from google\.genai import types$", lambda m: m.group(0) + "\nimport guts_settings")
    if not ok:
        return None, ["could not find 'from google.genai import types'"]
    text, ok = _sub_one(text, r"system_instruction=build_system\(\)",
                        "system_instruction=build_system() + guts_settings.prompt_addon()", flags=0)
    if not ok:
        return None, ["could not find 'system_instruction=build_system()'"]
    text, ok = _sub_one(text, r"^FACE_LOCK = True\b.*$", 'FACE_LOCK = guts_settings.get("face_lock", True)')
    notes.append("face lock setting: " + ("yes" if ok else "skipped (FACE_LOCK line not found)"))
    text, ok = _sub_one(text, r"^PROACTIVE = True\b.*$", 'PROACTIVE = guts_settings.get("proactive", True)')
    notes.append("proactive setting: " + ("yes" if ok else "skipped (PROACTIVE line not found)"))
    text, ok = _sub_one(
        text, r'polite = STATE\["visitor_mode"\] == "polite" and time\.time\(\) < STATE\["visitor_until"\]',
        'polite = (guts_settings.get("persona", "giga_chad") != "giga_chad") or '
        '(STATE["visitor_mode"] == "polite" and time.time() < STATE["visitor_until"])', flags=0)
    notes.append("polite visitors for calm/pro: " + ("yes" if ok else "skipped (visitor line not found)"))
    text, more = add_avatar(text)
    notes += more
    return text, notes


def patch_pc_tools(text: str):
    """The browser the person chose (settings) wins over the built-in Brave search."""
    if "guts_settings" in text:
        return text, ["already patched"]
    new, ok = _sub_one(text, r"^def find_brave\(\):\n", lambda m: (
        "def find_brave():\n"
        "    try:\n"
        "        import guts_settings\n"
        "        chosen = guts_settings.browser_path()\n"
        "        if chosen:\n"
        "            return chosen\n"
        "    except Exception:\n"
        "        pass\n"))
    return (new, ["browser choice: yes"]) if ok else (text, ["browser choice: skipped (find_brave not found)"])


def patch_face_guard(text: str):
    """The camera number from the settings."""
    if "_cam_from_settings" in text:
        return text, ["already patched"]
    new, ok = _sub_one(
        text, r'^CAMERA_INDEX = int\(os\.environ\.get\("GUTS_CAM", "0"\)\).*$',
        lambda m: ("def _cam_from_settings():\n"
                   "    try:\n"
                   "        import guts_settings\n"
                   "        return int(guts_settings.get(\"camera_index\", 0))\n"
                   "    except Exception:\n"
                   "        return 0\n\n\n"
                   "CAMERA_INDEX = int(os.environ.get(\"GUTS_CAM\", _cam_from_settings()))"))
    return (new, ["camera number: yes"]) if ok else (text, ["camera number: skipped (CAMERA_INDEX line not found)"])


def newest():
    nums = [int(m.group(1)) for p in BASE.glob("live_voice_*.py") if (m := re.fullmatch(r"live_voice_(\d+)\.py", p.name))]
    return max(nums) if nums else None


def main():
    if len(sys.argv) > 2:
        src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    else:
        n = newest()
        src = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / f"live_voice_{n}.py"
        m = re.fullmatch(r"live_voice_(\d+)\.py", src.name)
        dst = BASE / (f"live_voice_{int(m.group(1)) + 1}.py" if m else "live_voice_new.py")
    if not src.exists():
        print(f"Cannot find {src}. Run this from the Guts_AI folder.")
        return
    if not (BASE / "guts_settings.py").exists():
        print("guts_settings.py is missing. Put it in this folder first.")
        return
    new, notes = patch_main(src.read_text(encoding="utf-8"))
    if new is None:
        print("STOPPED:", "; ".join(notes), ". Nothing was written. Send me this message and your file.")
        return
    if new == src.read_text(encoding="utf-8"):
        print("Nothing to do:", "; ".join(notes))
        return
    compile(new, str(dst), "exec")
    dst.write_text(new, encoding="utf-8")
    print(f"Done: {dst.name} created from {src.name}. {src.name} is untouched.")
    for n in notes:
        print("  -", n)


if __name__ == "__main__":
    main()
