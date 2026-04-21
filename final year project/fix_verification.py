import asyncio
import json
import os
import sys

# Ensure current dir is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import classifier_service
import inventory_service

async def test_inventory_awareness():
    print("\n--- Testing Inventory Awareness (Out of Stock Item) ---")
    # Set Masala Dosa to 0 stock
    inventory = inventory_service.load_inventory()
    if "Masala Dosa" not in inventory:
        inventory["Masala Dosa"] = {"stock": 0, "alternative": "Uttapam"}
    else:
        inventory["Masala Dosa"]["stock"] = 0
    inventory_service.save_inventory(inventory)
    
    transcript = "I want one Masala Dosa"
    result = await classifier_service.classify_order(transcript)
    
    print(f"Transcript: {transcript}")
    print(f"Response: {result['response_text']}")
    
    # Check if apology and alternative (Uttapam) are in the response
    # The LLM might use different words, so we check for key concepts
    lower_res = result['response_text'].lower()
    if any(w in lower_res for w in ["sorry", "maaf", "nathi", "naji"]):
        if "uttapam" in lower_res:
            print("✅ SUCCESS: Inventory awareness worked.")
        else:
            print("❌ FAILURE: Alternative not suggested.")
    else:
        print("❌ FAILURE: No apology detected.")

async def test_tandoori_roti_matching():
    print("\n--- Testing Tandoori Roti Matching ---")
    
    transcript = "Bring me two Tandoori Roti"
    result = await classifier_service.classify_order(transcript)
    
    print(f"Transcript: {transcript}")
    print(f"Extracted Items: {[i['dish'] for i in result['items']]}")
    
    found = False
    for item in result['items']:
        if item['dish'] == "Tandoori Roti":
            found = True
            break
            
    if found:
        print("✅ SUCCESS: Tandoori Roti matched correctly.")
    else:
        print("❌ FAILURE: Tandoori Roti not matched correctly.")

async def run_tests():
    await test_inventory_awareness()
    await test_tandoori_roti_matching()
    
    # Reset Masala Dosa stock for safety
    inventory = inventory_service.load_inventory()
    if "Masala Dosa" in inventory:
        inventory["Masala Dosa"]["stock"] = 50
        inventory_service.save_inventory(inventory)

if __name__ == "__main__":
    asyncio.run(run_tests())
