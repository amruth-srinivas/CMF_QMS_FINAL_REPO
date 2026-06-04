"""
Lookup tables for standardizing QMS metadata.
"""
from sqlalchemy import Column, Integer, String, Text
from app.database import Base


class CharacteristicType(Base):
    """Types of characteristics (Length, Diameter, Flatness, etc.)"""
    __tablename__ = "char_types"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, index=True)
    symbol = Column(String(10), nullable=True)  # e.g., GD&T Symbols
    description = Column(Text, nullable=True)


class UnitOfMeasure(Base):
    """Units (mm, inch, degree, etc.)"""
    __tablename__ = "units"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True)
    abbreviation = Column(String(10), unique=True)


class MeasuringInstrument(Base):
    """Standard measuring instruments/equipment"""
    __tablename__ = "instruments"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), index=True)
    calibration_id = Column(String(100), nullable=True)
    accuracy = Column(String(100), nullable=True)
