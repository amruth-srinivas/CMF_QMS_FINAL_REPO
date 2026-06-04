"""
Balloon model for storing balloon annotations on documents.
"""
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from app.database import Base


class Balloon(Base):
    """Balloon model - represents a balloon annotation on a document."""
    
    __tablename__ = "balloons"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Link to Part (required - primary association)
    part_id = Column(Integer, ForeignKey("parts.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Link to Document (optional - for reference)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Balloon identifier (unique per document)
    balloon_id = Column(String(100), nullable=False, index=True)
    
    # Position and dimensions (for bounding box display)
    x = Column(Float, nullable=True)  # X coordinate
    y = Column(Float, nullable=True)  # Y coordinate
    width = Column(Float, nullable=True)  # Width of bounding box
    height = Column(Float, nullable=True)  # Height of bounding box
    page = Column(Integer, nullable=True, default=1)  # Page number
    
    # Specification values
    nominal = Column(Float, nullable=True)  # Target value
    # Use String (VARCHAR) so SQLAlchemy's PG dialect handles OID 1043; Text-only processors can fail
    utol = Column(String(500), nullable=True)  # Upper tolerance
    ltol = Column(String(500), nullable=True)  # Lower tolerance
    type = Column(String(500), nullable=True)  # Dimension type (e.g., "Length", "GDT-⌯ flatness")
    zone = Column(String(200), nullable=True)  # Zone identifier (e.g., "B5", "C6")
    measuring_instrument = Column(String(500), nullable=True)  # Required measuring instrument
    op_no = Column(String(200), nullable=True)  # Operation number
    sampling = Column(Integer, nullable=True, default=3)  # Number of samples to measure
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    
    # Relationships - passive_deletes=True lets DB handle CASCADE
    part = relationship("Part", back_populates="balloons")
    document = relationship("Document", back_populates="balloons")
    # measurements = relationship("Measurement", back_populates="balloon", cascade="all, delete-orphan", passive_deletes=True)

