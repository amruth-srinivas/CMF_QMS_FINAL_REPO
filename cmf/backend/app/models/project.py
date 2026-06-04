"""
Project model.
Represents a project in the QMS system.
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, func
from sqlalchemy.orm import relationship
from app.database import Base


class Project(Base):
    """Project model representing a project."""
    
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, index=True)
    project_number = Column(String(100), nullable=False, index=True, unique=True)
    name = Column(String(255), nullable=False, index=True)
    customer_details = Column(String(500), nullable=True)
    reference_no = Column(String(100), nullable=True, index=True)
    is_completed = Column(Boolean, nullable=False, default=False)  # Project completion status
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships - passive_deletes=True lets DB handle CASCADE, avoiding lazy-load of related
    # entities that can trigger "Unknown PG numeric type: 1043" on schema mismatches
    assemblies = relationship("Assembly", back_populates="project", cascade="all, delete-orphan", passive_deletes=True)
    part_locations = relationship("PartLocation", back_populates="project", cascade="all, delete-orphan", passive_deletes=True)

