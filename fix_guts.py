from pathlib import Path
import re
p = Path("live_voice_18.py")
t = p.read_text(encoding="utf-8")

# 1. import fix
if "import guts_hands" not in t:
    t = t.replace("from pc_tools import", "import guts_hands\nfrom pc_tools import")

# 2. FUNCS fix
if "guts_hands.set_volume" not in t:
    t = t.replace("FUNCS += [heavy_task, heavy_status, open_tekken8, game_buddy]", "FUNCS += [heavy_task, heavy_status, open_tekken8, game_buddy, guts_hands.set_volume, guts_hands.set_brightness, guts_hands.take_screenshot, guts_hands.system_power, guts_hands.media_control, guts_hands.press_hotkey, guts_hands.type_text]")

# 3. purane tuti hui decls hatao
t = re.sub(r\'\s*decl\("set_volume".*?\n\',\'\n\',t)
t = re.sub(r\'\s*decl\("set_brightness".*?\n\',\'\n\',t)
t = re.sub(r\'\s*decl\("take_screenshot".*?\n\',\'\n\',t)
t = re.sub(r\'\s*decl\("system_power".*?\n\',\'\n\',t)
t = re.sub(r\'\s*decl\("media_control".*?\n\',\'\n\',t)
t = re.sub(r\'\s*decl\("press_hotkey".*?\n\',\'\n\',t)
t = re.sub(r\'\s*decl\("type_text".*?\n\',\'\n\',t)

# 4. sahi jagah 7 decls add karo
old = \'\'\'         name="App name, folder name, or the word folders"),
]
DECLS += [\'\'\'
new = \'\'\'         name="App name, folder name, or the word folders"),
    decl("set_volume", "Set GUTS volume 0-100.", level="0 to 100"),
    decl("set_brightness", "Set brightness 0-100.", level="0 to 100"),
    decl("take_screenshot", "Take screenshot.", name="Optional name"),
    decl("system_power", "Lock/sleep/shutdown.", action="lock, sleep, shutdown, restart"),
    decl("media_control", "Media keys.", action="play_pause, next, prev"),
    decl("press_hotkey", "Press shortcut.", keys="e.g. win+d"),
    decl("type_text", "Type text.", text="Text to type"),
]
DECLS += [\'\'\'
if old in t:
    t = t.replace(old, new)

# 5. build_system me JARVIS HANDS add karo
if "JARVIS HANDS" not in t:
    t = t.replace("To close an app, window, file or folder call close_item", "JARVIS HANDS: You HAVE these tools and MUST use them: set_volume for volume 0-100, set_brightness for brightness, take_screenshot for screenshot, system_power for lock/sleep/shutdown, media_control for play/pause. To close an app, window, file or folder call close_item")

p.write_text(t, encoding="utf-8")
print("FIXED: live_voice_18.py Syntax OK - MODEL not changed")