import httpx
import json
import base64
import os
import winsound

BASE_URL = "http://127.0.0.1:8000"

def test_flow():
    # 1. Reset
    print("\n--- Resetting Order ---")
    httpx.post(f"{BASE_URL}/order/reset")

    # 2. Add Item
    print("\n--- Testing: 'ek masala dosa' ---")
    payload = {"transcript": "ek masala dosa"}
    res = httpx.post(f"{BASE_URL}/order/classify", data=payload, timeout=60.0)
    data = res.json()
    print("Response Text:", data["response_text"])
    if data["speech"]:
        print(f"Speech received (base64 length: {len(data['speech'])})")
        with open("res_dosa.wav", "wb") as f:
            f.write(base64.b64decode(data["speech"]))
        print("Saved to res_dosa.wav. Playing...")
        winsound.PlaySound("res_dosa.wav", winsound.SND_FILENAME)

    # 3. Add Another (needs confirmation)
    print("\n--- Testing: 'ane ek mohan josh' ---")
    payload = {"transcript": "ane ek mohan josh"}
    res = httpx.post(f"{BASE_URL}/order/classify", data=payload, timeout=60.0)
    data = res.json()
    print("Response Text:", data["response_text"])

    # 4. Confirm it
    print("\n--- Testing: 'haan' (Affirmative) ---")
    payload = {"transcript": "haan"}
    res = httpx.post(f"{BASE_URL}/order/classify", data=payload, timeout=60.0)
    data = res.json()
    print("Response Text:", data["response_text"])
    if data["speech"]:
        winsound.PlaySound(base64.b64decode(data["speech"]), winsound.SND_MEMORY)
    print("Current Order:", data["current_order"])

    # 5. Finish Order
    print("\n--- Testing: 'bas itna hi' (Finish) ---")
    payload = {"transcript": "bas itna hi"}
    res = httpx.post(f"{BASE_URL}/order/classify", data=payload, timeout=60.0)
    data = res.json()
    print("Response Text:", data["response_text"])
    print("Is Finished:", data["is_finished"])
    if data["speech"]:
        with open("res_final.wav", "wb") as f:
            f.write(base64.b64decode(data["speech"]))
        print("Saved final summary to res_final.wav. Playing...")
        winsound.PlaySound("res_final.wav", winsound.SND_FILENAME)

if __name__ == "__main__":
    test_flow()
