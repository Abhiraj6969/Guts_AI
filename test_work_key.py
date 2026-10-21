import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
key = os.getenv("GEMINI_WORK_KEY")
print("key found:", bool(key))
client = genai.Client(api_key=key)

names = []
try:
    for m in client.models.list():
        n = m.name.replace("models/", "")
        acts = m.supported_actions or []
        bad = ("live", "tts", "image", "audio", "embedding")
        if "generateContent" in acts and "flash" in n and not any(b in n for b in bad):
            names.append(n)
except Exception as e:
    print("could not list models:", str(e)[:100])
names = names[:4] or ["gemini-3.8-flash"]
print("will try:", names)


def ask(prompt, config=None):
    for n in names:
        for attempt in range(3):
            try:
                r = client.models.generate_content(model=n, contents=prompt, config=config)
                print("[used model]", n)
                return r.text
            except Exception as e:
                print(f"[{n}] try {attempt + 1} failed: {str(e)[:90]}")
                time.sleep(3)
    return "All models failed."


print(ask("Write a Python function that adds two numbers. Code only."))
print("--- research test ---")
search = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
print(ask("What is today's date and one big tech news item from this week?", search))