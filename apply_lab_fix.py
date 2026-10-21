"""apply_lab_fix.py - stops the "server busy" errors when Guts plans a Packet Tracer lab.

Problem in pt_lab.py: it asked ONE Gemini model, with the voice key, and gave up on the first 503.
Fix: pt_lab.py now asks guts_brain.py, which uses your second key, tries 4 Gemini models,
rests a provider after a 429, and falls back to Groq if you added GROQ_API_KEY.

It edits pt_lab.py in place and saves a copy first as pt_lab_backup.py.

Run (in the Guts_AI folder):
  python apply_lab_fix.py
"""
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "pt_lab.py"

NEW_ASK = r'''def _json_from(text: str) -> dict:
    """Finds the JSON object in a reply, even when it comes wrapped in text or code fences."""
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("the reply had no JSON object")
    return json.loads(text[a:b + 1])


def ask_gemini(request: str, previous: dict = None, problems: list = None) -> dict:
    """Asks the shared brain (guts_brain.py): second Gemini key with model fallback, then Groq."""
    import guts_brain
    prompt = request
    if previous and problems:
        clean = {k: v for k, v in previous.items() if not k.startswith("_")}
        prompt = (f"Request: {request}\n\nYour previous plan:\n{json.dumps(clean)}\n\n"
                  "A checker found these problems. Fix ALL of them and return the complete corrected JSON:\n- "
                  + "\n- ".join(problems))
    system = SYSTEM_PROMPT + "\nReply with ONE JSON object only. No text before or after it."
    return _json_from(guts_brain._generate(prompt, system, False))'''

NEW_MAKE = r'''def make_lab(request: str) -> dict:
    """The brain plans, the checker verifies, up to MAX_TRIES rounds."""
    spec, problems, result = None, None, None
    for attempt in range(1, MAX_TRIES + 1):
        print(f"[Lab] Planning (try {attempt}/{MAX_TRIES}) ...")
        try:
            new = ask_gemini(request, spec, problems)
        except RuntimeError as e:          # every provider is busy or out of quota
            return {"ok": False, "errors": [str(e)[:300]], "warnings": [], "spec": spec or {}}
        except ValueError as e:            # includes unreadable JSON
            problems = [f"Your last reply could not be read ({e}). Reply with ONE valid JSON object only."]
            print("[Lab] Unreadable reply, asking again ...")
            continue
        spec = new
        result = build(spec)
        if result["ok"]:
            return result
        problems = result["errors"]
        print(f"[Lab] Checker found {len(problems)} problem(s), asking for a fix:")
        for p in problems[:6]:
            print("   -", p)
    return result or {"ok": False, "errors": problems or ["no plan was made"], "warnings": [], "spec": spec or {}}'''


def main():
    if not SRC.exists():
        print(f"Cannot find {SRC}. Run this from the Guts_AI folder.")
        return
    text = SRC.read_text(encoding="utf-8")
    if "_json_from" in text:
        print("pt_lab.py already has this fix. Nothing to do.")
        return

    a = text.find("def _api_key():")
    b = text.find("# ================= DEMO PLANS")
    c = text.find("def make_lab(request: str) -> dict:")
    d = text.find("def report(result: dict):")
    if not (0 <= a < b < c < d):
        print("STOPPED. pt_lab.py looks different from what I expected. Nothing was changed.")
        print("Send me this message and your pt_lab.py.")
        return

    new = text[:a] + NEW_ASK + "\n\n\n" + text[b:c] + NEW_MAKE + "\n\n\n" + text[d:]
    compile(new, str(SRC), "exec")                       # syntax check before saving
    shutil.copy2(SRC, BASE / "pt_lab_backup.py")
    SRC.write_text(new, encoding="utf-8")
    print("Done: pt_lab.py updated. Backup: pt_lab_backup.py")
    print("Next: restart Guts, or test with   python pt_lab.py \"2 routers with OSPF and 1 PC on each LAN\"")


if __name__ == "__main__":
    main()
