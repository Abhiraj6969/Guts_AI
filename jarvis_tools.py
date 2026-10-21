# jarvis_tools.py - JARVIS Hands for Guts
import os, subprocess, time
from pathlib import Path
import pyautogui
import psutil

def set_volume(level: str) -> str:
    try:
        level = int(level)
        level = max(0, min(100, level))
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMasterVolumeLevelScalar(level/100, None)
        return f"Volume set to {level}%"
    except Exception as e:
        return f"Volume error: {e} - Try: pip install pycaw comtypes"

def set_brightness(level: str) -> str:
    try:
        level = int(level)
        level = max(0, min(100, level))
        import screen_brightness_control as sbc
        sbc.set_brightness(level)
        return f"Brightness set to {level}%"
    except Exception as e:
        return f"Brightness error: {e} - Try: pip install screen-brightness-control"

def take_screenshot(name: str = "screenshot") -> str:
    try:
        path = Path.home() / "Desktop" / f"{name}_{time.strftime(\'%H%M%S\')}.png"
        pyautogui.screenshot(str(path))
        return f"Screenshot saved: {path}"
    except Exception as e:
        return f"Screenshot error: {e}"

def system_power(action: str) -> str:
    a = action.lower().strip()
    try:
        if a == "lock":
            subprocess.Popen("rundll32.exe user32.dll,LockWorkStation", shell=True)
            return "PC Locked"
        elif a == "sleep":
            subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
            return "Sleeping..."
        elif a == "shutdown":
            subprocess.Popen("shutdown /s /t 5", shell=True)
            return "Shutdown in 5 seconds"
        elif a == "restart":
            subprocess.Popen("shutdown /r /t 5", shell=True)
            return "Restart in 5 seconds"
        elif a == "mute":
            return set_volume("0")
        else:
            return "Unknown action. Use: lock, sleep, shutdown, restart, mute"
    except Exception as e:
        return f"System error: {e}"

def media_control(action: str) -> str:
    # Uses virtual keys - works for YouTube/Spotify/Brave
    keys = {"play_pause": "playpause", "next": "nexttrack", "prev": "prevtrack", "volume_up": "volumeup", "volume_down": "volumedown", "mute": "volumemute"}
    k = keys.get(action.lower().strip())
    if not k: return "Use: play_pause, next, prev, volume_up, volume_down, mute"
    pyautogui.press(k)
    return f"Media: {action} done"

def press_hotkey(keys: str) -> str:
    # e.g. "win+d", "alt+tab", "ctrl+c"
    try:
        pyautogui.hotkey(*[k.strip() for k in keys.split("+")])
        return f"Pressed {keys}"
    except Exception as e:
        return f"Hotkey error: {e}"

def type_text(text: str) -> str:
    try:
        pyautogui.typewrite(text, interval=0.02)
        return f"Typed: {text[:50]}"
    except Exception as e:
        return f"Type error: {e}"