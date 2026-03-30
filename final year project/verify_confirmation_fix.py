import requests
import json

def test_confirmation_fix():
    url = "http://localhost:8000/order/classify"
    payload = {
        "transcript": "Ajwa chawal teekha mat rakhna"
    }
    
    print(f"Sending transcript: {payload['transcript']}")
    response = requests.post(url, data=payload)
    
    if response.status_code == 200:
        data = response.json()
        print("\nResponse Text:")
        print(data.get("response_text"))
        
        classification = data.get("classification", {})
        needs_confirm = classification.get("needs_confirmation", [])
        print("\nNeeds Confirmation:")
        print(json.dumps(needs_confirm, indent=2))
        
        if "Rajma Chawal" in data.get("response_text") and "Ajwa chawal" in data.get("response_text"):
            print("\n✅ SUCCESS: Confirmation message correctly generated and not clobbered.")
        else:
            print("\n❌ FAILURE: Confirmation message missing or incorrect.")
    else:
        print(f"Error: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    test_confirmation_fix()
