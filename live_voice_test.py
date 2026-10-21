import os
import time
import asyncio
import subprocess
from pathlib import Path
from urllib.parse import quote

import psutil
import pyaudio
import pyautogui
from dotenv import load_dotenv
from google import genai
from google.genai import types

try:
    import pygetwindow as gw
except Exception:
    gw = None

# ================= 1. SETUP =================
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MODEL = "gemini-3.8-live"
SEND_RATE = 16000   # mic
RECV_RATE = 24000   # Guts voice
CHUNK = 1024
HOME = Path.home()

SYSTEM = (
    "You are Guts, Boss's loyal Giga Chad best friend. Speak natural Hinglish, "
    "1-3 short sentences, witty and warm. Call him 'Boss'. Never say 'As an AI'. "
    "IMPORTANT: When Boss asks about his PC status, current window, or his files, "
    "you MUST call the matching tool first and answer using the real result. "
    "Never guess or make up PC information. "
    "When Boss asks to open an app, call open_app. "
    "When Boss asks to message someone on WhatsApp, call send_whatsapp. "
    "If a tool returns an error, say the error in one short sentence."
)


# ================= 2. SAFE READ-ONLY TOOLS =================
def get_system_status() -> str:
    """CPU, RAM and battery of Boss's PC."""
    b = psutil.sensors_battery()
    bat = f"{b.percent}% ({'charging' if b.power_plugged else 'on battery'})" if b else "Desktop"
    return f"CPU {psutil.cpu_percent()}%, RAM {psutil.virtual_memory().percent}%, Battery {bat}"


def get_active_window() -> str:
    """Which app or window Boss is using right now."""
    try:
        return (gw.getActiveWindowTitle() if gw else None) or "Unknown"
    except Exception:
        return "Unknown"


def list_folder(name: str = "Desktop") -> str:
    """List files in one of Boss's folders: Desktop, Documents or Downloads."""
    allowed = {"desktop": "Desktop", "documents": "Documents", "downloads": "Downloads"}
    key = allowed.get(name.lower())
    if not key:
        return "I can only list Desktop, Documents or Downloads."
    folder = HOME / key
    if not folder.exists():
        folder = HOME / "OneDrive" / key
    try:
        items = sorted(os.listdir(folder))[:40]
        return "\n".join(items) or "(empty)"
    except Exception as e:
        return f"List error: {e}"


# ================= 3. APP LAUNCHER (fixed allowed list) =================
APPS = {
    "notepad": "notepad",
    "calculator": "calc",
    "chrome": "chrome",
    "whatsapp": "whatsapp:",
    "vscode": "code",
    "explorer": "explorer",
}


def open_app(name: str) -> str:
    """Open an app from the allowed list."""
    target = APPS.get(name.lower().strip())
    if not target:
        return f"I can only open: {', '.join(APPS)}"
    try:
        subprocess.Popen(f'start "" {target}', shell=True)
        return f"Opened {name}"
    except Exception as e:
        return f"Could not open {name}: {e}"


# ================= 4. WHATSAPP (with confirmation) =================
CONTACTS = {
    "jagrit": "919899920413",   # country code + number, digits only
    "mummy": "918796682083",
    "ira": "919868412456",
    "vridhi": "919350347268",
    "mahek": "919582402991",
}


def confirm(question: str) -> bool:
    print(f"\n[CONFIRM] {question}")
    return input("Allow? (y/n): ").strip().lower() == "y"


def send_whatsapp(contact: str, message: str) -> str:
    """Send a WhatsApp message to a saved contact."""
    phone = CONTACTS.get(contact.lower().strip())
    if not phone:
        return f"I only know these contacts: {', '.join(CONTACTS)}"
    if not confirm(f"Send WhatsApp to {contact}: '{message}'"):
        return "Boss said no. Message NOT sent."
    try:
        os.startfile(f"whatsapp://send?phone={phone}&text={quote(message)}")
        time.sleep(6)
        pyautogui.press("enter")
        return f"Message sent to {contact}"
    except Exception as e:
        return f"WhatsApp error: {e}"


# ================= 5. TOOL REGISTRY =================
# Every tool must appear in BOTH places: TOOL_FUNCS (the code) and TOOL_DECLS (what Gemini sees).
TOOL_FUNCS = {
    "get_system_status": get_system_status,
    "get_active_window": get_active_window,
    "list_folder": list_folder,
    "open_app": open_app,
    "send_whatsapp": send_whatsapp,
}

TOOL_DECLS = [types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="get_system_status",
        description="Get CPU, RAM and battery status of Boss's PC.",
    ),
    types.FunctionDeclaration(
        name="get_active_window",
        description="Get the title of the window Boss is currently using.",
    ),
    types.FunctionDeclaration(
        name="list_folder",
        description="List files in Boss's Desktop, Documents or Downloads folder.",
        parameters=types.Schema(
            type="OBJECT",
            properties={"name": types.Schema(type="STRING", description="Desktop, Documents or Downloads")},
        ),
    ),
    types.FunctionDeclaration(
        name="open_app",
        description="Open an app on Boss's PC: notepad, calculator, chrome, whatsapp, vscode or explorer.",
        parameters=types.Schema(
            type="OBJECT",
            properties={"name": types.Schema(type="STRING", description="App name from the allowed list")},
            required=["name"],
        ),
    ),
    types.FunctionDeclaration(
        name="send_whatsapp",
        description="Send a WhatsApp message to a saved contact. Boss will be asked to confirm.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "contact": types.Schema(type="STRING", description="Contact name, e.g. jagrit"),
                "message": types.Schema(type="STRING", description="Message text to send"),
            },
            required=["contact", "message"],
        ),
    ),
])]


# ================= 6. AUDIO + LIVE SESSION =================
pya = pyaudio.PyAudio()


async def send_mic(session):
    stream = pya.open(format=pyaudio.paInt16, channels=1, rate=SEND_RATE,
                      input=True, frames_per_buffer=CHUNK)
    while True:
        data = await asyncio.to_thread(stream.read, CHUNK, False)
        await session.send_realtime_input(
            audio=types.Blob(data=data, mime_type=f"audio/pcm;rate={SEND_RATE}")
        )


async def play_replies(session):
    out = pya.open(format=pyaudio.paInt16, channels=1, rate=RECV_RATE, output=True)
    while True:
        async for msg in session.receive():
            # --- run tools requested by Gemini ---
            if msg.tool_call:
                responses = []
                for fc in msg.tool_call.function_calls:
                    print(f"[Tool]: {fc.name} {dict(fc.args or {})}")
                    try:
                        result = await asyncio.to_thread(TOOL_FUNCS[fc.name], **(fc.args or {}))
                    except Exception as e:
                        print(f"[Tool ERROR]: {fc.name} -> {e!r}")
                        result = f"Error: {e}"
                    responses.append(types.FunctionResponse(
                        id=fc.id, name=fc.name, response={"result": result}))
                await session.send_tool_response(function_responses=responses)

            # --- play Guts's voice ---
            if msg.data:
                await asyncio.to_thread(out.write, msg.data)

            # --- print transcripts ---
            sc = msg.server_content
            if sc and sc.input_transcription and sc.input_transcription.text:
                print(f"[Boss]: {sc.input_transcription.text}")
            if sc and sc.output_transcription and sc.output_transcription.text:
                print(f"[Guts]: {sc.output_transcription.text}")


async def main():
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=SYSTEM,
        tools=TOOL_DECLS,
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    async with client.aio.live.connect(model=MODEL, config=config) as session:
        print("Guts is live. Talk to him. Press Ctrl+C to stop.")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(send_mic(session))
            tg.create_task(play_replies(session))


try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("\nStopped.")