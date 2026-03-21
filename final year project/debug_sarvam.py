import os
from dotenv import load_dotenv
from sarvamai import SarvamAI
import json

load_dotenv()
api_key = os.getenv("SARVAM_API_KEY")
client = SarvamAI(api_subscription_key=api_key)

try:
    res = client.chat.completions(
        messages=[{"role": "user", "content": "ek samosa. output only JSON: {'items': [{'dish': 'samosa', 'quantity': 1, 'raw_addons': []}]}"}],
        temperature=0
    )
    print("Full Response Object:", res)
    print("Content:", res.choices[0].message.content)
except Exception as e:
    print("Error:", e)
