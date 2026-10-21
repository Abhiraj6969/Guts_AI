"""fix_fstring_quotes.py - fixes this Python 3.11 error in a Guts file:

    SyntaxError: f-string expression part cannot include a backslash
    path = ... f"{name}_{time.strftime(\\'%H%M%S\\')}.png"

The file was written with its quotes escaped (\\' and \\"). In Python 3.11 that is not allowed
inside the { } of an f-string. This removes the backslashes ONLY inside f-strings, so normal text
like 'it\\'s' is not touched.

It also checks every .py file in the folder and lists the ones that still have a syntax error.

Run (in the Guts_AI folder), with the same Python you use for Guts:
  python fix_fstring_quotes.py                 fixes guts_hands.py
  python fix_fstring_quotes.py other_file.py   fixes the file(s) you name
A backup is saved as <file>.bak before anything is changed.
"""
import re
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

DQ_FSTRING = re.compile(r'\b([fF][rR]?|[rR][fF])"((?:[^"\\\n]|\\.)*)"')    # f"...."
SQ_FSTRING = re.compile(r"\b([fF][rR]?|[rR][fF])'((?:[^'\\\n]|\\.)*)'")    # f'....'


def fix_text(text: str):
    """Returns (new_text, number_of_changed_lines)."""
    out, changed = [], 0
    for line in text.split("\n"):
        new = line
        if "\\" in new and 'f"' in new.lower().replace("rf", "f"):
            new = DQ_FSTRING.sub(lambda m: f'{m.group(1)}"{m.group(2).replace(chr(92) + chr(39), chr(39))}"', new)
        if "\\" in new and "f'" in new.lower().replace("rf", "f"):
            new = SQ_FSTRING.sub(lambda m: f"{m.group(1)}'{m.group(2).replace(chr(92) + chr(34), chr(34))}'", new)
        if new != line:
            changed += 1
        out.append(new)
    return "\n".join(out), changed


def check(path: Path):
    """None if the file compiles, else a short message."""
    try:
        compile(path.read_text(encoding="utf-8", errors="replace"), str(path), "exec")
        return None
    except SyntaxError as e:
        return f"line {e.lineno}: {e.msg}"


def fix_file(path: Path) -> bool:
    if not path.exists():
        print(f"- {path.name}: file not found in this folder.")
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    new, changed = fix_text(text)
    if not changed:
        print(f"- {path.name}: no escaped quotes found inside f-strings.")
        problem = check(path)
        print(f"  still has an error ({problem})." if problem else "  syntax is fine.")
        return not problem
    try:
        compile(new, str(path), "exec")
    except SyntaxError as e:
        print(f"- {path.name}: changed {changed} line(s) but the file still has an error: "
              f"line {e.lineno}: {e.msg}. NOTHING was written.")
        bad = new.split("\n")[e.lineno - 1] if e.lineno else ""
        print(f"  that line: {bad.strip()[:150]}")
        return False
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
    path.write_text(new, encoding="utf-8")
    print(f"- {path.name}: fixed {changed} line(s). Backup: {bak.name}")
    return True


def main():
    targets = [Path(a) if Path(a).is_absolute() else BASE / a for a in sys.argv[1:]] or [BASE / "guts_hands.py"]
    print(f"Python {sys.version.split()[0]}\n")
    for t in targets:
        fix_file(t)
    print("\nChecking every .py file in this folder:")
    bad = 0
    for f in sorted(BASE.glob("*.py")):
        problem = check(f)
        if problem:
            bad += 1
            print(f"  PROBLEM  {f.name}: {problem}")
    print("  all files compile." if not bad else f"\n{bad} file(s) still have a problem. Paste the lines above to me.")


if __name__ == "__main__":
    main()
