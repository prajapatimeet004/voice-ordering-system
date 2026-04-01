import sys
import os
import json

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from classifier_service import classify_order

def test_negative_add():
    print("--- Testing Negative Add: 'Burger add na karo' ---")
    
    transcript = "Burger add na karo"
    result = classify_order(transcript)
    
    print(f"Transcript: {transcript}")
    print(f"Pooja's Response: {result.get('response_text')}")
    
    for item in result.get("items", []):
        print(f"Item: {item['dish']}, Qty: {item['quantity']}, Modifier: {item['modifier']}")
        if item['modifier'] in ["decrease", "remove"]:
            print("✅ SUCCESS: Correct negative modifier detected for 'add na karo'.")
        else:
            print(f"❌ FAILURE: Unexpected results. Modifier should be 'decrease' or 'remove'. Got: {item['modifier']}")

if __name__ == "__main__":
    test_negative_add()
