import json
import os
from typing import Optional, Tuple
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.inventory import InventoryItem


async def seed_inventory_from_file(session: AsyncSession, inventory_file: str = None):
    """Load inventory.json into DB if the inventory table is empty."""
    if inventory_file is None:
        inventory_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "inventory.json")
    result = await session.execute(select(InventoryItem).limit(1))
    if result.scalar_one_or_none() is not None:
        return

    if not os.path.exists(inventory_file):
        print(f"WARNING: {inventory_file} not found, skipping inventory seed.")
        return

    with open(inventory_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = []
    for name, info in data.items():
        items.append(InventoryItem(
            dish_name=name,
            stock=info.get("stock", 50),
            alternative=info.get("alternative"),
        ))
    session.add_all(items)
    await session.commit()
    print(f"INFO: Seeded {len(items)} inventory items from {inventory_file}")


async def get_stock(session: AsyncSession, dish_name: str) -> int:
    result = await session.execute(
        select(InventoryItem.stock).where(InventoryItem.dish_name == dish_name)
    )
    row = result.scalar_one_or_none()
    return row if row is not None else 0


async def check_availability(session: AsyncSession, dish_name: str, quantity: int = 1) -> Tuple[bool, int]:
    stock = await get_stock(session, dish_name)
    return (stock >= quantity, stock)


async def update_stock(session: AsyncSession, dish_name: str, change: int) -> bool:
    result = await session.execute(
        select(InventoryItem).where(InventoryItem.dish_name == dish_name)
    )
    item = result.scalar_one_or_none()
    if not item:
        return False
    new_stock = max(0, item.stock + change)
    item.stock = new_stock
    await session.commit()
    return True


async def get_full_inventory(session: AsyncSession) -> dict:
    result = await session.execute(select(InventoryItem))
    rows = result.scalars().all()
    return {
        row.dish_name: {
            "stock": row.stock,
            "alternative": row.alternative,
        }
        for row in rows
    }


async def get_inventory_summary(session: AsyncSession) -> str:
    inventory = await get_full_inventory(session)
    unavailable = []
    for dish, data in inventory.items():
        if data.get("stock", 0) <= 0:
            alt = data.get("alternative", "None")
            unavailable.append(f"- {dish} (Alternative: {alt})")
    if not unavailable:
        return "All items are currently in stock."
    return "The following items are OUT OF STOCK. If a customer orders them, apologize in Gujlish and suggest the listed alternative:\n" + "\n".join(unavailable)
