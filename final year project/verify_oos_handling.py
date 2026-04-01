import sys
import os
import json

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from classifier_service import classify_order
import inventory_service

def test_oos():
    print("--- Testing Out-of-Stock: Masala Dosa (Alt: Uttapam) ---")
    # Verify stock is 0 in inventory.json (mocking or checking live)
    inventory = inventory_service.get_full_inventory()
    if "Masala Dosa" in inventory:
        inventory["Masala Dosa"]["stock"] = 0
        inventory_service.save_inventory(inventory)
    
    transcript = "I want one Masala Dosa please"
    result = classify_order(transcript)
    
    print(f"Transcript: {transcript}")
    print(f"Pooja's Response: {result.get('response_text')}")
    
    # Check if 'Uttapam' is in the response
    if "Uttapam" in result.get('response_text'):
        print("✅ SUCCESS: Pooja suggested Uttapam.")
    else:
        print("❌ FAILURE: Pooja did not suggest Uttapam.")

    # Check if Masala Dosa is in confirmed (it should be, because classify_order just classifies)
    # The server.py is what prevents it from being added to the GLOBAL state.
    # But let's check if the intent was correctly captured.
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    test_oos()
