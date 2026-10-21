import time
import pyautogui
import pyperclip
import pygetwindow as gw

def focus_whatsapp() -> bool:
    """Finds and brings WhatsApp Desktop / Web window to focus."""
    windows = gw.getWindowsWithTitle('WhatsApp')
    if windows:
        win = windows[0]
        if win.isMinimized:
            win.restore()
        win.activate()
        time.sleep(0.5)
        return True
    return False

def read_latest_whatsapp_messages() -> str:
    """Focuses WhatsApp, selects active conversation text via clipboard, and returns it for reading out loud."""
    try:
        if not focus_whatsapp():
            return "Boss, WhatsApp window nahi mili. Kripya pehle WhatsApp launch karein."

        # Focus message area and copy recent text using clipboard automation
        # Click near center-right of window (chat screen)
        win = gw.getWindowsWithTitle('WhatsApp')[0]
        chat_x = win.left + int(win.width * 0.6)
        chat_y = win.top + int(win.height * 0.5)
        
        pyautogui.click(chat_x, chat_y)
        time.sleep(0.3)
        
        # Select recent text via Ctrl+A & Ctrl+C safely or drag select
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'c')
        time.sleep(0.3)
        
        copied_text = pyperclip.paste().strip()
        
        # Deselect by clicking again
        pyautogui.click(chat_x, chat_y)
        
        if not copied_text:
            return "WhatsApp khula hai par koi message text read nahi ho paya, Boss."
            
        # Get last 400 characters to avoid huge walls of text
        recent_snippet = copied_text[-400:].strip()
        return f"Recent WhatsApp Messages:\n{recent_snippet}"
    except Exception as e:
        return f"Error reading WhatsApp messages: {str(e)}"