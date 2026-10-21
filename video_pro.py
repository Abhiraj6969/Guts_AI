"""video_pro.py - Guts edits videos (PART 2): zoom punch-ins, captions and a hook title.

Builds on video_edit.py (Part 1). One command does everything:
  1. Part 1: cuts the silent gaps, 9:16 reel format, colour, loudness
  2. zoom punch-in every few seconds (long clips are split so you always see it)
  3. captions: 3 words at a time, big bold style, the spoken word pops in gold, Roman Hinglish,
     timed to the real speech (the program checks the captions against the audio and fixes the offset)
  4. a hook title banner in the first seconds
  5. optional music (Part 3): zoom switches on the beat, music ducks under the voice, fades, -14 LUFS
  6. exports  <name>_<style>_pro_edit.mp4  (or ..._music_pro_edit.mp4) to projects\\video\\   (the clean Part 1 edit is kept too)

Speech to text (needed for captions), the first one that works is used:
  - Groq Whisper (free):  add GROQ_API_KEY=... to .env
  - local faster-whisper: python -m pip install faster-whisper     (downloads a model the first time)

Test without Guts:
  python video_pro.py "C:\\path\\video.mp4"
  python video_pro.py "C:\\path\\video.mp4" --hook "Yeh galti mat karo"
  python video_pro.py "C:\\path\\video.mp4" --no-zoom
  python video_pro.py "C:\\path\\video.mp4" --draft             (quick half-size preview, about 3x faster)
  python video_pro.py "C:\\path\\video.mp4" --music auto          (random song from the music folder, zoom on the beat)
  python video_pro.py "C:\\path\\video.mp4" --music "C:\\path\\song.mp3"
  python video_pro.py "C:\\path\\video.mp4" --style clean       (calmer caption look)
  python video_pro.py "C:\\path\\video.mp4" --shift -0.15        (captions 0.15 s earlier; + = later)
  python video_pro.py "C:\\path\\video.mp4" --captions-only     (no cutting, only captions + hook)
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import shutil
from pathlib import Path

from dotenv import load_dotenv

import video_edit as ve
import video_music as vm

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")

# ---- tuning (edit these to change the look) ----
ZOOM = 1.2                  # punch-in size on every second clip (1.0 = no zoom)
ZOOM_EVERY = 2.8            # seconds. Long clips are split about this often so the zoom shows even without cuts
CAPTION_STYLE = "bold"      # "bold" = big Impact letters, the spoken word pops. "clean" = calm Arial
CAPTION_WORDS = 3           # words on screen at a time
CAPTION_MARGIN_V = 540      # distance from the bottom, keeps captions clear of the Reels buttons
CAPTION_SHIFT = 0.0         # fine tuning in seconds after the automatic sync: + = later, - = earlier
SYNC_LEAD = 0.04            # captions appear a hair early, it feels more in sync
DEVANAGARI_FONT = "Nirmala UI"      # used only for captions that contain Hindi letters
STYLES = {
    "bold": {"font": "Impact", "size": 104, "outline": 8, "shadow": 3, "active_scale": 114, "caps": True, "hook_box": True, "wf": 0.6},
    "clean": {"font": "Arial", "size": 78, "outline": 6, "shadow": 2, "active_scale": 100, "caps": True, "hook_box": False, "wf": 0.66},
}
HIGHLIGHT = "&H00D7FF&"     # spoken word colour (gold). Format is &HBBGGRR&
HOOK_SECONDS = 2.6
HOOK_SIZE = 88
HOOK_MARGIN_V = 300
STT_LANGUAGE = "hi"         # speech language hint for Hinglish. Use "en" for English videos, "" for auto
STT_PROMPT = "Yeh ek Hinglish video hai, Hindi aur English mix. Jaise: aaj hum dekhenge ki ye kaise kaam karta hai."
GROQ_MODELS = ["whisper-large-v3", "whisper-large-v3-turbo"]      # the bigger model first: better timing
DEV_RE = re.compile(r"[\u0900-\u097F]")

# ---- speed ----
SPEEDUP = True              # also makes Part 1 (video_auto_edit) faster
ENCODE_PRESET = "veryfast"  # x264 speed: ultrafast, superfast, veryfast, faster, fast, medium (slower = smaller file)
ENCODE_CRF = 20             # quality: lower = better and bigger. 18 was near lossless, 20-23 is plenty for Reels
USE_GPU = True              # use the graphics card encoder (NVIDIA, Intel, AMD) when ffmpeg can: 3-8x faster
WORK_SIZE = 1920            # long side of the working picture. 4K phone videos are shrunk early, the rest is much faster

_set = lambda **kw: ve._set(**kw)


# ================= speed + zoom punch-in =================
BLUR_RE = re.compile(r"\[bgs\]scale=(\d+):(\d+):force_original_aspect_ratio=increase,crop=\d+:\d+,"
                     r"boxblur=24:6,eq=brightness=-0\.08\[bg\]")


def fast_blur(graph: str) -> str:
    """The blurred background is made small, blurred, then enlarged: the same look with 16x fewer pixels to blur."""
    return BLUR_RE.sub(lambda m: (f"[bgs]scale={int(m[1]) // 4}:{int(m[2]) // 4}:force_original_aspect_ratio=increase,"
                                  f"crop={int(m[1]) // 4}:{int(m[2]) // 4},boxblur=6:2,eq=brightness=-0.08,"
                                  f"scale={m[1]}:{m[2]}[bg]"), graph)


def prep_graph(graph: str, info: dict, zoom: float) -> str:
    """Speed and zoom changes to the Part 1 filter graph:
    every clip is cut to 30 fps and shrunk to the working size FIRST (a 4K 60 fps phone video is 8x more work
    than needed), and every second clip is cropped in a little (zoom) and scaled back."""
    w, h = info["w"], info["h"]
    f = min(1.0, WORK_SIZE / max(w, h))
    ww, hh = max(2, int(w * f) // 2 * 2), max(2, int(h * f) // 2 * 2)

    def sub(m):
        i = int(m.group(1))
        chain = f"setpts=PTS-STARTPTS,fps={ve.FPS},scale={ww}:{hh}:flags=bicubic"
        if zoom > 1.0 and i % 2 == 1:
            chain += (f",crop=trunc(iw/{zoom}/2)*2:trunc(ih/{zoom}/2)*2,scale={ww}:{hh}:flags=bicubic")
        return chain + f",setsar=1[v{i}]"

    return fast_blur(re.sub(r"setpts=PTS-STARTPTS\[v(\d+)\]", sub, graph))


# ================= encoder =================
_ENC = {}


def _encoders(ff: str) -> list:
    """[(name, ffmpeg arguments)] best first. The graphics card encoder only if a real test encode works."""
    if "list" not in _ENC:
        x264 = ("libx264", ["-c:v", "libx264", "-preset", ENCODE_PRESET, "-crf", str(ENCODE_CRF)])
        out = [x264]
        if USE_GPU:
            trials = [("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "22", "-b:v", "0"]),
                      ("h264_qsv", ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "22"]),
                      ("h264_amf", ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "22", "-qp_p", "22"])]
            for name, args in trials:
                try:
                    r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                                        "color=c=black:s=640x360:d=0.2", "-pix_fmt", "yuv420p"] + args + ["-f", "null", "-"],
                                       capture_output=True, timeout=30, **ve._no_window())
                    if r.returncode == 0:
                        out.insert(0, (name, args))
                        break
                except Exception:
                    pass
        _ENC["list"] = out
        print(f"[Pro] video encoder: {out[0][0]}" + (" (graphics card)" if out[0][0] != "libx264" else f" ({ENCODE_PRESET})"))
    return _ENC["list"]


def _encode_fast(ff: str, src: Path, script: Path, graph: str, info: dict, out: Path, kept: float):
    """Same job as video_edit._encode with the faster encoder choice. If the graphics card encoder
    fails for any reason, it falls back to x264 by itself."""
    maps = ["-map", "[v]"] + (["-map", "[a]"] if info["audio"] else [])
    audio = ["-c:a", "aac", "-b:a", "192k"] if info["audio"] else []
    tail = ["-movflags", "+faststart", "-progress", "pipe:1"]
    ways = [["-/filter_complex", str(script)], ["-filter_complex_script", str(script)]]
    if len(graph) < 24000:
        ways.append(["-filter_complex", graph])
    last = ""
    for ename, eargs in _encoders(ff):
        for way in ways:
            cmd = ([ff, "-hide_banner", "-nostats", "-y", "-i", str(src)] + way + maps + ["-pix_fmt", "yuv420p"]
                   + eargs + audio + tail + [str(out)])
            errfile = Path(tempfile.gettempdir()) / f"guts_enc_err_{int(time.time() * 1000)}.txt"
            with open(errfile, "w", encoding="utf-8", errors="replace") as ef:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=ef, text=True, errors="replace", **ve._no_window())
                for line in p.stdout:
                    m = re.match(r"out_time_us=(\d+)", line) or re.match(r"out_time_ms=(\d+)", line)
                    if m and kept > 0:
                        _set(pct=min(99, 5 + int(int(m.group(1)) / 1e6 / kept * 94)), msg="exporting")
                p.wait()
            last = errfile.read_text(encoding="utf-8", errors="replace")
            try:
                errfile.unlink()
            except Exception:
                pass
            if p.returncode == 0 and out.exists():
                return
            if out.exists():
                try:
                    out.unlink()
                except Exception:
                    pass
            if "Unrecognized option" in last or "Option not found" in last:
                continue                                  # this ffmpeg does not know that way of giving the filters
            break                                         # this encoder failed: try the next one
        print(f"[Pro] encoder {ename} failed, trying the next one")
    tail_msg = " | ".join(last.strip().splitlines()[-6:]) if last.strip() else "unknown error"
    raise RuntimeError("ffmpeg failed: " + tail_msg)


if SPEEDUP:                                               # Part 1 gets the same speed-ups
    _orig_build_graph = ve.build_graph
    ve.build_graph = lambda segs, info, style: fast_blur(_orig_build_graph(segs, info, style))
    ve._encode = _encode_fast


def split_for_zoom(segs: list, every: float = ZOOM_EVERY) -> list:
    """Cuts long clips into pieces of about `every` seconds. The pieces follow each other without any gap,
    so nothing is lost: it only gives the zoom a place to switch."""
    out = []
    for a, b in segs:
        n = max(1, int(round((b - a) / every)))
        step = (b - a) / n
        for i in range(n):
            s = round(a + i * step, 3)
            e = round(b if i == n - 1 else a + (i + 1) * step, 3)
            out.append((s, e))
    return out


# ================= speech to text =================
def _multipart(fields: dict, file_field: str, file_path: Path):
    boundary = "----guts" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        for item in (v if isinstance(v, list) else [v]):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{item}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
                  f'filename="{file_path.name}"\r\nContent-Type: audio/flac\r\n\r\n').encode()
                 + file_path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return boundary, b"".join(parts)


def _words_from(data: dict) -> list:
    out = []
    for w in data.get("words") or []:
        t = str(w.get("word", "")).strip()
        if t:
            out.append({"text": t, "start": float(w["start"]), "end": float(w["end"])})
    if out:
        return out
    for s in data.get("segments") or []:        # no word times: spread each sentence evenly
        ws = str(s.get("text", "")).split()
        if not ws:
            continue
        a, b = float(s["start"]), float(s["end"])
        step = (b - a) / len(ws)
        out += [{"text": x, "start": a + i * step, "end": a + (i + 1) * step} for i, x in enumerate(ws)]
    return out


def _stt_groq(audio: Path) -> list:
    key = os.getenv("GROQ_API_KEY")
    last = ""
    for model in GROQ_MODELS:
        fields = {"model": model, "response_format": "verbose_json", "temperature": "0",
                  "timestamp_granularities[]": ["word", "segment"]}
        if STT_LANGUAGE:
            fields["language"] = STT_LANGUAGE
        if STT_PROMPT:
            fields["prompt"] = STT_PROMPT
        boundary, body = _multipart(fields, "file", audio)
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/audio/transcriptions", data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}",
                     "User-Agent": "guts-ai/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read().decode("utf-8"))
            words = _words_from(data)
            if words:
                print(f"[Pro] speech read by groq/{model}")
                return words
            last = f"groq/{model}: no words in the answer"
        except urllib.error.HTTPError as e:
            last = f"groq/{model}: {e.code} {e.read().decode(errors='ignore')[:100]}"
        except Exception as e:
            last = f"groq/{model}: {str(e)[:100]}"
        print(f"[Pro] {last}")
    raise RuntimeError(last)


def _stt_local(audio: Path) -> list:
    from faster_whisper import WhisperModel          # ImportError if not installed
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(str(audio), word_timestamps=True, vad_filter=True,
                               language=STT_LANGUAGE or None, initial_prompt=STT_PROMPT or None)
    out = []
    for s in segs:
        for w in (s.words or []):
            t = w.word.strip()
            if t:
                out.append({"text": t, "start": float(w.start), "end": float(w.end)})
    print("[Pro] speech read by local faster-whisper")
    return out


def transcribe(audio: Path) -> list:
    errs = []
    if os.getenv("GROQ_API_KEY"):
        try:
            return _stt_groq(audio)
        except Exception as e:
            errs.append(str(e)[:150])
    try:
        return _stt_local(audio)
    except ImportError:
        errs.append("faster-whisper is not installed")
    except Exception as e:
        errs.append(f"local: {str(e)[:120]}")
    raise RuntimeError("Could not read the speech (" + " | ".join(errs) + "). Add GROQ_API_KEY to .env "
                       "or run: python -m pip install faster-whisper")


# ================= captions =================
def make_chunks(words: list, n: int = CAPTION_WORDS, max_gap: float = 0.6) -> list:
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= n or w["start"] - cur[-1]["end"] > max_gap
                    or cur[-1]["text"].endswith((".", "?", "!", "\u0964"))):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    chunks = [{"start": g[0]["start"], "end": g[-1]["end"], "words": g,
               "text": " ".join(x["text"] for x in g)} for g in groups]
    for i, c in enumerate(chunks):                    # no flicker between lines, and never too short
        nxt = chunks[i + 1]["start"] if i + 1 < len(chunks) else None
        c["end"] = max(c["end"], c["start"] + 0.35)
        if nxt is not None:
            c["end"] = nxt if nxt - c["end"] < 0.4 else min(c["end"] + 0.2, nxt)
        else:
            c["end"] += 0.2
    return chunks


def speech_onsets(ff: str, path: Path, duration: float) -> list:
    """Moments when speech starts after a short pause, read from the sound itself."""
    r = subprocess.run([ff, "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                        f"silencedetect=noise={ve.SILENCE_DB}dB:d=0.12", "-f", "null", "-"],
                       capture_output=True, text=True, errors="replace", **ve._no_window())
    starts = [float(x) for x in re.findall(r"silence_start: (-?\d+(?:\.\d+)?)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?\d+(?:\.\d+)?)", r.stderr)]
    onsets = [e for e in ends if e < duration - 0.2]
    if not starts or starts[0] > 0.15:
        onsets.insert(0, 0.0)
    return onsets


def _shift(chunks: list, d: float):
    for c in chunks:
        c["start"] += d
        c["end"] += d
        for w in c["words"]:
            w["start"] += d
            w["end"] += d


def align_to_audio(chunks: list, onsets: list):
    """Speech to text can be a few tenths of a second off. Whenever a caption starts after a pause, the real
    start of speech is known from the sound, so the typical offset is measured and removed.
    Returns (offset_found, anchors_used)."""
    if not chunks or not onsets:
        return 0.0, 0
    diffs, prev_end = [], None
    for c in chunks:
        c["after_pause"] = prev_end is None or c["words"][0]["start"] - prev_end >= 0.12
        prev_end = c["words"][-1]["end"]
        if c["after_pause"]:
            near = min(onsets, key=lambda o: abs(o - c["start"]))
            if abs(near - c["start"]) <= 0.6:
                diffs.append(near - c["start"])
    shift = 0.0
    if len(diffs) >= 3:
        diffs.sort()
        shift = max(-0.5, min(0.5, diffs[len(diffs) // 2]))
        if abs(shift) < 0.04:
            shift = 0.0
    if shift:
        _shift(chunks, shift)
    for c in chunks:                                   # captions after a pause start exactly where the voice starts
        if c.get("after_pause"):
            near = min(onsets, key=lambda o: abs(o - c["start"]))
            if abs(near - c["start"]) <= 0.2:
                d = near - c["start"]
                c["start"] += d
                w0 = c["words"][0]
                w0["start"] += d
                if w0["end"] <= w0["start"]:
                    w0["end"] = w0["start"] + 0.15
    for i in range(len(chunks) - 1):                   # no overlap between two captions
        if chunks[i]["end"] > chunks[i + 1]["start"]:
            chunks[i]["end"] = max(chunks[i]["start"] + 0.1, chunks[i + 1]["start"])
    return shift, len(diffs)


def romanize(chunks: list):
    """Hindi letters become Roman Hinglish (the font and the audience both like it better)."""
    if not any(DEV_RE.search(c["text"]) for c in chunks):
        return
    try:
        import guts_brain
    except Exception:
        return
    for i in range(0, len(chunks), 40):
        batch = chunks[i:i + 40]
        prompt = ("Convert every numbered line to natural Roman-script Hinglish (English letters only, the way "
                  "people type Hindi in chat). Keep English words as they are. Do not translate, merge or drop "
                  f"lines. Reply with ONE JSON array of strings with exactly {len(batch)} items, in order.\n\n"
                  + "\n".join(f"{k + 1}. {c['text']}" for k, c in enumerate(batch)))
        try:
            text = guts_brain._generate(prompt, "You convert Hindi text to Roman Hinglish. Reply with JSON only.", False)
            out = json.loads(text[text.find("["):text.rfind("]") + 1])
            if isinstance(out, list) and len(out) == len(batch) and all(isinstance(x, str) for x in out):
                for c, new in zip(batch, out):
                    c["text"] = new.strip()
        except Exception as e:
            print(f"[Pro] could not convert to Roman letters: {str(e)[:80]}")


def auto_hook(text: str) -> str:
    try:
        import guts_brain
        out = guts_brain._generate(
            "Write ONE punchy hook title for an Instagram reel made from this speech. Maximum 6 words, Roman "
            "Hinglish or English, no quotes, no emojis, no hashtags. Reply with the title only.\n\nSpeech: " + text,
            "You write short viral hook titles.", False)
        line = out.strip().splitlines()[0].strip().strip("\"'*#").strip()
        return line[:45]
    except Exception as e:
        print(f"[Pro] no auto hook: {str(e)[:80]}")
        return ""


def _t(x: float) -> str:
    cs = int(round(max(0.0, x) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _esc(s: str) -> str:
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def _look(s: str, caps: bool = True) -> str:
    s = _esc(s)
    return s.upper() if caps and not DEV_RE.search(s) else s


def build_ass(chunks: list, hook: str, w: int, h: int, duration: float) -> str:
    st = STYLES.get(CAPTION_STYLE, STYLES["bold"])
    k = min(w, h) / 1080.0
    fs, hfs = int(st["size"] * k), int(HOOK_SIZE * k)
    mv, hmv, mx = int(CAPTION_MARGIN_V * k), int(HOOK_MARGIN_V * k), int(60 * k)
    outline, shadow = max(2, int(st["outline"] * k)), max(1, int(st["shadow"] * k))
    gold = f"&H00{HIGHLIGHT[2:-1]}"
    if st["hook_box"]:      # black letters on a gold banner
        hook_style = (f"Style: Hook,{st['font']},{hfs},&H00000000,&H00FFFFFF,{gold},&H00000000,-1,0,0,0,100,100,0,0,3,"
                      f"{int(18 * k)},0,8,{mx},{mx},{hmv},1")
    else:                   # gold letters with a black outline
        hook_style = (f"Style: Hook,{st['font']},{hfs},{gold},&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,"
                      f"{max(2, int(7 * k))},{max(1, int(3 * k))},8,{mx},{mx},{hmv},1")
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {w}\nPlayResY: {h}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,{st['font']},{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,"
        f"{outline},{shadow},2,{mx},{mx},{mv},1\n"
        + hook_style + "\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    caps, sc = st["caps"], st["active_scale"]

    def fit(n_chars: float, base: int) -> int:
        """Biggest letter size that keeps a line inside the screen (long words shrink instead of being cut off)."""
        return max(48, min(base, int((w - 2 * mx) / (st["wf"] * max(n_chars, 1)))))

    ev = []
    if hook:
        end = min(HOOK_SECONDS, max(1.0, duration))
        hs = fit(len(hook) + 3, hfs)
        size_tag = f"\\fs{hs}" if hs < hfs else ""
        ev.append(f"Dialogue: 1,{_t(0)},{_t(end)},Hook,,0,0,0,,{{\\fad(150,250){size_tag}}}{_look(hook, caps)}")
    for c in chunks:
        font = f"{{\\fn{DEVANAGARI_FONT}}}" if DEV_RE.search(c["text"]) else ""
        parts = c["text"].split()
        ws = c["words"]
        cs = fit(len(" ".join(parts)) * (1.08 if sc > 100 else 1.0), fs)
        if cs < fs:
            font += f"{{\\fs{cs}}}"
        if len(parts) == len(ws) and len(ws) > 1:     # the spoken word is gold, bigger, and pops in
            for j, wd in enumerate(ws):
                a = c["start"] if j == 0 else wd["start"]
                b = c["end"] if j == len(ws) - 1 else ws[j + 1]["start"]
                if b - a < 0.05:
                    continue
                if sc > 100:
                    on = f"{{\\1c{HIGHLIGHT}\\fscx{int(sc * 0.82)}\\fscy{int(sc * 0.82)}\\t(0,110,\\fscx{sc}\\fscy{sc})}}"
                    off = "{\\1c&H00FFFFFF&\\fscx100\\fscy100}"
                else:
                    on, off = f"{{\\1c{HIGHLIGHT}}}", "{\\1c&H00FFFFFF&}"
                text = " ".join((f"{on}{_look(p, caps)}{off}" if idx == j else _look(p, caps))
                                for idx, p in enumerate(parts))
                ev.append(f"Dialogue: 0,{_t(a)},{_t(b)},Cap,,0,0,0,,{font}{text}")
        else:
            ev.append(f"Dialogue: 0,{_t(c['start'])},{_t(c['end'])},Cap,,0,0,0,,{font}{_look(c['text'], caps)}")
    return head + "\n".join(ev) + "\n"


# ================= the pipeline =================
def _run_ffmpeg(cmd: list, total: float, lo: int, hi: int, cwd: str = None):
    errfile = Path(tempfile.gettempdir()) / f"guts_pro_err_{int(time.time() * 1000)}.txt"
    with open(errfile, "w", encoding="utf-8", errors="replace") as ef:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=ef, text=True, errors="replace",
                             cwd=cwd, **ve._no_window())
        for line in p.stdout:
            m = re.match(r"out_time_us=(\d+)", line) or re.match(r"out_time_ms=(\d+)", line)
            if m and total > 0:
                _set(pct=lo + int(min(1.0, int(m.group(1)) / 1e6 / total) * (hi - lo)))
        p.wait()
    err = errfile.read_text(encoding="utf-8", errors="replace")
    try:
        errfile.unlink()
    except Exception:
        pass
    if p.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + " | ".join(err.strip().splitlines()[-5:]))


def _captions_pass(ff: str, base: Path, src: Path, tag: str, hook: str, tmp: Path) -> Path:
    _set(msg="listening to the speech", pct=56)
    audio = tmp / "speech.flac"
    subprocess.run([ff, "-hide_banner", "-y", "-i", str(base), "-vn", "-ac", "1", "-ar", "16000",
                    "-c:a", "flac", str(audio)], capture_output=True, **ve._no_window())
    if not audio.exists():
        raise RuntimeError("this video has no audio to make captions from")
    words = transcribe(audio)
    if not words:
        raise RuntimeError("no speech was found in the video")
    chunks = make_chunks(words)
    binfo = ve.probe(str(base))
    _set(msg="syncing captions to the voice", pct=66)
    try:
        off, n = align_to_audio(chunks, speech_onsets(ff, base, binfo["duration"]))
        print(f"[Pro] caption sync: moved by {off:+.2f}s using {n} voice starts")
    except Exception as e:
        print(f"[Pro] caption sync skipped: {str(e)[:80]}")
    fine = CAPTION_SHIFT - SYNC_LEAD
    if fine:
        _shift(chunks, fine)
    _set(msg="writing captions", pct=68)
    romanize(chunks)
    if hook == "auto":
        hook = auto_hook(" ".join(c["text"] for c in chunks)[:1500])
    (tmp / "caps.ass").write_text(build_ass(chunks, hook, binfo["w"], binfo["h"], binfo["duration"]),
                                  encoding="utf-8")
    out = ve._unique_out(src, tag)
    try:                                              # a list of what was heard and when, to check the timing
        lines = [f"{c['start']:7.2f}  {c['text']}" for c in chunks]
        out.with_suffix(".txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass
    _set(msg="adding captions", pct=72)
    err = None
    for ename, eargs in _encoders(ff):
        cmd = ([ff, "-hide_banner", "-nostats", "-y", "-i", str(base), "-vf", "ass=caps.ass", "-pix_fmt", "yuv420p"]
               + eargs + ["-c:a", "copy", "-movflags", "+faststart", "-progress", "pipe:1", str(out)])
        try:
            _run_ffmpeg(cmd, binfo["duration"], 72, 99, cwd=str(tmp))      # relative file name, so no path escaping
            return out
        except RuntimeError as e:
            err = e
            print(f"[Pro] encoder {ename} failed for the captions, trying the next one")
    raise err


def _run_pro(src: Path, style: str, hook: str, zoom: float, do_edit: bool, music: str = ""):
    src = Path(src).resolve()                       # captions run from a temp folder, so paths must be full
    tmp = Path(tempfile.mkdtemp(prefix="guts_pro_"))
    clean = None
    try:
        ff = ve._ffmpeg()
        info = ve.probe(str(src))
        if info["duration"] < 1:
            raise RuntimeError("The video is shorter than 1 second.")
        base, note = src, ""
        song = vm.pick_music(music) if music else None      # fails early with a clear message if there is no song

        if do_edit:
            _set(msg="looking for silent parts", pct=2)
            if info["audio"]:
                starts, ends = ve._silences(ff, str(src))
                segs = ve.keep_segments(info["duration"], starts, ends)
            else:
                segs = []
            if not segs:
                segs = [(0.0, round(info["duration"], 3))]
            kept = sum(b - a for a, b in segs)
            cuts = max(0, len(segs) - 1)
            _set(msg=f"cutting {cuts} silent gaps ({info['duration']:.0f}s -> {kept:.0f}s)", pct=5)
            zsegs = split_for_zoom(segs) if zoom > 1.0 else segs
            beat_note = ""
            if song and zoom > 1.0:                        # zoom switches on the beat of the song
                try:
                    bpm, beats = vm.detect_beats(song)
                    if beats and vm.duration(song) >= kept + 0.5:
                        beats = vm.extend_beats(bpm, beats, kept + 2)
                        zsegs = vm.split_on_beats(segs, beats, bpm)
                        beat_note = f", zoom on the beat ({bpm:.0f} BPM)"
                        print(f"[Pro] song tempo {bpm:.0f} BPM, zoom follows the beat")
                    else:
                        print("[Pro] the song is shorter than the video or has no clear beat, zoom keeps the normal rhythm")
                except Exception as e:
                    print(f"[Pro] beat detection skipped: {str(e)[:80]}")
            graph = prep_graph(ve.build_graph(zsegs, info, style), info, zoom if len(zsegs) > 1 else 1.0)
            clean = ve._unique_out(src, style)
            script = tmp / "graph.txt"
            script.write_bytes(graph.encode("utf-8"))
            orig = ve._set

            def scaled(**kw):                          # the edit takes the first half of the progress bar
                if "pct" in kw:
                    kw["pct"] = 5 + int(kw["pct"] * 0.5)
                orig(**kw)

            ve._set = scaled
            try:
                _encode_fast(ff, src, script, graph, info, clean, kept)
            finally:
                ve._set = orig
            base = clean
            note = f"{info['duration']:.0f}s became {kept:.0f}s with {cuts} cuts and {len(zsegs)} zoom clips{beat_note}"

        try:
            tag = f"{style}_pro" if do_edit else "captions"
            out = _captions_pass(ff, base, src, tag, hook, tmp)
            msg = (note + ", zoom, " if do_edit else "") + "captions and hook added."
        except Exception as e:
            if clean is None:
                raise
            out = clean
            msg = f"{note}. The clean edit is saved, but captions failed: {str(e)[:200]}"
        if song:
            _set(msg=f"adding the music ({song.stem})", pct=99)
            try:
                mout = ve._unique_out(src, "music_pro" if do_edit else "music")
                vm.mix_music(out, song, mout)
                out = mout
                msg += f" Music '{song.stem}' added with voice ducking."
            except Exception as e:
                msg += f" Music failed: {str(e)[:150]}"
        _set(state="done", pct=100, out=str(out), msg=msg)
        try:
            if sys.platform == "win32":
                os.startfile(str(ve.OUT_DIR))
        except Exception:
            pass
    except Exception as e:
        _set(state="failed", msg=str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _start(path: str, style: str, hook: str, zoom: float, do_edit: bool, music: str = "") -> str:
    try:
        src = ve._check_video(path)
        if not ve._ffmpeg():
            return "ffmpeg is not installed. Tell Boss to run: winget install Gyan.FFmpeg   then restart Guts."
        style = "original" if (style or "").lower().startswith(("orig", "land", "keep")) else "reel"
        with ve._LOCK:
            if ve.JOB["state"] == "running":
                return "An edit is already running. Use video_status to see the progress."
            ve.JOB.update(state="running", msg="starting", out=None, t0=time.time(), pct=0)
        threading.Thread(target=_run_pro, args=(src, style, hook, zoom, do_edit, music), daemon=True).start()
        what = "pro edit with zoom, captions and hook" if do_edit else "captions and hook"
        return (f"Started the {what} for {src.name} ({style}). It runs in the background and takes a few minutes. "
                "Tell Boss it started and use video_status when he asks if it is done.")
    except Exception as e:
        return f"Cannot start: {e}"


# ================= tools for Guts =================
def video_pro_edit(path: str, hook: str = "auto", style: str = "reel", music: str = "") -> str:
    """Full pro edit: silence cuts, 9:16 reel, zoom punch-ins, Hinglish captions, hook title, colour, loudness.
    music: empty for none, auto for a random song from the music folder, part of a song name, or a file path."""
    return _start(path, style, (hook or "").strip(), ZOOM, True, (music or "").strip())


def video_add_captions(path: str, hook: str = "") -> str:
    """Only add captions (and an optional hook title) to a video that is already edited. No cutting."""
    return _start(path, "original", (hook or "").strip(), 1.0, False)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0].startswith("--"):
        print(__doc__)
        sys.exit()
    path, hook, zoom, do_edit, style, music = args[0], "auto", ZOOM, True, "reel", ""
    i = 1
    while i < len(args):
        if args[i] == "--hook" and i + 1 < len(args):
            hook = args[i + 1]
            i += 1
        elif args[i] == "--no-zoom":
            zoom = 1.0
        elif args[i] == "--captions-only":
            do_edit = False
        elif args[i] == "--original":
            style = "original"
        elif args[i] == "--draft":                    # quick preview: half size, fastest encode
            ve.REEL_W, ve.REEL_H = 540, 960
            ENCODE_PRESET, ENCODE_CRF, WORK_SIZE = "ultrafast", 28, 960
            _ENC.clear()
        elif args[i] == "--music" and i + 1 < len(args):
            music = args[i + 1]
            i += 1
        elif args[i] == "--style" and i + 1 < len(args):
            CAPTION_STYLE = args[i + 1]
            i += 1
        elif args[i] == "--shift" and i + 1 < len(args):
            CAPTION_SHIFT = float(args[i + 1])
            i += 1
        i += 1
    print(ve.video_info(path))
    print(_start(path, style, hook, zoom, do_edit, music))
    while ve.JOB["state"] == "running":
        time.sleep(1)
        print(ve.video_status())
    print(ve.video_status())
