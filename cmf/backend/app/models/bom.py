"""
BOM (Bill of Materials) model for linking items in a hierarchy.
"""
from sqlalchemy import Column, Integer, ForeignKey, Float
from sqlalchemy.orm import relationship
from app.database import Base


class BOMItem(Base):
    """
    Links a parent ItemRevision to a child Item.
    This defines where an item is used and in what quantity.
    """
    __tablename__ = "bom_items"
    
    id = Column(Integer, primary_key=True, index=True)
    parent_revision_id = Column(Integer, ForeignKey("item_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    child_item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    
    quantity = Column(Float, nullable=False, default=1.0)
    position_number = Column(Integer, nullable=True)  # Item number in the BOM (10, 20, 30...)
    
    # Relationships
    parent_revision = relationship("ItemRevision", back_populates="children", foreign_keys=[parent_revision_id])
    child_item = relationship("Item", back_populates="parents", foreign_keys=[child_item_id])
