"""patch_pt_send.py - Patches pt_send.py to do direct paste without failing on clipboard read-back."""

from pathlib import Path

BASE = Path(__file__).resolve().parent
PT_SEND_FILE = BASE / "pt_send.py"

if not PT_SEND_FILE.exists():
    print("❌ pt_send.py not found!")
    exit()

text = PT_SEND_FILE.read_text(encoding="utf-8")

# Replace _paste_verified logic with direct paste logic
OLD_PASTE_LOGIC = """def _paste_verified(cal: dict, script: str) -> str:"""

NEW_PASTE_LOGIC = """def _paste_verified(cal: dict, script: str) -> str:
    import pyautogui
    _copy(script)
    _click(cal, "editor")
    time.sleep(0.5)
    _combo("ctrl", "a")
    pyautogui.press("delete")
    time.sleep(0.3)
    log("pasting script via Ctrl+V ...")
    _combo("ctrl", "v")
    time.sleep(0.8)
    return "Ctrl+V (Direct)"
"""

if "def _paste_verified" in text:
    # Find start and end of function
    start_idx = text.find("def _paste_verified")
    end_idx = text.find("def _wait_for_window", start_idx)
    
    if start_idx != -1 and end_idx != -1:
        text = text[:start_idx] + NEW_PASTE_LOGIC + "\n\n" + text[end_idx:]
        PT_SEND_FILE.write_text(text, encoding="utf-8")
        print("✅ Successfully patched pt_send.py for direct pasting!")
    else:
        print("⚠️ Could not locate function bounds, please check file.")
else:
    print("⚠️ Function _paste_verified already updated or missing.")