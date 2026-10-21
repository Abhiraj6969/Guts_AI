from pathlib import Path
SRC = Path("live_voice_17.py")
DST = Path("live_voice_18.py")
if not SRC.exists():
    print("ERROR: live_voice_17.py nahi mila")
    exit()
text = SRC.read_text(encoding="utf-8")

# MODEL KO TOUCH NAHI KARENGE - jaisa hai waisa rahega

if "import guts_hands" not in text:
    text = text.replace("from pc_tools import", "import guts_hands\nfrom pc_tools import")

if "guts_hands.set_volume" not in text:
    text = text.replace("FUNCS += [heavy_task, heavy_status, open_tekken8, game_buddy]", "FUNCS += [heavy_task, heavy_status, open_tekken8, game_buddy, guts_hands.set_volume, guts_hands.set_brightness, guts_hands.take_screenshot, guts_hands.system_power, guts_hands.media_control, guts_hands.press_hotkey, guts_hands.type_text]")

if \'"set_volume"\' not in text:
    text = text.replace(\'    decl("heavy_task"\', \'    decl("set_volume", "Set GUTS volume 0-100.", level="0 to 100"),\n    decl("set_brightness", "Set brightness 0-100.", level="0 to 100"),\n    decl("take_screenshot", "Take screenshot.", name="Optional name"),\n    decl("system_power", "Lock/sleep/shutdown.", action="lock, sleep, shutdown, restart"),\n    decl("media_control", "Media keys.", action="play_pause, next, prev"),\n    decl("press_hotkey", "Press shortcut.", keys="e.g. win+d"),\n    decl("type_text", "Type text.", text="Text to type"),\n    decl("heavy_task"\')

DST.write_text(text, encoding="utf-8")
print("SUCCESS: live_voice_18.py ban gaya - MODEL same hai: gemini-3.8-live")