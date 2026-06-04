"""
Assembly model with recursive parent-child relationship.
Assemblies can belong to a project and have a parent assembly.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func, CheckConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class Assembly(Base):
    """Assembly model with recursive parent-child relationship."""
    
    __tablename__ = "assemblies"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    no = Column(String(255), nullable=True, index=True)  # Assembly number
    rev = Column(String(64), nullable=True)  # Revision
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_assembly_id = Column(Integer, ForeignKey("assemblies.id", ondelete="SET NULL"), nullable=True, index=True)
    quantity = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships - passive_deletes=True lets DB handle CASCADE
    project = relationship("Project", back_populates="assemblies")
    parent_assembly = relationship("Assembly", remote_side=[id], backref="child_assemblies")
    part_locations = relationship("PartLocation", back_populates="assembly", cascade="all, delete-orphan", passive_deletes=True)
    documents = relationship("Document", back_populates="assembly", cascade="all, delete-orphan", passive_deletes=True)

