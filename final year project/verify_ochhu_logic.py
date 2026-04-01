import sys
import os
import json

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from classifier_service import classify_order

def test_ochhu_quantity():
    print("--- Testing Gujlish Decrease: 'ek burger ochhu karo' ---")
    
    transcript = "ek burger ochhu karo"
    result = classify_order(transcript)
    
    print(f"Transcript: {transcript}")
    print(f"Pooja's Response: {result.get('response_text')}")
    
    for item in result.get("items", []):
        print(f"Item: {item['dish']}, Qty: {item['quantity']}, Modifier: {item['modifier']}")
        if item['modifier'] == "decrease" and item['quantity'] == 1:
            print("✅ SUCCESS: Correct decrease modifier detected.")
        else:
            print(f"❌ FAILURE: Unexpected results. Qty: {item['quantity']}, Modifier: {item['modifier']}")

if __name__ == "__main__":
    test_ochhu_quantity()
