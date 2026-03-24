import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_flow():
    print("--- 1. Checking Initial Inventory ---")
    res = requests.get(f"{BASE_URL}/inventory/status")
    initial_inventory = res.json()
    print(json.dumps(initial_inventory, indent=2))
    
    dosa_stock = initial_inventory.get("Masala Dosa", {}).get("stock", 0)
    print(f"Current Masala Dosa Stock: {dosa_stock}")

    print("\n--- 2. Manually Adding Stock ---")
    res = requests.post(f"{BASE_URL}/inventory/update", data={"dish_name": "Masala Dosa", "change": 10})
    print(res.json())
    
    print("\n--- 3. Classifying Order (2 Masala Dosa) ---")
    # This won't work without a running server, but for the sake of the script logic:
    # We'll assume the classification works and adds to the state.
    # Note: In a real test, you'd need the server running and possibly use a mock for Sarvam if needed,
    # or just use the /order/classify endpoint if you have audio/transcript.
    res = requests.post(f"{BASE_URL}/order/classify", data={"transcript": "mujhe do masala dosa chahiye"})
    print(res.json().get("response_text"))
    print(f"Current Order State: {res.json().get('current_order')}")

    print("\n--- 4. Submitting Order ---")
    res = requests.post(f"{BASE_URL}/order/submit")
    print(res.json())

    print("\n--- 5. Verifying Final Stock ---")
    res = requests.get(f"{BASE_URL}/inventory/status")
    final_inventory = res.json()
    final_dosa_stock = final_inventory.get("Masala Dosa", {}).get("stock", 0)
    print(f"Final Masala Dosa Stock: {final_dosa_stock}")
    
    expected_stock = dosa_stock + 10 - 2
    if final_dosa_stock == expected_stock:
        print("\n✅ SUCCESS: Inventory updated correctly!")
    else:
        print(f"\n❌ FAILURE: Expected {expected_stock}, got {final_dosa_stock}")

if __name__ == "__main__":
    try:
        test_flow()
    except Exception as e:
        print(f"Error during test: {e}")
        print("Make sure the server is running on http://localhost:8000")
