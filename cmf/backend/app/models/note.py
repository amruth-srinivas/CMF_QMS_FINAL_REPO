"""
Note model for storing notes/annotations on documents.
"""
from sqlalchemy import Column, Integer, String, Text, Float, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from app.database import Base


class Note(Base):
    """Note model - represents a note/annotation on a document."""
    
    __tablename__ = "notes"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Link to Part (required)
    part_id = Column(Integer, ForeignKey("parts.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Link to Document (optional - for reference)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Position and dimensions (for bounding box display)
    x = Column(Float, nullable=True)  # X coordinate
    y = Column(Float, nullable=True)  # Y coordinate
    width = Column(Float, nullable=True)  # Width of bounding box
    height = Column(Float, nullable=True)  # Height of bounding box
    page = Column(Integer, nullable=True, default=1)  # Page number
    
    # Note content
    note_text = Column(Text, nullable=True)  # The note text content
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    
    # Relationships
    part = relationship("Part", back_populates="notes")
    document = relationship("Document", back_populates="notes")
