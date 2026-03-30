import requests
import json

def test_optimized_classification():
    print("\n--- Testing Optimized Classification (Samosa + Masala Dosa) ---")
    url = "http://localhost:8000/order/classify"
    # Samosa (2 in stock), Masala Dosa (0 in stock)
    payload = {
        "transcript": "2 samosa and 1 masala dosa"
    }
    
    response = requests.post(url, data=payload)
    if response.status_code == 200:
        data = response.json()
        print("Response Text:", data.get("response_text"))
        print("Confirmed Order:", json.dumps(data.get("current_order"), indent=2))
        
        # Check if Samosa is in cart and Masala Dosa is NOT
        cart = data.get("current_order", {})
        if "Samosa" in cart and "Masala Dosa" not in cart:
            print("✅ SUCCESS: Samosa added, Masala Dosa skipped.")
        else:
            print("❌ FAILURE: Cart state incorrect.")
            
        # Check for availability message
        resp_text = data.get("response_text", "").lower()
        if "masala dosa available nathi" in resp_text:
            print("✅ SUCCESS: Availability message generated in Python.")
        else:
            print("❌ FAILURE: Missing availability message.")
    else:
        print(f"FAILED: {response.text}")

if __name__ == "__main__":
    test_optimized_classification()
