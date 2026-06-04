"""
Item and ItemRevision models for unified product structure.
Replaces the separate Project, Assembly, and Part models with a more flexible structure.
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Enum as SQLEnum, func
from sqlalchemy.orm import relationship
import enum
from app.database import Base


class ItemType(str, enum.Enum):
    """Enumeration of item types."""
    PROJECT = "PROJECT"
    ASSEMBLY = "ASSEMBLY"
    PART = "PART"


class Item(Base):
    """
    Base Item entity.
    Represents a unique 'thing' in the system (e.g., a specific Part Number).
    """
    __tablename__ = "items"
    
    id = Column(Integer, primary_key=True, index=True)
    item_no = Column(String(255), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    item_type = Column(SQLEnum(ItemType), nullable=False, index=True)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    revisions = relationship("ItemRevision", back_populates="item", cascade="all, delete-orphan")
    parents = relationship("BOMItem", back_populates="child_item", foreign_keys="[BOMItem.child_item_id]")


class ItemRevision(Base):
    """
    A specific revision of an Item.
    Contains the design/specification that changes over time.
    """
    __tablename__ = "item_revisions"
    
    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    revision = Column(String(64), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="Draft")  # Draft, Released, Superseded
    is_current = Column(Boolean, nullable=False, default=True)
    
    # QMS specific flags
    inspection_plan_status = Column(Boolean, nullable=False, default=False)
    priority_component = Column(Boolean, nullable=False, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    
    # Relationships
    item = relationship("Item", back_populates="revisions")
    
    # Hierarchy (BOM)
    # Revisions consume other Items (not revisions, usually, to allow 'latest' navigation)
    # but in strict systems, Revisions consume specific Revisions. 
    # For now, let's link Parent Revision -> Child Item.
    children = relationship("BOMItem", back_populates="parent_revision", cascade="all, delete-orphan")

    # Document links
    documents = relationship("Document", back_populates="item_revision", cascade="all, delete-orphan")
    
    # Inspection Plans
    inspection_plans = relationship("InspectionPlan", back_populates="item_revision", cascade="all, delete-orphan")
