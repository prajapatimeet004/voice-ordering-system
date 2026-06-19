from sqlalchemy import Column, Integer, String, DateTime, func, ForeignKey
from models.base import Base


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dish_name = Column(String(255), unique=True, nullable=False, index=True)
    stock = Column(Integer, default=50, nullable=False)
    alternative = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
