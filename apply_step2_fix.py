"""apply_step2_fix.py - Patches live_voice_13.py to print full error tracebacks."""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
TARGET = BASE / "live_voice_13.py"

if not TARGET.exists():
    print("❌ live_voice_13.py file nahi mili!")
    sys.exit(1)

code = TARGET.read_text(encoding="utf-8")

# 1. Ensure import traceback exists
if "import traceback" not in code:
    code = "import traceback\n" + code

# 2. Add detailed traceback printing in exception blocks
if "traceback.print_exc()" not in code:
    code = code.replace(
        "except Exception as e:",
        "except Exception as e:\n        print('\\n❌ [Guts Debug] DETAILED TRACEBACK:')\n        traceback.print_exc()",
    )

TARGET.write_text(code, encoding="utf-8")
print("✅ Step 2 successfully applied to live_voice_13.py!")