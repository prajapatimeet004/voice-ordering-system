import os
import json
import threading

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INVENTORY_FILE = os.path.join(_SCRIPT_DIR, "inventory.json")

# Use a lock to ensure thread-safety for file operations
inventory_lock = threading.Lock()

def load_inventory():
    """Loads the inventory from the JSON file."""
    with inventory_lock:
        try:
            if os.path.exists(INVENTORY_FILE):
                with open(INVENTORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {}
        except Exception as e:
            print(f"Error loading inventory: {e}")
            return {}

def save_inventory(inventory):
    """Saves the inventory to the JSON file."""
    with inventory_lock:
        try:
            with open(INVENTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(inventory, f, indent=4)
            return True
        except Exception as e:
            print(f"Error saving inventory: {e}")
            return False

def get_stock(dish_name):
    """
    Returns the current stock for a given dish.
    If the dish is not in the inventory file, it defaults to 20 (assuming it's a valid menu item).
    """
    inventory = load_inventory()
    if dish_name in inventory:
        return inventory[dish_name].get("stock", 0)
    
    # Default behavior for items not yet explicitly managed in inventory.json
    return 20

def update_stock(dish_name, change):
    """
    Updates the stock for a given dish by the specified change (positive or negative).
    Returns True if successful, False otherwise.
    """
    inventory = load_inventory()
    if dish_name in inventory:
        current_stock = inventory[dish_name].get("stock", 0)
        new_stock = max(0, current_stock + change)
        inventory[dish_name]["stock"] = new_stock
        return save_inventory(inventory)
    else:
        # If item doesn't exist, we add it with a base of 20 + change
        new_stock = max(0, 20 + change)
        inventory[dish_name] = {"stock": new_stock}
        print(f"Dish {dish_name} added to inventory with {new_stock} stock.")
        return save_inventory(inventory)

def check_availability(dish_name, quantity=1):
    """
    Checks if a dish has enough stock for the requested quantity.
    Returns (is_available, remaining_stock).
    """
    stock = get_stock(dish_name)
    return (stock >= quantity, stock)

def toggle_availability(dish_name, status=None):
    """
    Toggles availability (sets stock to 0 or a default value).
    If status is True, sets stock to 10 (arbitrary).
    If status is False, sets stock to 0.
    """
    inventory = load_inventory()
    if dish_name in inventory:
        if status is None:
            # Toggle logic
            new_stock = 10 if inventory[dish_name].get("stock", 0) == 0 else 0
        else:
            new_stock = 10 if status else 0
        
        inventory[dish_name]["stock"] = new_stock
        return save_inventory(inventory)
    return False
