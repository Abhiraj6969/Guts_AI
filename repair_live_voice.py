"""repair_live_voice.py - repairs two problems in your newest live_voice_N.py:

 1) a half-written duplicate line   decl("heavy_task"      (causes: ']' does not match '(')
 2) garbled Hindi text like  à¤¹à¤¾à¤  that should be  हाँ   (the file was saved with the wrong encoding;
    this breaks the Hindi yes/no words, the sleep phrase and similar)

It creates live_voice_(N+1).py and checks the syntax before saving.
Your broken file is NOT changed.

Run (in the Guts_AI folder):
  python repair_live_voice.py
or choose files yourself:
  python repair_live_voice.py live_voice_18.py live_voice_19.py
"""
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
MARKERS = ("à¤", "à¥", "Ã", "Â")   # what Devanagari looks like when UTF-8 bytes were read as Windows-1252
                                         # (the last two show up when it was damaged twice)


def pick_files():
    if len(sys.argv) > 2:
        return Path(sys.argv[1]), Path(sys.argv[2])
    nums = [int(m.group(1)) for f in BASE.glob("live_voice_*.py")
            if (m := re.fullmatch(r"live_voice_(\d+)\.py", f.name))]
    if not nums:
        return None, None
    n = max(nums)
    return BASE / f"live_voice_{n}.py", BASE / f"live_voice_{n + 1}.py"


def unmangle(line: str) -> str:
    """Undo 'UTF-8 read as Windows-1252' for one line. Returns the line unchanged if it cannot be undone."""
    raw = bytearray()
    for ch in line:
        try:
            raw += ch.encode("cp1252")
        except UnicodeEncodeError:
            if 0x80 <= ord(ch) <= 0x9F:          # bytes Windows-1252 leaves empty come through as control characters
                raw.append(ord(ch))
            else:
                return line
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return line


def main():
    src, dst = pick_files()
    if not src or not src.exists():
        print("Cannot find your live_voice file. Run this from the Guts_AI folder.")
        return
    text = src.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    report = []

    # 1) half-written duplicate declarations: decl("name"  with nothing after it
    kept = []
    for i, line in enumerate(lines, 1):
        if re.fullmatch(r'\s*decl\("[A-Za-z_]+"\s*', line):
            report.append(f"removed broken line {i}: {line.strip()}")
            continue
        kept.append(line)
    lines = kept

    # 2) garbled Hindi
    fixed = 0
    for i, line in enumerate(lines):
        for _ in range(3):                       # up to 3 rounds, in case it was damaged more than once
            if not any(m in line for m in MARKERS):
                break
            new = unmangle(line)
            still_marked = any(m in new for m in MARKERS)
            has_hindi = any("\u0900" <= c <= "\u097f" for c in new)
            if new == line or not (has_hindi or still_marked):
                break                            # not really garbled Hindi: leave the line alone
            line = new
        if line != lines[i]:
            fixed += 1
            lines[i] = line
    if fixed:
        report.append(f"repaired Hindi text on {fixed} line(s)")
    for n, l in enumerate(lines, 1):
        if any(m in l for m in MARKERS):
            report.append(f"NOTE: line {n} still has odd characters (maybe fine): "
                          f"{l.strip()[:60].encode('ascii', 'replace').decode()}")

    if not report:
        print("Nothing to repair in this file. The problem may be somewhere else.")
        print(f"Run:  python -c \"import ast,sys; ast.parse(open('{src.name}', encoding='utf-8').read())\"  and paste the error.")
        return

    new_text = "\n".join(lines)
    try:
        compile(new_text, str(dst), "exec")
    except SyntaxError as e:
        print(f"STOPPED. After the repair the file still has a syntax error: {e.msg} (line {e.lineno}).")
        print("Nothing was written. Send me this message and the lines around it.")
        return
    dst.write_text(new_text, encoding="utf-8")
    print("Repairs:")
    for r in report:
        print("  -", r)
    print(f"\nDone: {dst.name} created from {src.name}. {src.name} is untouched.")
    print(f"Next: python {dst.name}")


if __name__ == "__main__":
    main()
