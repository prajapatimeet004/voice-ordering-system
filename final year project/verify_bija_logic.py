import sys
import os
import json

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from classifier_service import classify_order

def test_gujlish_quantity():
    print("--- Testing Gujlish Quantity: 'Burger bija be add karo' ---")
    
    transcript = "Burger bija be add karo"
    result = classify_order(transcript)
    
    print(f"Transcript: {transcript}")
    print(f"Pooja's Response: {result.get('response_text')}")
    
    for item in result.get("items", []):
        print(f"Item: {item['dish']}, Qty: {item['quantity']}, Modifier: {item['modifier']}")
        if item['modifier'] == "increase" and item['quantity'] == 2:
            print("✅ SUCCESS: Correct relative quantity and modifier detected.")
        else:
            print(f"❌ FAILURE: Unexpected result. Qty: {item['quantity']}, Modifier: {item['modifier']}")

if __name__ == "__main__":
    test_gujlish_quantity()
