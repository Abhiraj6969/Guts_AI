"""voice_id.py - offline voice recognition for Guts (who is speaking: Boss, a friend, or a stranger).

Nothing is sent to the internet. Only the first run downloads a small model (about 26 MB).
Voice fingerprints are saved in the 'voices' folder next to this file.

Commands (run in the Guts_AI folder, with Guts STOPPED so the mic is free):
  python voice_id.py enroll boss      -> record Boss's voice (about 40 seconds)
  python voice_id.py enroll jagrit    -> record a friend's voice (optional)
  python voice_id.py test             -> live test: shows who it thinks is speaking
  python voice_id.py list             -> show saved voices
"""
import re
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
MODEL_DIR = BASE / "models"
MODEL_FILE = MODEL_DIR / "wespeaker_en_voxceleb_resnet34.onnx"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
             "speaker-recongition-models/wespeaker_en_voxceleb_resnet34.onnx")
VOICE_DIR = BASE / "voices"

RATE = 16000
CHUNK = 1024
THRESHOLD = 0.55     # score at or above this = known voice, below = stranger (tune with 'test')
MIN_RMS = 0.01       # quieter than this counts as silence

_EXTRACTOR = None


# ================= MODEL =================
def ensure_model():
    if MODEL_FILE.exists():
        return
    MODEL_DIR.mkdir(exist_ok=True)
    tmp = MODEL_FILE.with_suffix(".part")
    print("[Voice] Downloading the voice model (about 26 MB), please wait ...")
    try:
        urllib.request.urlretrieve(MODEL_URL, tmp)
        tmp.rename(MODEL_FILE)
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"Could not download the model: {e}\n"
                           f"Download it by hand from {MODEL_URL}\n"
                           f"and put the file in {MODEL_DIR}")
    print("[Voice] Model ready.")


def _extractor():
    global _EXTRACTOR
    if _EXTRACTOR is None:
        import sherpa_onnx
        ensure_model()
        cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(MODEL_FILE), num_threads=2, debug=False, provider="cpu")
        if not cfg.validate():
            raise RuntimeError("Voice model config is not valid. Delete the models folder and run again.")
        _EXTRACTOR = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
    return _EXTRACTOR


# ================= CORE FUNCTIONS (Guts will use these later) =================
def pcm_to_float(pcm: bytes) -> np.ndarray:
    """16-bit mic bytes -> float samples between -1 and 1."""
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(samples ** 2))) if len(samples) else 0.0


def embed(samples: np.ndarray) -> np.ndarray:
    """Voice fingerprint (256 numbers, length 1) of a clip of speech."""
    ex = _extractor()
    s = ex.create_stream()
    s.accept_waveform(sample_rate=RATE, waveform=samples.astype(np.float32))
    s.input_finished()
    v = np.array(ex.compute(s), dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def load_voices() -> dict:
    voices = {}
    if VOICE_DIR.exists():
        for f in sorted(VOICE_DIR.glob("*.npy")):
            voices[f.stem] = np.load(f)
    return voices


def score_all(emb: np.ndarray, voices: dict) -> dict:
    return {name: float(np.dot(emb, v)) for name, v in voices.items()}


def identify(emb: np.ndarray, voices: dict):
    """Returns (name, score). name is 'stranger' when nobody matches well enough."""
    scores = score_all(emb, voices)
    if not scores:
        return "stranger", 0.0
    best = max(scores, key=scores.get)
    if scores[best] >= THRESHOLD:
        return best, scores[best]
    return "stranger", scores[best]


# ================= MICROPHONE =================
def _open_mic():
    import pyaudio
    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True,
                     frames_per_buffer=CHUNK)
    return pa, stream


def record(stream, seconds: float) -> np.ndarray:
    frames = []
    for _ in range(int(RATE / CHUNK * seconds)):
        frames.append(stream.read(CHUNK, exception_on_overflow=False))
    return pcm_to_float(b"".join(frames))


# ================= ENROLL =================
PROMPTS = [
    "Guts, aaj ka plan kya hai? Mujhe PC ka status batao.",
    "Notepad kholo aur Desktop ki files dikhao.",
    "Ek se das tak ginti karo: ek, do, teen, char, paanch, chhe, saat, aath, nau, das.",
    "Aaj mausam kaisa hai, aur kya naya chal raha hai?",
    "Guts, WhatsApp pe message bhejo aur koi achha gaana chalao.",
]
CLIP_SECONDS = 7


def enroll(name: str):
    name = re.sub(r"[^a-z0-9_]", "", name.lower())
    if not name:
        print("Give a name, for example: python voice_id.py enroll boss")
        return
    _extractor()                      # load (and download) the model first
    pa, stream = _open_mic()
    print(f"\nEnrolling voice: {name}")
    print("Tips: quiet room, your normal voice, same mic you use for Guts, no music.")
    print("Speak the line shown (or anything natural) for the full 7 seconds.\n")
    embs = []
    try:
        for i, line in enumerate(PROMPTS, 1):
            for attempt in range(3):
                print(f"Clip {i}/{len(PROMPTS)}: say something like:  \"{line}\"")
                for n in (3, 2, 1):
                    print(f"  starting in {n} ...")
                    time.sleep(1)
                print("  >>> SPEAK NOW <<<")
                clip = record(stream, CLIP_SECONDS)
                level = rms(clip)
                print(f"  done (loudness {level:.3f})")
                if level < MIN_RMS * 1.5:
                    print("  Too quiet. Let's try this clip again.\n")
                    continue
                embs.append(embed(clip))
                print()
                break
            else:
                print("Your mic is too quiet. Check the microphone in Windows settings and try again.")
                return
    finally:
        stream.close()
        pa.terminate()

    # how similar are the clips to each other? (a clean recording scores high)
    sims = [float(np.dot(embs[a], embs[b])) for a in range(len(embs)) for b in range(a + 1, len(embs))]
    avg = sum(sims) / len(sims) if sims else 1.0
    print(f"Consistency between your clips: {avg:.2f} (above 0.60 is good)")
    if avg < 0.45:
        print("WARNING: the clips do not match each other well. Too much noise? Try enrolling again.")

    mean = np.mean(embs, axis=0)
    mean = (mean / (np.linalg.norm(mean) + 1e-9)).astype(np.float32)
    VOICE_DIR.mkdir(exist_ok=True)
    np.save(VOICE_DIR / f"{name}.npy", mean)
    print(f"\nSaved voice '{name}' in {VOICE_DIR}")
    print("Next: python voice_id.py test")


# ================= TEST =================
def test():
    voices = load_voices()
    if not voices:
        print("No voices saved yet. First run: python voice_id.py enroll boss")
        return
    _extractor()
    pa, stream = _open_mic()
    print(f"Known voices: {', '.join(voices)}   (threshold {THRESHOLD})")
    print("Speak in 3-second windows. Ctrl+C to stop.")
    print("Test 1: you talk normally.  Test 2: a friend or family member talks.  Test 3: play a YouTube video.\n")
    try:
        while True:
            clip = record(stream, 3)
            level = rms(clip)
            stamp = time.strftime("%H:%M:%S")
            if level < MIN_RMS:
                print(f"{stamp}  (quiet)")
                continue
            scores = score_all(embed(clip), voices)
            best = max(scores, key=scores.get)
            verdict = best.upper() if scores[best] >= THRESHOLD else "STRANGER"
            detail = " | ".join(f"{n} {s:.2f}" for n, s in scores.items())
            print(f"{stamp}  {verdict:<9} {detail}   (loudness {level:.3f})")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        stream.close()
        pa.terminate()


def list_voices():
    v = load_voices()
    print("Saved voices: " + (", ".join(v) if v else "none"))


if __name__ == "__main__":
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    if cmd == "enroll":
        enroll(sys.argv[2] if len(sys.argv) > 2 else "")
    elif cmd == "test":
        test()
    elif cmd == "list":
        list_voices()
    else:
        print(__doc__)
