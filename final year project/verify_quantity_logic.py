import sys
import os
import json

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from classifier_service import classify_order

def test_quantity_increment():
    print("--- Testing Quantity Increment: 'add one more burger' ---")
    
    # We simulate the LLM's potential output or just test the server logic directly if needed.
    # But let's check what the LLM actually produces with the NEW prompt.
    transcript = "add one more burger"
    result = classify_order(transcript)
    
    print(f"Transcript: {transcript}")
    print(f"Pooja's Response: {result.get('response_text')}")
    
    for item in result.get("items", []):
        print(f"Item: {item['dish']}, Qty: {item['quantity']}, Modifier: {item['modifier']}")
        if item['modifier'] in ["increase", "add"]:
            print("✅ SUCCESS: Correct modifier detected for 'one more'.")
        else:
            print(f"❌ FAILURE: Unexpected modifier '{item['modifier']}' for 'one more'.")

if __name__ == "__main__":
    test_quantity_increment()
