"""video_music.py - Guts edits videos (PART 3): background music, voice ducking, beat-synced zoom.

  add music        mixes a music track under the voice. The music gets quieter while you speak (ducking),
                   fades in and out, and the final loudness is -14 LUFS (Instagram / YouTube level).
  beat zoom        when video_pro.py gets a music file, the zoom punch-ins switch exactly on the beat.

Put your music files in the  music  folder next to this file (mp3, wav, m4a, aac, ogg, flac).
Use music you may legally use (YouTube Audio Library, Pixabay, the library inside Instagram...).
Copyrighted songs can get a reel muted or blocked.

Test without Guts:
  python video_music.py list                                  (shows the music folder)
  python video_music.py beats "C:\\path\\song.mp3"             (shows the tempo and the first beats)
  python video_music.py "C:\\path\\edited_video.mp4"           (adds a random song from the music folder)
  python video_music.py "C:\\path\\edited_video.mp4" "C:\\path\\song.mp3"
"""
import os
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import video_edit as ve

BASE = Path(__file__).resolve().parent
MUSIC_DIR = BASE / "music"
MUSIC_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}

# ---- tuning ----
MUSIC_VOLUME = 0.28         # music level under the voice before ducking (0.1 = very quiet, 0.5 = loud)
MUSIC_ONLY_VOLUME = 0.9     # when the video has no voice at all
DUCK_THRESHOLD = 0.03       # voice louder than this makes the music go down
DUCK_RATIO = 8              # how hard the music goes down
FADE_IN, FADE_OUT = 1.0, 1.5
BEAT_EVERY = 4              # zoom switches on every 4th beat (8th when the song is very fast)
MIN_ZOOM_GAP = 1.4          # seconds, no zoom clip shorter than this
BEAT_LATENCY = 0.028        # seconds. The analysis window sees a drum hit slightly early; measured on test songs


# ================= music files =================
def music_files() -> list:
    if not MUSIC_DIR.exists():
        return []
    return sorted(p for p in MUSIC_DIR.rglob("*") if p.suffix.lower() in MUSIC_EXT)


def music_list() -> str:
    """Names of the songs in the music folder."""
    files = music_files()
    if not files:
        return f"The music folder is empty. Put songs (mp3, wav, m4a) in {MUSIC_DIR}"
    return "Songs: " + "; ".join(p.stem for p in files[:40])


def pick_music(name: str = "auto") -> Path:
    """auto = a random song from the music folder, a part of a name, or a full file path."""
    name = (name or "auto").strip().strip('"')
    p = Path(os.path.expandvars(name)).expanduser()
    if p.is_file() and p.suffix.lower() in MUSIC_EXT:
        return p
    files = music_files()
    if not files:
        raise RuntimeError(f"No music found. Put songs in {MUSIC_DIR} or give the full path of a song.")
    if name.lower() in ("", "auto", "random", "any"):
        return random.choice(files)
    hits = [f for f in files if name.lower() in f.stem.lower()]
    if not hits:
        raise RuntimeError(f"No song matches '{name}'. {music_list()}")
    return hits[0]


def duration(path: Path) -> float:
    ff = ve._ffmpeg()
    r = subprocess.run([ff, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                       errors="replace", **ve._no_window())
    d = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not d:
        raise RuntimeError("Cannot read the length of " + Path(path).name)
    return int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))


# ================= beat detection =================
def detect_beats(path: Path, seconds: int = 120):
    """Tempo (BPM) and beat times in seconds, from the sound only. Returns (bpm, [times])."""
    import numpy as np
    ff = ve._ffmpeg()
    sr, n_fft, hop = 22050, 1024, 512
    r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-i", str(path), "-t", str(seconds),
                        "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True, **ve._no_window())
    x = np.frombuffer(r.stdout, dtype=np.float32)
    if len(x) < sr * 4:
        return 0.0, []
    frames = 1 + (len(x) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(frames)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * np.hanning(n_fft), axis=1))
    logs = np.log1p(spec * 20.0)
    diff = np.maximum(0.0, np.diff(logs, axis=0))
    k = max(3, int(0.5 * sr / hop))

    def onset(flux):
        flux = np.concatenate([[0.0], flux])
        e = np.maximum(0.0, flux - np.convolve(flux, np.ones(k) / k, mode="same"))
        return e / e.max() if e.max() > 0 else e

    low_bins = int(250 * n_fft / sr)                      # bass drum area, below about 250 Hz
    env = onset(diff[:, 1:low_bins].sum(axis=1)) + 0.35 * onset(diff.sum(axis=1))
    if env.max() <= 0:
        return 0.0, []
    env /= env.max()
    fps = sr / hop

    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 70)
    lags = np.arange(lo, hi + 1)
    bpm_axis = 60.0 * fps / lags
    prior = np.exp(-0.5 * (np.log2(bpm_axis / 118.0) / 0.55) ** 2)        # people like songs near 118 BPM
    best = int(lags[int(np.argmax(ac[lo:hi + 1] * prior))])

    top, top_score = None, -1.0
    for p in np.linspace(best * 0.96, best * 1.04, 81):                    # fine search of period and start
        for o in np.arange(0, p, 0.5):
            pos = np.round(o + p * np.arange(int((len(env) - o) // p))).astype(int)
            pos = pos[pos < len(env)]
            s = float(env[pos].sum()) / max(1, len(pos))
            if s > top_score:
                top, top_score = (p, o), s
    p, o = top
    bpm = 60.0 * fps / p
    n = int((len(env) - o) // p)
    beats = [round((o + p * i) / fps + BEAT_LATENCY, 3) for i in range(n)]
    return float(bpm), beats


def extend_beats(bpm: float, beats: list, until: float) -> list:
    """Continues the beat grid past the analysed part."""
    if not beats or bpm <= 0:
        return beats
    step = 60.0 / bpm
    out = list(beats)
    while out[-1] + step < until:
        out.append(round(out[-1] + step, 3))
    return out


def split_on_beats(segs: list, beats: list, bpm: float, every: int = BEAT_EVERY, min_gap: float = MIN_ZOOM_GAP) -> list:
    """Cuts the kept clips so that the zoom switches on the beat of the FINAL video.
    segs are source (start, end) pairs, played one after another, so the final time is the running total."""
    if not beats or bpm <= 0:
        return segs
    beat_len = 60.0 / bpm
    step = every if beat_len * every >= min_gap else every * 2
    marks = beats[::step]
    out, t0 = [], 0.0
    for a, b in segs:
        length = b - a
        inner = [m for m in marks if t0 + 0.5 < m < t0 + length - 0.5]
        cuts, last = [], 0.0
        for m in inner:                                   # keep the pieces at least min_gap long
            if m - t0 - last >= min_gap and (length - (m - t0)) >= 0.6:
                cuts.append(m - t0)
                last = m - t0
        pts = [0.0] + cuts + [length]
        for i in range(len(pts) - 1):
            out.append((round(a + pts[i], 3), round(a + pts[i + 1], 3)))
        t0 += length
    return out


# ================= mixing =================
def _graph(has_voice: bool, d: float, volume: float, normalize_arg: bool) -> str:
    fo = max(0.0, d - FADE_OUT)
    fades = f"afade=t=in:st=0:d={FADE_IN},afade=t=out:st={fo:.2f}:d={FADE_OUT}"
    fmt = "aformat=sample_rates=44100:channel_layouts=stereo"
    if not has_voice:
        return f"[1:a]{fmt},volume={MUSIC_ONLY_VOLUME},{fades},loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    mix_opts = "duration=first:dropout_transition=0" + (":normalize=0" if normalize_arg else "")
    return (f"[1:a]{fmt},volume={volume},{fades}[m];"
            f"[0:a]{fmt},asplit=2[v][sc];"
            f"[m][sc]sidechaincompress=threshold={DUCK_THRESHOLD}:ratio={DUCK_RATIO}:attack=10:release=350[duck];"
            f"[v][duck]amix=inputs=2:{mix_opts}[mix];"
            f"[mix]loudnorm=I=-14:TP=-1.5:LRA=11[a]")


def mix_music(video: Path, music: Path, out: Path, volume: float = MUSIC_VOLUME) -> Path:
    """Video stays untouched (no re-encode). Only the sound is mixed, so this takes seconds."""
    ff = ve._ffmpeg()
    info = ve.probe(str(video))
    d = info["duration"]
    loop = ["-stream_loop", "-1"] if duration(music) < d else []
    last = ""
    for normalize_arg in (True, False):                   # very old ffmpeg has no amix normalize option
        fc = _graph(info["audio"], d, volume, normalize_arg)
        cmd = ([ff, "-hide_banner", "-nostats", "-y", "-i", str(video)] + loop + ["-i", str(music),
               "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
               "-b:a", "192k", "-t", f"{d:.3f}", "-movflags", "+faststart", str(out)])
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", **ve._no_window())
        if r.returncode == 0 and out.exists():
            return out
        last = r.stderr
        if "normalize" not in last and "Option not found" not in last:
            break
    raise RuntimeError("ffmpeg failed: " + " | ".join(last.strip().splitlines()[-5:]))


# ================= tool for Guts =================
def _run_music(src: Path, music: Path):
    try:
        ve._set(msg=f"mixing the music ({music.stem})", pct=30)
        out = ve._unique_out(src, "music")
        mix_music(src, music, out)
        ve._set(state="done", pct=100, out=str(out), msg=f"Music '{music.stem}' added with voice ducking.")
        try:
            if sys.platform == "win32":
                os.startfile(str(ve.OUT_DIR))
        except Exception:
            pass
    except Exception as e:
        ve._set(state="failed", msg=str(e))


def video_add_music(path: str, music: str = "auto") -> str:
    """Add background music to a finished video. The music ducks under the voice. music: auto, part of a song name, or a path."""
    try:
        src = ve._check_video(path)
        if not ve._ffmpeg():
            return "ffmpeg is not installed. Tell Boss to run: winget install Gyan.FFmpeg   then restart Guts."
        song = pick_music(music)
        with ve._LOCK:
            if ve.JOB["state"] == "running":
                return "An edit is already running. Use video_status to see the progress."
            ve.JOB.update(state="running", msg="starting", out=None, t0=time.time(), pct=0)
        threading.Thread(target=_run_music, args=(src, song), daemon=True).start()
        return (f"Adding the song '{song.stem}' to {src.name}. It takes a few seconds. "
                "Use video_status to see when it is done.")
    except Exception as e:
        return f"Cannot start: {e}"


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] == "list":
        print(music_list())
    elif a[0] == "beats" and len(a) > 1:
        bpm, beats = detect_beats(pick_music(a[1]))
        print(f"Tempo: {bpm:.1f} BPM, {len(beats)} beats found. First beats (seconds): {beats[:12]}")
    else:
        print(ve.video_info(a[0]))
        print(video_add_music(a[0], a[1] if len(a) > 1 else "auto"))
        while ve.JOB["state"] == "running":
            time.sleep(1)
        print(ve.video_status())
