"""
Instrument setup: hierarchical categories and library instruments (catalog rows).
"""
from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class InstrumentSetupCategory(Base):
    __tablename__ = "instrument_setup_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    parent_id = Column(Integer, ForeignKey("instrument_setup_categories.id"), nullable=True, index=True)

    parent = relationship(
        "InstrumentSetupCategory",
        remote_side=[id],
        backref="children",
    )


class LibraryInstrument(Base):
    __tablename__ = "library_instruments"

    __table_args__ = (
        UniqueConstraint("category_id", "instrument_code", name="uq_library_instrument_code_per_category"),
    )

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("instrument_setup_categories.id"), nullable=False, index=True)
    
    # Basic Identity
    instrument_code = Column(String(120), nullable=False) # Asset Tag / Internal ID
    instrument_name = Column(String(255), nullable=True)
    manufacturer = Column(String(120), nullable=True)
    model_number = Column(String(120), nullable=True)
    serial_number = Column(String(255), nullable=True) # Manufacturer Serial / MAC
    
    # Specs
    range = Column(String(120), nullable=True)
    resolution = Column(String(120), nullable=True)
    accuracy = Column(String(120), nullable=True)
    
    # Calibration
    last_calibration_date = Column(String(64), nullable=True)
    calibration = Column(String(64), nullable=True) # Next Calibration Date
    calibration_interval = Column(Integer, nullable=True) # months
    
    # Management
    status = Column(String(64), nullable=True, default="Active")
    location = Column(String(255), nullable=True)
    available_qty = Column(Integer, nullable=False, default=1)
    equipment_no = Column(String(255), nullable=True) # Legacy field

    category = relationship("InstrumentSetupCategory", backref="instruments")
