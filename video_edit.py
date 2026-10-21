"""video_edit.py - Guts edits videos (PART 1) with ffmpeg. Works without CapCut.

  latest_video(folder)       newest video in Downloads / Desktop / Videos
  video_info(path)           length, size, fps, audio
  video_auto_edit(path, style)   starts the edit in the BACKGROUND:
        1. cuts the silent gaps (jump cuts)
        2. 9:16 reel format (horizontal video gets a blurred background, no ugly bars)
        3. light pro colour (contrast, saturation, sharpen)
        4. loudness to -14 LUFS (Instagram / YouTube level) and removes low rumble
        5. exports mp4 (H.264, high quality) to projects\\video\\
  video_status()             progress / result

Needs ffmpeg:  winget install Gyan.FFmpeg     (or: python -m pip install imageio-ffmpeg)
"""
import os
import re
import sys
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT_DIR = BASE / "projects" / "video"
HOME = Path.home()
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

# ---- tuning (edit these if the cuts feel too tight or too loose) ----
SILENCE_DB = -35        # quieter than this = silence
SILENCE_MIN = 0.35      # silence must last at least this many seconds to be cut
PAD = 0.08              # seconds of breathing room kept around speech
MIN_KEEP = 0.25         # shorter pieces than this are dropped
REEL_W, REEL_H, FPS = 1080, 1920, 30

JOB = {"state": "idle", "msg": "", "out": None, "t0": 0.0, "pct": 0}
_LOCK = threading.Lock()


# ================= ffmpeg =================
def _ffmpeg():
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _no_window():
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}      # CREATE_NO_WINDOW


def probe(path: str) -> dict:
    """Length, size, fps, audio. Reads ffmpeg's own report, so ffprobe is not needed."""
    ff = _ffmpeg()
    if not ff:
        raise RuntimeError("ffmpeg is not installed. Run: winget install Gyan.FFmpeg   (then restart Guts)")
    r = subprocess.run([ff, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                       errors="replace", **_no_window())
    txt = r.stderr
    d = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", txt)
    v = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", txt)
    if not d or not v:
        raise RuntimeError("This file does not look like a video ffmpeg can read.")
    w, h = int(v.group(1)), int(v.group(2))
    rot = re.search(r"rotation of (-?\d+(?:\.\d+)?) degrees", txt)
    if rot and abs(round(float(rot.group(1)))) % 180 == 90:       # phone video stored sideways
        w, h = h, w
    fps = re.search(r"([\d.]+) fps", txt)
    return {"duration": int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)),
            "w": w, "h": h, "fps": float(fps.group(1)) if fps else 30.0,
            "audio": bool(re.search(r"Stream #\d+:\d+.*Audio:", txt))}


def _folder(name: str) -> Path:
    n = (name or "downloads").strip().lower()
    for k in ("Desktop", "Documents", "Downloads", "Videos"):
        if n == k.lower():
            p = HOME / "OneDrive" / k
            return p if p.exists() else HOME / k
    return Path(os.path.expandvars(name)).expanduser()


def _check_video(path: str) -> Path:
    p = Path(os.path.expandvars(path)).expanduser()
    if not p.is_file():
        raise RuntimeError(f"File not found: {p}")
    if p.suffix.lower() not in VIDEO_EXT:
        raise RuntimeError(f"That is not a video file ({p.suffix}).")
    return p


# ================= tools for Guts =================
def latest_video(folder: str = "Downloads") -> str:
    """Newest video file in Downloads, Desktop, Documents, Videos or a folder path."""
    base = _folder(folder)
    best = None
    try:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            if root[len(str(base)):].count(os.sep) >= 2:
                dirs[:] = []
            for f in files:
                if Path(f).suffix.lower() in VIDEO_EXT:
                    fp = os.path.join(root, f)
                    m = os.path.getmtime(fp)
                    if best is None or m > best[0]:
                        best = (m, fp)
    except Exception as e:
        return f"Search error: {e}"
    if not best:
        return f"No video found in {base}."
    return f"{best[1]}  (saved {time.strftime('%Y-%m-%d %H:%M', time.localtime(best[0]))})"


def video_info(path: str) -> str:
    try:
        p = _check_video(path)
        i = probe(str(p))
        return (f"{p.name}: {i['duration']:.1f} sec, {i['w']}x{i['h']}, {i['fps']:.0f} fps, "
                f"{'with audio' if i['audio'] else 'NO audio'}")
    except Exception as e:
        return f"Cannot read video: {e}"


def video_status() -> str:
    with _LOCK:
        j = dict(JOB)
    if j["state"] == "idle":
        return "No edit has been started."
    el = int(time.time() - j["t0"])
    if j["state"] == "running":
        return f"Editing is running: {j['msg']} ({j['pct']}%), {el} sec so far."
    if j["state"] == "done":
        return f"DONE in {el} sec. {j['msg']} File: {j['out']}"
    return f"FAILED: {j['msg']}"


# ================= the edit =================
def _silences(ff: str, path: str):
    r = subprocess.run([ff, "-hide_banner", "-nostats", "-i", path, "-vn",
                        "-af", f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_MIN}", "-f", "null", "-"],
                       capture_output=True, text=True, errors="replace", **_no_window())
    starts = [float(x) for x in re.findall(r"silence_start: (-?\d+(?:\.\d+)?)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?\d+(?:\.\d+)?)", r.stderr)]
    return starts, ends


def keep_segments(duration: float, starts: list, ends: list):
    """The parts to KEEP = everything that is not a silence, with a little padding."""
    sil = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else duration
        sil.append((max(0.0, s), min(duration, e)))
    keep, cur = [], 0.0
    for s, e in sil:
        if s - cur > 0:
            keep.append([cur, s])
        cur = max(cur, e)
    if duration - cur > 0:
        keep.append([cur, duration])
    out = []
    for a, b in keep:
        a, b = max(0.0, a - PAD), min(duration, b + PAD)
        if out and a <= out[-1][1] + 0.10:           # merge neighbours that now touch
            out[-1][1] = max(out[-1][1], b)
        elif b - a >= MIN_KEEP:
            out.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in out]


def build_graph(segs, info: dict, style: str) -> str:
    n = len(segs)
    parts = []
    for i, (a, b) in enumerate(segs):
        parts.append(f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}]")
        if info["audio"]:
            parts.append(f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a{i}]")
    cat_in = "".join(f"[v{i}]" + (f"[a{i}]" if info["audio"] else "") for i in range(n))
    parts.append(f"{cat_in}concat=n={n}:v=1:a={1 if info['audio'] else 0}[cv]" + ("[ca]" if info["audio"] else ""))

    color = "eq=contrast=1.06:saturation=1.12,unsharp=5:5:0.6:5:5:0.0"
    if style == "reel":
        if info["h"] >= info["w"]:                    # already vertical: fill the frame
            parts.append(f"[cv]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
                         f"crop={REEL_W}:{REEL_H},fps={FPS},{color},format=yuv420p[v]")
        else:                                         # horizontal: sharp video over a blurred copy of itself
            parts.append("[cv]split[bgs][fgs]")
            parts.append(f"[bgs]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
                         f"crop={REEL_W}:{REEL_H},boxblur=24:6,eq=brightness=-0.08[bg]")
            parts.append(f"[fgs]scale={REEL_W}:-2[fg]")
            parts.append(f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={FPS},{color},format=yuv420p[v]")
    else:                                             # keep the original size
        parts.append(f"[cv]fps={FPS},{color},format=yuv420p[v]")
    if info["audio"]:
        parts.append("[ca]highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    return ";\n".join(parts)


def _unique_out(src: Path, style: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", src.stem).strip("_") or "video"
    n = 1
    while True:
        out = OUT_DIR / f"{stem}_{style}_edit{'' if n == 1 else '_' + str(n)}.mp4"
        if not out.exists():
            return out
        n += 1


def _set(**kw):
    with _LOCK:
        JOB.update(kw)


def _encode(ff: str, src: Path, script: Path, graph: str, info: dict, out: Path, kept: float):
    """Runs the encode. Newer ffmpeg (8.x) removed -filter_complex_script and older ones (before 7) do not know
    -/filter_complex, so each way of giving the filter graph is tried until one is accepted."""
    maps = ["-map", "[v]"] + (["-map", "[a]"] if info["audio"] else [])
    enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"] + \
          (["-c:a", "aac", "-b:a", "192k"] if info["audio"] else []) + \
          ["-movflags", "+faststart", "-progress", "pipe:1"]
    ways = [["-/filter_complex", str(script)], ["-filter_complex_script", str(script)]]
    if len(graph) < 24000:                            # Windows allows about 32000 characters in a command
        ways.append(["-filter_complex", graph])
    last = ""
    for way in ways:
        cmd = [ff, "-hide_banner", "-nostats", "-y", "-i", str(src)] + way + maps + enc + [str(out)]
        errfile = Path(tempfile.gettempdir()) / f"guts_ffmpeg_err_{int(time.time())}.txt"
        with open(errfile, "w", encoding="utf-8", errors="replace") as ef:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=ef, text=True, errors="replace", **_no_window())
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
            continue                                  # this ffmpeg does not know that way, try the next
        break
    tail = " | ".join(last.strip().splitlines()[-6:]) if last.strip() else "unknown error"
    raise RuntimeError("ffmpeg failed: " + tail)


def _run_edit(src: Path, style: str):
    try:
        ff = _ffmpeg()
        info = probe(str(src))
        if info["duration"] < 1:
            raise RuntimeError("The video is shorter than 1 second.")
        _set(msg="looking for silent parts", pct=2)
        if info["audio"]:
            starts, ends = _silences(ff, str(src))
            segs = keep_segments(info["duration"], starts, ends)
        else:
            segs = [(0.0, round(info["duration"], 3))]
        if not segs:
            segs = [(0.0, round(info["duration"], 3))]
        kept = sum(b - a for a, b in segs)
        cuts = max(0, len(segs) - 1)
        _set(msg=f"cutting {cuts} silent gaps ({info['duration']:.0f}s -> {kept:.0f}s)", pct=5)

        out = _unique_out(src, style)
        graph = build_graph(segs, info, style)
        script = Path(tempfile.gettempdir()) / f"guts_graph_{int(time.time())}.txt"
        script.write_bytes(graph.encode("utf-8"))
        try:
            _encode(ff, src, script, graph, info, out, kept)
        finally:
            try:
                script.unlink()
            except Exception:
                pass
        _set(state="done", pct=100, out=str(out),
             msg=f"{info['duration']:.0f}s became {kept:.0f}s with {cuts} cuts, {style} format, colour and loudness fixed.")
        try:
            if sys.platform == "win32":
                os.startfile(str(OUT_DIR))
        except Exception:
            pass
    except Exception as e:
        _set(state="failed", msg=str(e))


def video_auto_edit(path: str, style: str = "reel") -> str:
    """Start a professional auto edit in the background. style: reel (9:16) or original (keep size)."""
    try:
        src = _check_video(path)
        if not _ffmpeg():
            return "ffmpeg is not installed. Tell Boss to run: winget install Gyan.FFmpeg   then restart Guts."
        style = "original" if (style or "").lower().startswith(("orig", "land", "keep")) else "reel"
        with _LOCK:
            if JOB["state"] == "running":
                return "An edit is already running. Use video_status to see the progress."
            JOB.update(state="running", msg="starting", out=None, t0=time.time(), pct=0)
        threading.Thread(target=_run_edit, args=(src, style), daemon=True).start()
        return (f"Edit started for {src.name} ({style}). It runs in the background. "
                "Tell Boss it started and use video_status when he asks if it is done.")
    except Exception as e:
        return f"Cannot start: {e}"


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(video_info(sys.argv[1]))
        print(video_auto_edit(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "reel"))
        while JOB["state"] == "running":
            time.sleep(1)
            print(video_status())
        print(video_status())
    else:
        print(__doc__)
