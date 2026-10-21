"""guts_brain.py - coding and research helper for Guts.

It tries several providers in order, so one running out of free quota does not stop Guts:
  1. Gemini (your SECOND key, GEMINI_WORK_KEY in .env)   - can also search the web
  2. Groq   (GROQ_API_KEY in .env, optional, free)       - no web search

Test it from PowerShell (in the Guts_AI folder):
  python guts_brain.py ping                 (tiny test: shows which provider answered)
  python guts_brain.py research "latest news about electric cars in India"
  python guts_brain.py code "simple calculator in python with a window"
  python guts_brain.py run                  (runs the LAST code that was written)
"""
import os
import re
import sys
import json
import time
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")
PROJECTS = BASE / "projects"          # every coding job gets its own NEW folder in here
LAST = PROJECTS / "_last.txt"         # remembers the file written last
client = genai.Client(api_key=os.getenv("GEMINI_WORK_KEY"))

# ---------------------------------------------------------------- settings
GEMINI_MODELS = [                     # best first; lite models are the safe fallback
    "gemini-flash-latest",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-flash-lite-latest",
]
GROQ_MODELS = [                       # model names change; if all fail, check console.groq.com for names
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "qwen/qwen3-32b",
    "llama-3.1-8b-instant",
]
COOLDOWN_QUOTA = 600                  # seconds to skip a provider after it said 429
COOLDOWN_OTHER = 60

CODE_SYSTEM = (
    "You are an expert programmer. Write complete, working, well-commented code for the request. "
    "Reply in exactly this format and nothing else:\n"
    "FILENAME: best_file_name.ext\n"
    "```\n<the full code>\n```"
)
RESEARCH_SYSTEM = (
    "You are a careful research assistant speaking to Boss out loud. Use the search tool for anything "
    "recent. Answer in simple Hinglish, under 120 words, with the key facts first. "
    "Say clearly if you are not sure."
)

# Words that make code risky. If any is found, run_code refuses unless Boss forces it.
DANGER = ["os.remove", "os.unlink", "os.rmdir", "rmtree", "send2trash", "shutil.move", "subprocess",
          "os.system", "eval(", "exec(", "__import__", "socket", "ctypes", "winreg", "requests.",
          "urllib", ".env", "os.environ"]

COOL = {}                             # "provider:search" -> time until which it is skipped


# ---------------------------------------------------------------- providers
def _gemini(prompt: str, system: str, search: bool) -> str:
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        tools=[types.Tool(google_search=types.GoogleSearch())] if search else None,
    )
    last = ""
    for model in GEMINI_MODELS:
        for attempt in range(2):
            try:
                r = client.models.generate_content(model=model, contents=prompt, config=cfg)
                if r.text:
                    print(f"[Brain] used gemini/{model}")
                    return r.text
            except Exception as e:
                msg = str(e)
                last = f"gemini/{model}: {msg[:90]}"
                print(f"[Brain] {last}")
                if "429" in msg or "404" in msg:
                    break                   # quota used up or model missing: next model now
                time.sleep(2)               # busy (503): wait and try once more
    raise RuntimeError(last or "gemini: no answer")


def _groq(prompt: str, system: str, search: bool) -> str:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("groq: no GROQ_API_KEY in .env")
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    last = ""
    for model in GROQ_MODELS:
        body = json.dumps({"model": model, "messages": msgs, "temperature": 0.3}).encode()
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions", data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "User-Agent": "guts-ai/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
            text = data["choices"][0]["message"]["content"] or ""
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
            if text:
                print(f"[Brain] used groq/{model}")
                return text
        except urllib.error.HTTPError as e:
            last = f"groq/{model}: {e.code} {e.read().decode(errors='ignore')[:80]}"
            print(f"[Brain] {last}")
        except Exception as e:
            last = f"groq/{model}: {str(e)[:90]}"
            print(f"[Brain] {last}")
    raise RuntimeError(last or "groq: no answer")


PROVIDERS = [("gemini", _gemini), ("groq", _groq)]


def _generate(prompt: str, system: str = None, search: bool = False) -> str:
    errors = []
    for name, fn in PROVIDERS:
        ck = f"{name}:{search}"
        if time.time() < COOL.get(ck, 0):
            errors.append(f"{name}: resting after a limit error")
            continue
        if name == "groq" and not os.getenv("GROQ_API_KEY"):
            continue
        try:
            text = fn(prompt, system, search)
            if text:
                return text
        except Exception as e:
            msg = str(e)
            errors.append(msg[:100])
            COOL[ck] = time.time() + (COOLDOWN_QUOTA if "429" in msg else COOLDOWN_OTHER)
    raise RuntimeError("All providers failed. " + " | ".join(errors))


# ---------------------------------------------------------------- tools
def research(question: str) -> str:
    """Search the web and answer. If web search is not possible, answer without it and say so."""
    try:
        return _generate(question, RESEARCH_SYSTEM, search=True)[:1500]
    except RuntimeError:
        note = (" Web search is not available right now, so answer from your own knowledge and say "
                "clearly that it may be outdated.")
        return _generate(question, RESEARCH_SYSTEM + note, search=False)[:1500]


def write_code(topic: str) -> str:
    """Write code for a topic, save it in a NEW folder under projects, and open it in VS Code."""
    text = _generate(f"Write code for: {topic}", CODE_SYSTEM)

    block = re.search(r"```[\w+#.-]*\n(.*?)```", text, re.S)
    code = (block.group(1) if block else text).strip() + "\n"

    found = re.search(r"FILENAME:\s*([\w.\-]+)", text)
    slug = re.sub(r"\W+", "_", topic.lower()).strip("_")[:30] or "project"
    name = Path(found.group(1)).name if found else slug + ".py"

    folder = PROJECTS / f"{slug}_{time.strftime('%H%M%S')}"   # new folder, so nothing is overwritten
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(code, encoding="utf-8")
    LAST.write_text(str(path), encoding="utf-8")

    try:
        subprocess.Popen(["code", str(path)], shell=True)       # VS Code command line
        opened = "opened in VS Code"
    except Exception:
        os.startfile(path)
        opened = "opened with the default app"
    return f"Code saved as {name} in projects\\{folder.name} and {opened}. Not run yet."


def check_code(path: Path) -> list:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [d for d in DANGER if d in text]


def run_code(force: bool = False) -> str:
    """Run ONLY the last code Guts wrote, and only if it lives inside the projects folder."""
    if not LAST.exists():
        return "No code has been written yet."
    path = Path(LAST.read_text(encoding="utf-8").strip()).resolve()
    if PROJECTS.resolve() not in path.parents or not path.exists():
        return "Blocked: I only run files inside the projects folder."
    if path.suffix.lower() != ".py":
        return f"I can only run .py files. {path.name} is open in VS Code for Boss to run."
    flags = check_code(path)
    if flags and not force:
        return ("NOT RUN. This code uses risky things: " + ", ".join(flags) +
                ". Tell Boss to read it in VS Code first.")
    flags_note = " (risky parts were allowed by Boss)" if flags else ""
    subprocess.Popen(["cmd", "/k", sys.executable, str(path)], cwd=str(path.parent),
                     creationflags=subprocess.CREATE_NEW_CONSOLE)   # own window, stays open to show errors
    return f"Running {path.name}{flags_note}."


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "ping":
        print("Keys found -> gemini:", bool(os.getenv("GEMINI_WORK_KEY")),
              "| groq:", bool(os.getenv("GROQ_API_KEY")))
        print("Answer:", _generate("Reply with just the word OK.", None, False)[:60])
    elif cmd == "run":
        print(run_code())
    elif cmd in ("research", "code") and len(sys.argv) > 2:
        text_in = " ".join(sys.argv[2:])
        print(research(text_in) if cmd == "research" else write_code(text_in))
    else:
        print(__doc__)
