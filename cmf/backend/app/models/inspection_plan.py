"""
InspectionPlan and Characteristic models.
Characteristics (formerly Balloons) are now part of an Inspection Plan.
"""
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Boolean, func
from sqlalchemy.orm import relationship
from app.database import Base


class InspectionPlan(Base):
    """
    Inspection Plan for a specific ItemRevision.
    Contains characteristics and lifecycle status for quality control.
    """
    __tablename__ = "inspection_plans"
    
    id = Column(Integer, primary_key=True, index=True)
    item_revision_id = Column(Integer, ForeignKey("item_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    
    plan_no = Column(String(100), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(50), nullable=False, default="Draft")  # Draft, Approved, Locked
    is_active = Column(Boolean, nullable=False, default=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    item_revision = relationship("ItemRevision", back_populates="inspection_plans")
    characteristics = relationship("Characteristic", back_populates="plan", cascade="all, delete-orphan")


class Characteristic(Base):
    """
    Quality Characteristic (Point of Measurement).
    Replacing the legacy 'Balloon' model with more structure.
    """
    __tablename__ = "characteristics"
    
    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("inspection_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Core Balloon Properties (from drawing)
    balloon_id = Column(String(100), nullable=False, index=True)
    page = Column(Integer, nullable=True, default=1)
    x = Column(Float, nullable=True)
    y = Column(Float, nullable=True)
    width = Column(Float, nullable=True)
    height = Column(Float, nullable=True)
    
    # Specification
    nominal = Column(Float, nullable=True)
    utol = Column(Float, nullable=True)  # Normalized to Float
    ltol = Column(Float, nullable=True)  # Normalized to Float
    utol_str = Column(String(100), nullable=True)  # Original string for display
    ltol_str = Column(String(100), nullable=True)  # Original string for display
    
    type_id = Column(Integer, ForeignKey("char_types.id"), nullable=True)
    unit_id = Column(Integer, ForeignKey("units.id"), nullable=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=True)
    
    zone = Column(String(200), nullable=True)
    op_no = Column(String(100), nullable=True)
    criticality = Column(String(50), nullable=True, default="Standard")  # Critical, Major, Standard
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    plan = relationship("InspectionPlan", back_populates="characteristics")
    # char_type = relationship("CharacteristicType")
    # unit = relationship("UnitOfMeasure")
    # instrument = relationship("MeasuringInstrument")
    measurements = relationship("MeasurementValue", back_populates="characteristic", cascade="all, delete-orphan")
