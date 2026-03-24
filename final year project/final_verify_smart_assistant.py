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
    # Test a sequence on the same order
    # 1. Reset
    httpx.post("http://localhost:8000/order/reset")
    
    phrases = [
        "Masala Dosa aapo",             # State: {Masala Dosa: 1}
        "Masala Dosa ek vadhare aapo",  # State: {Masala Dosa: 2}
        "ek pav Masala Dosa aapo",      # State: {Masala Dosa: 2, quarter Masala Dosa: 1}
        "Samosa ane Pizza aapo",        # State: {M.D: 2, q.M.D: 1, Samosa: 1} - Pizza blocked
        "Samosa ek ochu karo"           # State: {M.D: 2, q.M.D: 1} - Samosa removed
    ]
    for p in phrases:
        test_phrase(p)
        time.sleep(2)
