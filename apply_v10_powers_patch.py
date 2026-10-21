"""apply_v10_powers_patch.py - Upgrades live_voice_9.py to live_voice_10.py with RAM analysis, detailed specs, and WhatsApp reader."""

from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "live_voice_9.py"
DST = BASE / "live_voice_10.py"

IMPORTS_BLOCK = """
# Extended Guts Powers
try:
    from guts_sysinfo import get_top_ram_consuming_apps, get_detailed_system_specs
    from guts_whatsapp import read_latest_whatsapp_messages
    HAS_SUPER_POWERS = True
except ImportError:
    HAS_SUPER_POWERS = False
"""

TOOLS_REGISTER = "tools=[update_user_profile, execute_ui_sequence, terminal_tool, get_system_status, get_top_ram_consuming_apps, get_detailed_system_specs, read_latest_whatsapp_messages, close_item, list_open_windows, close_all_apps, force_close],"

SYSTEM_PROMPT_ADDITION = """
5. SYSTEM & RAM DIAGNOSTICS: Use `get_top_ram_consuming_apps` to tell Boss exactly which apps are consuming RAM in GB/MB. Use `get_detailed_system_specs` for full hardware stats.
6. WHATSAPP READING: Use `read_latest_whatsapp_messages` when Boss asks to read or check WhatsApp messages, then summarize and speak them clearly in Hinglish.
"""

def main():
    if not SRC.exists():
        print(f"Cannot find {SRC.name}! Make sure live_voice_9.py exists in Guts_AI folder.")
        return

    text = SRC.read_text(encoding="utf-8")

    if "get_top_ram_consuming_apps" in text:
        print("live_voice_9.py already has super powers attached!")
        return

    # Add imports
    text = IMPORTS_BLOCK + "\n" + text

    # Add tools to Gemini configuration
    if "tools=[" in text:
        text = text.replace("tools=[", "tools=[get_top_ram_consuming_apps, get_detailed_system_specs, read_latest_whatsapp_messages, ", 1)

    # Enhance system instruction prompt
    if "=== CORE PERSONALITY & RULES ===" in text:
        text = text.replace("=== CORE PERSONALITY & RULES ===", "=== CORE PERSONALITY & RULES ===" + SYSTEM_PROMPT_ADDITION)

    DST.write_text(text, encoding="utf-8")
    print(f"✅ Success! Created {DST.name} from {SRC.name}.")
    print("🚀 Run command: python live_voice_10.py")

if __name__ == "__main__":
    main()