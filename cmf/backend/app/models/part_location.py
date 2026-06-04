"""
PartLocation model.
Links parts to either a project or an assembly.
Enforces CHECK constraint: exactly one of project_id or assembly_id must be non-null.
"""
from sqlalchemy import Column, Integer, ForeignKey, CheckConstraint, func
from sqlalchemy.orm import relationship
from app.database import Base


class PartLocation(Base):
    """
    PartLocation model.
    Links a part to either a project (top-level) or an assembly.
    Exactly one of project_id or assembly_id must be non-null.
    """
    
    __tablename__ = "part_locations"
    
    id = Column(Integer, primary_key=True, index=True)
    part_id = Column(Integer, ForeignKey("parts.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    assembly_id = Column(Integer, ForeignKey("assemblies.id", ondelete="CASCADE"), nullable=True, index=True)
    quantity = Column(Integer, nullable=False, default=1)
    
    # Relationships
    part = relationship("Part", back_populates="part_locations")
    project = relationship("Project", back_populates="part_locations")
    assembly = relationship("Assembly", back_populates="part_locations")
    
    # CHECK constraint: exactly one of project_id or assembly_id must be non-null
    __table_args__ = (
        CheckConstraint(
            "(project_id IS NOT NULL AND assembly_id IS NULL) OR (project_id IS NULL AND assembly_id IS NOT NULL)",
            name="check_exactly_one_location"
        ),
    )

