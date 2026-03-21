import httpx
import json
import os
import time

BASE_URL = "http://127.0.0.1:8000"

def test_root():
    print("\nTesting Root...")
    try:
        response = httpx.get(f"{BASE_URL}/")
        print(response.json())
    except Exception as e:
        print(f"Error: {e}")

def test_menu():
    print("\nTesting Menu...")
    try:
        response = httpx.get(f"{BASE_URL}/menu")
        print(f"Menu size: {len(response.json()['menu'])}")
    except Exception as e:
        print(f"Error: {e}")

def test_classify():
    print("\nTesting Classify...")
    try:
        payload = {"transcript": "Chole Bhature ane ek Bhature"}
        response = httpx.post(f"{BASE_URL}/order/classify", data=payload, timeout=60.0)
        print(json.dumps(response.json(), indent=4))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Note: This script assumes the server is running.
    # To run the server: py server.py
    test_root()
    test_menu()
    test_classify()
