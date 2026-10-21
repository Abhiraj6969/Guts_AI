"""heavy_brain.py - Guts uses a SECOND api key ONLY for heavy tech work and important work.

Normal talking stays on Guts's voice key. This key is used only when Guts calls heavy_task
(big code, debugging, system design, deep analysis, long research, important documents).

Put these in your .env file (never paste the key in a chat):
  HEAVY_API_KEY=your_key_here
  HEAVY_MODEL=model_name             (see: python heavy_brain.py models)
  HEAVY_BUDGET=1000000               (optional, total tokens you have)
  HEAVY_DAILY_CAP=150000             (optional, max tokens per day, so one bad day cannot burn everything)
  HEAVY_PROVIDER=                    (optional, only if the key is not recognised)
  HEAVY_BASE_URL=                    (optional, for other OpenAI-compatible services)

Test without Guts:
  python heavy_brain.py models       list the models your key can use
  python heavy_brain.py usage        tokens used so far
  python heavy_brain.py ask "your question"
"""
import os
import re
import sys
import json
import time
import threading
import urllib.error
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
USAGE_FILE = BASE / "heavy_usage.json"
OUT_DIR = BASE / "projects" / "heavy"
HOME = Path.home()

KINDS = ("code", "debug", "architecture", "research", "analysis", "planning", "document")
MAX_OUT_DEFAULT = 8000
MAX_FILE_CHARS = 60000
TEXT_EXT = {".txt", ".md", ".py", ".json", ".csv", ".log", ".html", ".css", ".js", ".java", ".c", ".cpp",
            ".xml", ".ini", ".yaml", ".yml", ".ts", ".tsx", ".jsx", ".sql", ".sh", ".bat", ".ps1"}
SECRET_HINTS = (".env", "id_rsa", ".pem", ".key", "secret", "password", "credential", "token")

PROVIDERS = {   # key prefix -> (provider, api style, base url, default model or None)
    "sk-ant-": ("anthropic", "anthropic", "https://api.anthropic.com", "claude-sonnet-5-5"),
    "AIza": ("gemini", "gemini", "https://generativelanguage.googleapis.com", "gemini-3-flash-preview"),
    "sk-or-": ("openrouter", "openai", "https://openrouter.ai/api/v1", None),
    "gsk_": ("groq", "openai", "https://api.groq.com/openai/v1", None),
    "xai-": ("xai", "openai", "https://api.x.ai/v1", None),
    "sk-": ("openai", "openai", "https://api.openai.com/v1", None),
}
NAMED = {"anthropic": PROVIDERS["sk-ant-"], "gemini": PROVIDERS["AIza"], "openrouter": PROVIDERS["sk-or-"],
         "groq": PROVIDERS["gsk_"], "xai": PROVIDERS["xai-"], "openai": PROVIDERS["sk-"]}

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0.0.0 Safari/537.36")   # many sites block Python's default signature (Cloudflare 1010)

JOB = {"state": "idle", "msg": "", "summary": "", "file": None, "t0": 0.0}
_LOCK = threading.Lock()

SYSTEM = (
    "You are the heavy-duty technical brain of Guts, the PC assistant of Boss, a first-year BSc IT student who "
    "likes cybersecurity, coding and building tech projects. Do the task properly: correct, complete, step by step. "
    "When code is asked, give complete working code with the file name and how to run it. When you are unsure, say so. "
    "FORMAT: the very first line must be 'SUMMARY:' followed by 2 short sentences in simple Hinglish that Guts can "
    "read aloud. Then a blank line, then the full answer in clear English with simple headings."
)


# ================= config =================
def _cfg() -> dict:
    key = (os.environ.get("HEAVY_API_KEY") or "").strip()
    if not key:
        return {}
    prov = (os.environ.get("HEAVY_PROVIDER") or "").strip().lower()
    entry = NAMED.get(prov)
    if not entry:
        entry = next((v for pre, v in PROVIDERS.items() if key.startswith(pre)), None)
    base_override = (os.environ.get("HEAVY_BASE_URL") or "").strip().rstrip("/")
    if not entry:
        if not base_override:
            return {"key": key, "error": "Key type not recognised. Set HEAVY_PROVIDER (anthropic, gemini, openai, "
                                         "openrouter, groq, xai) or HEAVY_BASE_URL in .env."}
        entry = ("custom", "openai", base_override, None)
    name, style, base, default_model = entry
    base = base_override or base
    if style == "anthropic" and base.endswith("/v1"):
        base = base[:-3]                       # this style adds /v1/... itself
    return {"key": key, "provider": name, "style": style, "base": base,
            "model": (os.environ.get("HEAVY_MODEL") or "").strip() or default_model,
            "budget": int(os.environ.get("HEAVY_BUDGET") or 1_000_000),
            "daily": int(os.environ.get("HEAVY_DAILY_CAP") or 150_000)}


def _mask(text: str, key: str) -> str:
    return text.replace(key, "***") if key else text


# ================= http =================
def _err_text(raw: str) -> str:
    try:
        j = json.loads(raw)
        e = j.get("error", j)
        if isinstance(e, dict):
            return str(e.get("message") or e)[:300]
        return str(e)[:300]
    except Exception:
        return raw[:200]


def _http(url: str, headers: dict, body=None, timeout: int = 240):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, **headers},
                                 method="POST" if body is not None else "GET")
    last = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = _err_text(e.read().decode("utf-8", "replace"))
            if e.code in (429, 500, 502, 503, 529) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                last = f"HTTP {e.code}: {msg}"
                continue
            hint = " (the key was rejected)" if e.code in (401, 403) else (" (model name not found: run python heavy_brain.py models)" if e.code == 404 else "")
            host = urllib.request.urlparse(url).netloc if hasattr(urllib.request, "urlparse") else url.split("/")[2]
            raise RuntimeError(f"HTTP {e.code} from {host}: {msg}{hint}")
        except urllib.error.URLError as e:
            last = f"Network error: {e.reason}"
            if attempt < 2:
                time.sleep(3)
                continue
            raise RuntimeError(last)
    raise RuntimeError(last or "request failed")


def _headers(cfg: dict) -> dict:
    if cfg["style"] == "anthropic":
        h = {"x-api-key": cfg["key"], "anthropic-version": "2023-06-01"}
        if "api.anthropic.com" not in cfg["base"]:
            h["Authorization"] = f"Bearer {cfg['key']}"
        return h
    if cfg["style"] == "gemini":
        return {"x-goog-api-key": cfg["key"]}
    return {"Authorization": f"Bearer {cfg['key']}"}


def list_models() -> list:
    cfg = _cfg()
    if not cfg or "error" in cfg:
        raise RuntimeError((cfg or {}).get("error", "No HEAVY_API_KEY in .env"))
    h = _headers(cfg)
    if cfg["style"] == "anthropic":
        j = _http(f"{cfg['base']}/v1/models?limit=100", h)
        return [m["id"] for m in j.get("data", [])]
    if cfg["style"] == "gemini":
        j = _http(f"{cfg['base']}/v1beta/models?pageSize=200", h)
        return [m["name"].split("/", 1)[-1] for m in j.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])]
    j = _http(f"{cfg['base']}/models", h)
    return [m["id"] for m in j.get("data", [])]


def call_llm(cfg: dict, prompt: str, max_out: int = MAX_OUT_DEFAULT):
    """One request. Returns (text, tokens_in, tokens_out)."""
    h, model = _headers(cfg), cfg["model"]
    if cfg["style"] == "anthropic":
        j = _http(f"{cfg['base']}/v1/messages", h, {"model": model, "max_tokens": max_out, "system": SYSTEM,
                                                    "messages": [{"role": "user", "content": prompt}]})
        text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        u = j.get("usage", {})
        return text, int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))
    if cfg["style"] == "gemini":
        j = _http(f"{cfg['base']}/v1beta/models/{model}:generateContent", h, {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_out}})
        parts = (j.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        u = j.get("usageMetadata", {})
        tin = int(u.get("promptTokenCount", 0))
        return text, tin, max(0, int(u.get("totalTokenCount", tin)) - tin)
    limit_key = "max_completion_tokens" if cfg["provider"] == "openai" else "max_tokens"
    j = _http(f"{cfg['base']}/chat/completions", h, {
        "model": model, limit_key: max_out,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]})
    text = ((j.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    u = j.get("usage", {})
    return text, int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))


# ================= budget =================
def _load_usage() -> dict:
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"used": 0, "days": {}, "log": []}


def _save_usage(u: dict):
    USAGE_FILE.write_text(json.dumps(u, indent=2), encoding="utf-8")


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def usage_summary(cfg=None) -> str:
    cfg = cfg or _cfg() or {}
    budget = cfg.get("budget", 1_000_000)
    daily = cfg.get("daily", 150_000)
    u = _load_usage()
    today = u["days"].get(_today(), 0)
    return (f"Heavy brain tokens used: {u['used']:,} of {budget:,} ({u['used'] * 100 // max(1, budget)}%). "
            f"Today: {today:,} of {daily:,}. Left: {max(0, budget - u['used']):,}.")


def _check_budget(cfg: dict, est_in: int, max_out: int):
    u = _load_usage()
    reserve = est_in + max_out
    if u["used"] + reserve > cfg["budget"] * 0.97:
        return "The heavy token budget is almost finished, so I stopped. " + usage_summary(cfg)
    if u["days"].get(_today(), 0) + reserve > cfg["daily"]:
        return ("Today's heavy limit is reached. " + usage_summary(cfg) +
                " Boss can raise HEAVY_DAILY_CAP in the .env file if this is important.")
    return ""


def _record(cfg: dict, kind: str, tin: int, tout: int):
    u = _load_usage()
    total = tin + tout
    u["used"] += total
    u["days"][_today()] = u["days"].get(_today(), 0) + total
    u["log"] = (u.get("log", []) + [{"time": time.strftime("%Y-%m-%d %H:%M"), "kind": kind, "in": tin,
                                      "out": tout, "model": cfg["model"]}])[-60:]
    _save_usage(u)
    return total


# ================= file context =================
def _read_context(file_path: str):
    p = Path(os.path.expandvars(file_path)).expanduser().resolve()
    if HOME not in p.parents and p != HOME and BASE not in p.parents:
        raise RuntimeError("Only files inside Boss's user folder can be sent.")
    low = p.name.lower()
    if any(h in low for h in SECRET_HINTS):
        raise RuntimeError("That file looks like it holds secrets, so it is not sent.")
    if not p.is_file() or p.suffix.lower() not in TEXT_EXT:
        raise RuntimeError("Only text or code files can be sent.")
    txt = p.read_text(encoding="utf-8", errors="ignore")
    cut = len(txt) > MAX_FILE_CHARS
    return p.name, txt[:MAX_FILE_CHARS] + ("\n[file cut here]" if cut else "")


# ================= the job =================
def _set(**kw):
    with _LOCK:
        JOB.update(kw)


def _split_summary(text: str):
    m = re.match(r"\s*SUMMARY:\s*(.+?)(?:\n\s*\n|\n)(.*)", text, re.S)
    if m:
        return m.group(1).strip()[:600], m.group(2).strip()
    return text.strip()[:300], text.strip()


def _run(task: str, kind: str, file_path: str, max_out: int):
    try:
        cfg = _cfg()
        prompt = f"TASK TYPE: {kind}\n\nTASK:\n{task.strip()}\n"
        if file_path:
            name, content = _read_context(file_path)
            prompt += f"\nFILE {name}:\n```\n{content}\n```\n"
        est_in = (len(prompt) + len(SYSTEM)) // 3 + 50
        stop = _check_budget(cfg, est_in, max_out)
        if stop:
            raise RuntimeError(stop)
        _set(msg=f"asking {cfg['model']} (about {est_in:,} tokens in)")
        text, tin, tout = call_llm(cfg, prompt, max_out)
        if not text.strip():
            raise RuntimeError("The model returned an empty answer.")
        if not tin and not tout:                     # service gave no usage numbers: estimate
            tin, tout = est_in, len(text) // 3
        used = _record(cfg, kind, tin, tout)
        summary, body = _split_summary(text)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{kind}.md"
        out.write_text(f"# {kind}: {task.strip()[:120]}\n\nModel: {cfg['model']}  |  tokens: {used:,}\n\n{body}\n",
                       encoding="utf-8")
        _set(state="done", summary=summary, file=str(out),
             msg=f"{used:,} tokens used for this job. {usage_summary(cfg)}")
    except Exception as e:
        cfg = _cfg() or {}
        _set(state="failed", msg=_mask(str(e), cfg.get("key", "")))


def heavy_task(task: str, kind: str = "analysis", file_path: str = "") -> str:
    """Send a serious task to the heavy brain (second api key). Runs in the background."""
    cfg = _cfg()
    if not cfg:
        return "No heavy key yet. Boss must add HEAVY_API_KEY to the .env file, then restart Guts."
    if "error" in cfg:
        return cfg["error"]
    if not cfg.get("model"):
        return ("HEAVY_MODEL is not set in .env. Boss can see the models with: python heavy_brain.py models")
    kind = (kind or "analysis").lower().strip()
    if kind not in KINDS:
        return f"kind must be one of: {', '.join(KINDS)}. The heavy brain is only for serious work."
    if len((task or "").strip()) < 20:
        return "That is too short for the heavy brain. It is only for serious tech or important work. Ask Boss for details."
    with _LOCK:
        if JOB["state"] == "running":
            return "The heavy brain is already working. Use heavy_status."
        JOB.update(state="running", msg="starting", summary="", file=None, t0=time.time())
    threading.Thread(target=_run, args=(task, kind, file_path, MAX_OUT_DEFAULT), daemon=True).start()
    return ("Heavy task started in the background. Tell Boss it started and use heavy_status when he asks. "
            + usage_summary(cfg))


def heavy_status() -> str:
    with _LOCK:
        j = dict(JOB)
    if j["state"] == "idle":
        return "No heavy task running. " + usage_summary()
    el = int(time.time() - j["t0"])
    if j["state"] == "running":
        return f"Heavy brain is working: {j['msg']}, {el} sec so far."
    if j["state"] == "done":
        return (f"DONE in {el} sec. Summary to read aloud: {j['summary']}  Full answer saved in {j['file']}. "
                f"{j['msg']}")
    return f"FAILED: {j['msg']}"


if __name__ == "__main__":
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    if cmd == "models":
        try:
            print("\n".join(list_models()) or "(no models listed)")
        except Exception as e:
            print("Error:", _mask(str(e), (_cfg() or {}).get("key", "")))
    elif cmd == "usage":
        print(usage_summary())
    elif cmd == "ask" and len(sys.argv) > 2:
        print(heavy_task(" ".join(sys.argv[2:]), "analysis"))
        while JOB["state"] == "running":
            time.sleep(1)
        print(heavy_status())
    else:
        print(__doc__)
