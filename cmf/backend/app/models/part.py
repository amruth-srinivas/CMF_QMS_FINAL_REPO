"""
Part model.
Represents a part in the QMS system.
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, func
from sqlalchemy.orm import relationship
from app.database import Base


class Part(Base):
    """Part model representing a part."""
    
    __tablename__ = "parts"
    
    id = Column(Integer, primary_key=True, index=True)
    part_no = Column(String(255), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    rev = Column(String(64), nullable=True)  # Revision
    inspection_plan_status = Column(Boolean, nullable=False, default=False)  # Inspection plan status (toggleable)
    priority_component = Column(Boolean, nullable=False, default=False)  # Priority component flag (star/balloon)
    inspection_plan_approved_at = Column(DateTime(timezone=True), nullable=True)  # Date when plan was approved
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships - passive_deletes=True lets DB handle CASCADE
    part_locations = relationship("PartLocation", back_populates="part", cascade="all, delete-orphan", passive_deletes=True)
    documents = relationship("Document", back_populates="part", cascade="all, delete-orphan", passive_deletes=True)
    balloons = relationship("Balloon", back_populates="part", cascade="all, delete-orphan", passive_deletes=True)
    notes = relationship("Note", back_populates="part", cascade="all, delete-orphan", passive_deletes=True)

