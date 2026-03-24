import httpx
import json
import time

def test_phrase(phrase):
    print(f"\n--- Phrase: {phrase} ---")
    url = "http://localhost:8000/order/classify"
    try:
        response = httpx.post(url, data={"transcript": phrase}, timeout=30.0)
        if response.status_code == 200:
            data = response.json()
            print(f"Response Text: {data.get('response_text')}")
            print(f"Classification: {json.dumps(data.get('classification'), indent=2)}")
            if data.get('speech'):
                print("✅ Speech generated.")
            else:
                print("❌ No speech generated.")
        else:
            print(f"Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Connection Error: {e}")

if __name__ == "__main__":
    phrases = [
        "menu batavo",
        "Paneer Tikka available che?",
        "ek Samosa aapo",
        "be loko mate table joie",
        "jamvanu thandu che"
    ]
    for p in phrases:
        test_phrase(p)
        time.sleep(2)
