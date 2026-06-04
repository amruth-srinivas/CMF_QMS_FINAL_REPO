"""
Measurement models for normalized sample recording.
"""
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Text, func, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum
from app.database import Base


class GoNoGoStatus(str, enum.Enum):
    GO = "GO"
    NO_GO = "NO_GO"


class MeasurementReport(Base):
    """
    A single inspection instance (Session).
    Links a physical part being measured to an InspectionPlan.
    """
    __tablename__ = "measurement_reports"
    
    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("inspection_plans.id", ondelete="CASCADE"), nullable=False)
    
    # Serial number of the physical part
    serial_number = Column(String(255), nullable=True)
    batch_no = Column(String(255), nullable=True)
    
    measured_by = Column(String(255), nullable=True)
    measured_at = Column(DateTime(timezone=True), server_default=func.now())
    notes = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="In-Progress")  # Completed, Rejected, Flagged
    
    # Relationships
    # plan = relationship("InspectionPlan")
    measurements = relationship("MeasurementValue", back_populates="report", cascade="all, delete-orphan")


class MeasurementValue(Base):
    """
    Actual measured value for a characteristic.
    One row per sample.
    """
    __tablename__ = "measurement_values"
    
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("measurement_reports.id", ondelete="CASCADE"), nullable=False)
    char_id = Column(Integer, ForeignKey("characteristics.id", ondelete="CASCADE"), nullable=False)
    
    sample_no = Column(Integer, nullable=False, default=1)
    value = Column(Float, nullable=True)
    go_no_go = Column(SQLEnum(GoNoGoStatus), nullable=True)
    
    measured_at = Column(DateTime(timezone=True), server_default=func.now())
    instrument_used = Column(String(255), nullable=True)
    obs = Column(Text, nullable=True)  # Observations/Notes
    
    # Relationships
    report = relationship("MeasurementReport", back_populates="measurements")
    characteristic = relationship("Characteristic", back_populates="measurements")


class Measurement(Base):
    """
    Simpler, flat measurement model used by the measurement router.
    Stores m1, m2, m3 as individual readings per part instance.
    """
    __tablename__ = "measurements"
    
    id = Column(Integer, primary_key=True, index=True)
    balloon_id = Column(Integer, ForeignKey("balloons.id", ondelete="CASCADE"), nullable=False, index=True)
    part_id = Column(Integer, ForeignKey("parts.id", ondelete="CASCADE"), nullable=True, index=True)
    
    quantity = Column(Integer, nullable=True, default=1)
    
    m1 = Column(Float, nullable=True)
    m2 = Column(Float, nullable=True)
    m3 = Column(Float, nullable=True)
    mean = Column(Float, nullable=True)
    
    go_or_no_go = Column(SQLEnum(GoNoGoStatus), nullable=True)
    
    measured_by = Column(String(255), nullable=True)
    instrument_id = Column(Integer, ForeignKey("library_instruments.id", ondelete="SET NULL"), nullable=True)
    measured_at = Column(DateTime(timezone=True), server_default=func.now())
    notes = Column(Text, nullable=True)
    
    # Relationships
    balloon = relationship("Balloon")
    part = relationship("Part")

