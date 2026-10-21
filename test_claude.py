import os
from dotenv import load_dotenv
import anthropic

load_dotenv()
key = os.getenv("abhiraj-api-key")
print("key found:", bool(key))

client = anthropic.Anthropic(api_key=key)
r = client.messages.create(
    model="claude-sonnet-5-5",
    max_tokens=100,
    messages=[{"role": "user", "content": "Say hi in one Hinglish line"}],
)
print(r.content[0].text)