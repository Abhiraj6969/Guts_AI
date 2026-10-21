"""test_rshift.py - checks that Python can see your RIGHT Shift key (needed by the calibration).
Run:  python test_rshift.py     then tap the RIGHT Shift key (the one near the arrow keys).
"""
import time
import ctypes

VK_RSHIFT = 0xA1
print("You have 10 seconds. Tap the RIGHT Shift key now ...")
t0 = time.time()
seen = False
while time.time() - t0 < 10 and not seen:
    if ctypes.windll.user32.GetAsyncKeyState(VK_RSHIFT) & 0x8000:
        seen = True
    time.sleep(0.02)
print("RIGHT SHIFT DETECTED. The key works." if seen else
      "NOT detected. Try: a different terminal, run PowerShell as Administrator, or use the countdown method.")
