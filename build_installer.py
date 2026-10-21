"""build_installer.py - turns your Guts_AI folder into GutsSetup-x.y.z.exe that installs on ANY Windows PC.

Run it on YOUR Windows PC, in the Guts_AI folder (Python 3.11, same one you use for Guts):
  python -m pip install pyinstaller
  winget install JRSoftware.InnoSetup           (the program that makes the installer; optional, a zip is made without it)
  python build_installer.py

  python build_installer.py --stage-only        only prepare and CHECK the clean files (fast, no exe, safe to try first)
  python build_installer.py --no-models         do not put the face and wake-word models inside (smaller installer)
  python build_installer.py --version 1.1.0

What it does:
  1. finds your newest live_voice_N.py and every helper file it really needs (no tests, no old versions)
  2. copies ONLY those into build\\stage\\app, NEVER your personal files (.env keys, contacts, your face, profile,
     projects, logs, Packet Tracer calibration) and stops if one slips in
  3. makes Guts personal: name, language, personality, face lock, browser and camera come from settings
  4. builds Guts.exe (PyInstaller, no console window) and tests that every library is inside it
  5. builds GutsSetup-x.y.z.exe with Inno Setup (per-user install, no admin needed), plus a portable zip
"""
import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
BUILD = BASE / "build"
VERSION = "1.0.0"

PERSONAL_FILES = {".env", "guts_user_profile.json", "contacts.json", "boss_face.npy", "pt_clicks.json",
                  "guts.log", "guts.old.log", "guts.pid", "guts_settings.json", "selftest.txt", "avatar_state.json",
                  "avatar_cmd.json"}
PERSONAL_DIRS = {"projects", "__pycache__", "build", "guts_env", ".git"}
NEVER_COPY_PREFIXES = ("test_", "apply_", "pt_check", "quota_check", "diagnose_key", "check_models", "live_test",
                       "build_installer", "start_guts", "autostart", "guts_launcher")
ALWAYS = ("guts_settings.py", "guts_setup.py", "guts_avatar.py", "guts_bridge.py")
MODEL_FILES = ("face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx")
VOSK_DIR = "vosk-model-small-en-us-0.15"

# libraries that need their data files or DLLs inside the exe
COLLECT_ALL = ["vosk", "yt_dlp", "google.genai", "pyautogui", "pygetwindow", "pyscreeze", "pymsgbox",
               "pytweening", "certifi"]
EXTRA_HIDDEN = ["websockets", "httpx", "anyio", "pydantic", "requests", "google.auth", "tkinter",
                "tkinter.ttk", "tkinter.scrolledtext", "tkinter.messagebox", "tkinter.simpledialog", "PIL.ImageTk", "PIL.ImageGrab",
                "PIL.ImageStat"]

ISS = r"""#define AppName "Guts AI"
[Setup]
AppId={{6F2B1D84-3C7A-4E59-A0B1-5D9C2E7F4A31}
AppName={#AppName}
AppVersion=__VERSION__
AppPublisher=Guts AI
DefaultDirName={localappdata}\Programs\Guts AI
DefaultGroupName=Guts AI
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=__OUTDIR__
OutputBaseFilename=GutsSetup-__VERSION__
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\Guts.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "stopicon"; Description: "Create a 'Stop Guts' shortcut on the desktop too"; GroupDescription: "Shortcuts:"

[Files]
Source: "__PAYLOAD__\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Guts AI"; Filename: "{app}\Guts.exe"
Name: "{autoprograms}\Guts AI - Stop"; Filename: "{app}\Guts.exe"; Parameters: "--stop"
Name: "{autoprograms}\Guts AI - Status"; Filename: "{app}\Guts.exe"; Parameters: "--status"
Name: "{autoprograms}\Guts AI - Setup again"; Filename: "{app}\Guts.exe"; Parameters: "--setup"
Name: "{autodesktop}\Guts AI"; Filename: "{app}\Guts.exe"; Tasks: desktopicon
Name: "{autodesktop}\Stop Guts"; Filename: "{app}\Guts.exe"; Parameters: "--stop"; Tasks: stopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "GutsAI"; Flags: dontcreatekey uninsdeletevalue

[Run]
Filename: "{app}\Guts.exe"; Parameters: "--setup --run-after"; Description: "Set up Guts now (your name, key, face)"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\Guts.exe"; Parameters: "--stop"; Flags: runhidden

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app\__pycache__"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if MsgBox('Also delete your personal Guts data (keys, contacts, your face, settings, projects)?',
              mbConfirmation, MB_YESNO) = IDYES then
    begin
      DeleteFile(ExpandConstant('{app}\app\.env'));
      DeleteFile(ExpandConstant('{app}\app\contacts.json'));
      DeleteFile(ExpandConstant('{app}\app\boss_face.npy'));
      DeleteFile(ExpandConstant('{app}\app\guts_settings.json'));
      DeleteFile(ExpandConstant('{app}\app\guts_user_profile.json'));
      DeleteFile(ExpandConstant('{app}\app\guts.log'));
      DeleteFile(ExpandConstant('{app}\app\guts.old.log'));
      DelTree(ExpandConstant('{app}\app\projects'), True, True, True);
    end;
  end;
end;
"""


# ================= scanning =================
def imports_of(path: Path) -> set:
    """Every module a file imports (also inside functions), as dotted names; google.x kept as google.x."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module != "google":
                out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names if a.name != "*")
    return out


def newest_main(folder: Path):
    best = None
    for p in folder.glob("live_voice_*.py"):
        m = re.fullmatch(r"live_voice_(\d+)\.py", p.name)
        if m and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), p)
    return best


def local_closure(main: Path, folder: Path) -> list:
    seen, stack = {}, [main]
    while stack:
        p = stack.pop()
        for mod in imports_of(p):
            top = mod.split(".")[0]
            f = folder / f"{top}.py"
            if f.exists() and f not in seen and f != main and not f.name.startswith(NEVER_COPY_PREFIXES):
                seen[f] = True
                stack.append(f)
    return sorted(seen)


def needed_modules(files: list, local_names: set):
    """(third_party, standard) module names the plain-source Guts files import.
    PyInstaller only sees what Guts.exe itself imports, so EVERYTHING the Guts files use must be listed."""
    std_names = set(sys.stdlib_module_names)
    third, std = set(), set()
    for f in files:
        for mod in imports_of(f):
            top = mod.split(".")[0]
            if top in local_names:
                continue
            if top in std_names:
                std.add(mod)
            else:
                third.add(mod if mod.startswith("google.") else top)
    return sorted(third), sorted(std)


def installed(mod: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def personal_warnings(app: Path) -> list:
    """Text that looks like it belongs to you. Warnings only, you decide."""
    warns = []
    pats = [(re.compile(r"abhiraj", re.I), "your name"),
            (re.compile(r"(?<![\w.])\d{10,13}(?![\w.])"), "a phone-number-like number"),
            (re.compile(r"C:\\\\?Users\\\\?[A-Za-z]"), "a C:\\Users path")]
    for f in sorted(app.glob("*.py")):
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for pat, what in pats:
                if pat.search(line):
                    warns.append(f"{f.name}:{i}  {what}:  {line.strip()[:90]}")
    return warns


# ================= staging =================
def stage(folder: Path, out: Path, with_models: bool) -> dict:
    sys.path.insert(0, str(folder))
    import apply_settings_patch as sp

    found = newest_main(folder)
    if not found:
        raise SystemExit("No live_voice_N.py found in this folder.")
    n, main = found
    if out.exists():
        shutil.rmtree(out)
    app = out / "app"
    app.mkdir(parents=True)

    report = {"main": main.name, "number": n, "files": [], "notes": [], "models": []}
    patched, notes = sp.patch_main(main.read_text(encoding="utf-8"))
    if patched is None:
        raise SystemExit("Could not make the main file personal: " + "; ".join(notes) +
                         "\nSend me this message and your newest live_voice file.")
    (app / "guts_main.py").write_text(patched, encoding="utf-8")
    report["notes"] += [f"main: {x}" for x in notes]

    files = local_closure(main, folder)
    for name in ALWAYS:
        p = folder / name
        if not p.exists():
            raise SystemExit(f"{name} is missing from this folder. Put it next to build_installer.py.")
        if p not in files:
            files.append(p)
    for f in files:
        text = f.read_text(encoding="utf-8")
        if f.name == "pc_tools.py":
            text, nn = sp.patch_pc_tools(text)
            report["notes"] += [f"pc_tools: {x}" for x in nn]
        elif f.name == "face_guard.py":
            text, nn = sp.patch_face_guard(text)
            report["notes"] += [f"face_guard: {x}" for x in nn]
        (app / f.name).write_text(text, encoding="utf-8")
        report["files"].append(f.name)

    if with_models:
        for m in MODEL_FILES:
            if (folder / m).exists():
                shutil.copy2(folder / m, app / m)
                report["models"].append(m)
        if (folder / VOSK_DIR).is_dir():
            shutil.copytree(folder / VOSK_DIR, app / VOSK_DIR)
            report["models"].append(VOSK_DIR)

    local_names = {p.stem for p in app.glob("*.py")} | {"guts_main"}
    third, std = needed_modules(sorted(app.glob("*.py")), local_names)
    keep_third = [m for m in third if installed(m)]
    keep_std = [m for m in std if installed(m)]
    report["skipped"] = [m for m in third if m not in keep_third]
    report["third"], report["std_count"] = keep_third, len(keep_std)
    report["deps"] = keep_third + keep_std                    # the exe must contain all of these
    (app / "_deps.json").write_text(json.dumps(report["deps"], indent=2), encoding="utf-8")

    leaked = [p.name for p in app.rglob("*") if p.name in PERSONAL_FILES or
              (p.is_dir() and p.name in PERSONAL_DIRS)]
    if leaked:
        raise SystemExit("STOP: personal files ended up in the installer: " + ", ".join(leaked))
    report["warnings"] = personal_warnings(app)
    return report


# ================= exe + installer =================
def build_exe(app_stage: Path, deps: list) -> Path:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit("PyInstaller is not installed. Run: python -m pip install pyinstaller")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "Guts",
           "--distpath", str(BUILD / "dist"), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD)]
    icon = BASE / "guts.ico"
    if icon.exists():
        cmd += ["--icon", str(icon)]
    for m in sorted(set(deps) | set(EXTRA_HIDDEN)):
        cmd += ["--hidden-import", m]
    for m in COLLECT_ALL:
        cmd += ["--collect-all", m]
    cmd.append(str(BASE / "guts_launcher.py"))
    print("\n[Build] PyInstaller (this takes several minutes) ...")
    r = subprocess.run(cmd)
    exe = BUILD / "dist" / "Guts" / "Guts.exe"
    if r.returncode != 0 or not exe.exists():
        raise SystemExit("PyInstaller failed. Read the red lines above and send them to me.")
    return BUILD / "dist" / "Guts"


def selftest(payload: Path) -> list:
    print("[Build] Self-test: does the exe contain every library? ...")
    subprocess.run([str(payload / "Guts.exe"), "--selftest"], timeout=300,
                   env={**__import__("os").environ, "GUTS_APP_DIR": str(payload / "app")})
    f = payload / "app" / "selftest.txt"
    if not f.exists():
        return ["selftest.txt was not created (the exe did not start?)"]
    lines = f.read_text(encoding="utf-8").splitlines()
    f.unlink()
    return [l for l in lines if l.startswith("FAIL")]


def find_iscc():
    for p in (r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe",
              str(Path.home() / "AppData/Local/Programs/Inno Setup 6/ISCC.exe")):
        if Path(p).exists():
            return p
    return shutil.which("ISCC")


def make_installer(payload: Path, version: str):
    out = BUILD / "installer"
    out.mkdir(parents=True, exist_ok=True)
    iss = BUILD / "guts_installer.iss"
    iss.write_text(ISS.replace("__VERSION__", version).replace("__OUTDIR__", str(out))
                   .replace("__PAYLOAD__", str(payload)), encoding="utf-8")
    zip_path = shutil.make_archive(str(out / f"GutsPortable-{version}"), "zip", payload)
    print(f"[Build] Portable zip: {zip_path}")
    iscc = find_iscc()
    if not iscc:
        print("[Build] Inno Setup not found, so no setup.exe yet. Install it:  winget install JRSoftware.InnoSetup\n"
              f"        then compile {iss} (right click, Compile) or run this script again.")
        return None
    r = subprocess.run([iscc, str(iss)])
    exe = out / f"GutsSetup-{version}.exe"
    return exe if r.returncode == 0 and exe.exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage-only", action="store_true")
    ap.add_argument("--no-models", action="store_true")
    ap.add_argument("--version", default=VERSION)
    ap.add_argument("--skip-selftest", action="store_true")
    ap.add_argument("--folder", default=str(BASE))
    a = ap.parse_args()
    folder = Path(a.folder).resolve()
    stage_dir = BUILD / "stage"
    rep = stage(folder, stage_dir, not a.no_models)

    print(f"\n[Stage] Main file: {rep['main']} -> guts_main.py")
    print(f"[Stage] {len(rep['files'])} Guts files: {', '.join(rep['files'])}")
    print(f"[Stage] Models inside: {', '.join(rep['models']) or 'none (downloaded on first use)'}")
    print(f"[Stage] Libraries the exe must contain: {', '.join(rep['third'])}  (+ {rep['std_count']} standard modules)")
    if rep["skipped"]:
        print(f"[Stage] Not installed on this PC, so left out (fine if optional): {', '.join(rep['skipped'])}")
    for n in rep["notes"]:
        print(f"[Stage]   {n}")
    print("[Stage] No personal files inside: .env, contacts, your face, profile, projects, logs are NOT copied.")
    if rep["warnings"]:
        print("\n[CHECK] These lines look personal. Open them and change them if they are yours:")
        for w in rep["warnings"][:25]:
            print("   ", w)
    if a.stage_only:
        print(f"\nStage-only done. Look inside {stage_dir / 'app'}")
        return

    dist = build_exe(stage_dir / "app", rep["deps"])
    payload = BUILD / "payload"
    if payload.exists():
        shutil.rmtree(payload)
    shutil.copytree(dist, payload)
    shutil.copytree(stage_dir / "app", payload / "app")
    if not a.skip_selftest:
        bad = selftest(payload)
        if bad:
            print("\n[Build] SELF-TEST FOUND MISSING LIBRARIES:")
            for b in bad:
                print("   ", b)
            print("Send me these lines. The installer was NOT made.")
            sys.exit(1)
        print("[Build] Self-test passed.")
    exe = make_installer(payload, a.version)
    print("\n" + "=" * 66)
    print(f"Installer : {exe}" if exe else "Installer : not made (see message above)")
    print(f"Portable  : {BUILD / 'installer' / ('GutsPortable-' + a.version + '.zip')}")
    print("=" * 66)
    print("Test it on ANOTHER Windows account or a clean PC before you share it.")


if __name__ == "__main__":
    main()
