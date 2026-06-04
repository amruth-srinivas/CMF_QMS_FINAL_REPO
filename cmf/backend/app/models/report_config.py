"""
Report configuration models for template management.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class ReportConfig(Base):
    """Base report template configuration."""
    __tablename__ = "report_config"

    id = Column(Integer, primary_key=True, index=True)
    report_name = Column(String(255), nullable=False, default="Inspection Report")
    company_name = Column(String(255), nullable=True)
    logo_path = Column(String(512), nullable=True)
    is_locked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    fields = relationship("ReportConfigField", back_populates="report", cascade="all, delete-orphan", order_by="ReportConfigField.id")

    def __repr__(self):
        return f"<ReportConfig(id={self.id}, report_name='{self.report_name}', is_locked={self.is_locked})>"


class ReportConfigField(Base):
    """Dynamic header/footer fields for a report template."""
    __tablename__ = "report_config_fields"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("report_config.id", ondelete="CASCADE"), nullable=False, index=True)
    section = Column(String(20), nullable=False)  # 'header' | 'footer'
    field_label = Column(String(255), nullable=False)
    backend_key = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    report = relationship("ReportConfig", back_populates="fields")

    def __repr__(self):
        return f"<ReportConfigField(id={self.id}, section='{self.section}', field_label='{self.field_label}')>"
