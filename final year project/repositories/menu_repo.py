import json
import os
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.menu import MenuItem


async def seed_menu_from_file(session: AsyncSession, menu_file: str = None):
    """Load menu.json into DB if the menu table is empty."""
    if menu_file is None:
        menu_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "menu.json")
    result = await session.execute(select(MenuItem).limit(1))
    if result.scalar_one_or_none() is not None:
        return  # already seeded

    if not os.path.exists(menu_file):
        print(f"WARNING: {menu_file} not found, skipping menu seed.")
        return

    with open(menu_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = []
    for name, info in data.items():
        items.append(MenuItem(
            name=name,
            category=info.get("category", "Other"),
            price=info.get("price", 0),
            allowed_addons=info.get("allowed_addons", []),
        ))
    session.add_all(items)
    await session.commit()
    print(f"INFO: Seeded {len(items)} menu items from {menu_file}")


async def get_all_menu_items(session: AsyncSession) -> dict:
    """Returns menu data in the same format as server.py's MENU_DATA."""
    result = await session.execute(select(MenuItem))
    rows = result.scalars().all()
    return {
        row.name: {
            "category": row.category,
            "price": row.price,
            "allowed_addons": row.allowed_addons or [],
        }
        for row in rows
    }


async def get_menu_item(session: AsyncSession, name: str) -> Optional[MenuItem]:
    result = await session.execute(select(MenuItem).where(MenuItem.name == name))
    return result.scalar_one_or_none()


async def get_menu_item_price(session: AsyncSession, name: str) -> float:
    item = await get_menu_item(session, name)
    return item.price if item else 0.0
