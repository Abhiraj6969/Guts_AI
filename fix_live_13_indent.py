"""fix_live_13_indent.py - Corrects all indentation errors in live_voice_13.py automatically."""

import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
TARGET = BASE / "live_voice_13.py"

if not TARGET.exists():
    print("❌ live_voice_13.py not found!")
    exit()

content = TARGET.read_text(encoding="utf-8")

# Clean up broken/mismatched debug prints first
content = re.sub(r"^\s*print\('\\n❌ \[Guts Debug\].*?\n", "", content, flags=re.M)
content = re.sub(r"^\s*traceback\.print_exc\(\)\n", "", content, flags=re.M)

lines = content.splitlines()
new_lines = []

if not any("import traceback" in line for line in lines[:30]):
    new_lines.append("import traceback")

for line in lines:
    new_lines.append(line)
    # Match any except block and auto-calculate its exact indentation level
    match = re.match(r"^(\s*)except\s+(?:Exception|BaseException).*?:", line)
    if match:
        base_indent = match.group(1)
        body_indent = base_indent + "    "  # Exactly 4 spaces more than 'except'
        new_lines.append(f"{body_indent}print('\\n❌ [Guts Debug] DETAILED TRACEBACK:')")
        new_lines.append(f"{body_indent}traceback.print_exc()")

TARGET.write_text("\n".join(new_lines), encoding="utf-8")
print("✅ Indentation fixed cleanly in live_voice_13.py!")