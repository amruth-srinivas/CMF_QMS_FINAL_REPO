from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    TIMESTAMP,
    func,
    UniqueConstraint,
    BigInteger,
    Text,
    text,
    JSON,
)
from ..database import Base


class MasterBoc(Base):
    """
    Master BOC — bill of characteristics (no FK to other schemas; values are logical references only).
    """
    __tablename__ = "master_boc"
    __table_args__ = {"schema": "quality"}

    id = Column(Integer, primary_key=True, index=True)
    part_id = Column(String, nullable=False)
    sales_order_id = Column(Integer, nullable=False)
    nominal = Column(String, nullable=False)
    uppertol = Column(Float, nullable=False)
    lowertol = Column(Float, nullable=False)
    zone = Column(String, nullable=False)
    dimension_type = Column(String, nullable=False)
    measured_instrument = Column(String, nullable=False, server_default=text("'default'"))
    op_no = Column(Integer, nullable=False)
    bbox = Column(Text, nullable=False)
    ipid = Column(String, nullable=False)
    user_id = Column(Integer, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class StageInspection(Base):
    """
    Stage inspection measurements (no FK to other schemas).
    """
    __tablename__ = "stage_inspection"
    __table_args__ = {"schema": "quality"}

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)
    part_id = Column(Integer, nullable=False)
    sale_order_id = Column(Integer, nullable=False)
    nominal_value = Column(String, nullable=False)
    uppertol = Column(Float, nullable=False)
    lowertol = Column(Float, nullable=False)
    zone = Column(String, nullable=False)
    dimension_type = Column(String, nullable=False)
    measurements = Column(JSON, nullable=False, server_default=text("'[]'"))
    measured_mean = Column(String, nullable=True)
    measured_instrument = Column(String, nullable=False)
    used_inst = Column(String, nullable=False)
    op_no = Column(Integer, nullable=False)
    quantity_no = Column(Integer, nullable=True)
    bbox = Column(Text, nullable=True)
    is_done = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)


class FTP(Base):
    """
    FTP / IPID completion tracking (no FK to other schemas).
    """
    __tablename__ = "ftp_status"
    __table_args__ = (
        UniqueConstraint("order_id", "ipid", name="uix_order_ipid"),
        {"schema": "quality"},
    )

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(BigInteger, nullable=False)
    ipid = Column(String(255), nullable=False)
    is_completed = Column(Boolean, nullable=False, default=False)
    status = Column(String(255), nullable=False)
    approved_by_username = Column(String(255), nullable=True)
    approved_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class InspectionPlanStatus(Base):
    """
    Draft vs confirmed inspection plan per part number + sales order + operation.
    """
    __tablename__ = "inspection_plan_status"
    __table_args__ = (
        UniqueConstraint("part_number", "sales_order_id", "op_no", name="uix_inspection_plan_scope"),
        {"schema": "quality"},
    )

    id = Column(Integer, primary_key=True, index=True)
    part_number = Column(String, nullable=False)
    sales_order_id = Column(Integer, nullable=False)
    op_no = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, server_default=text("'draft'"))
    confirmed_by_username = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Note(Base):
    """
    Inspector notes on PDF regions.
    """
    __tablename__ = "notes"
    __table_args__ = {"schema": "quality"}

    id = Column(Integer, primary_key=True, index=True)
    part_id = Column(Integer, nullable=False, index=True)
    document_id = Column(Integer, nullable=True, index=True)
    op_no = Column(Integer, nullable=False, server_default=text("0"), index=True)
    is_operation_document = Column(Boolean, nullable=False, server_default=text("false"))
    x = Column(Float, nullable=True)
    y = Column(Float, nullable=True)
    width = Column(Float, nullable=True)
    height = Column(Float, nullable=True)
    page = Column(Integer, nullable=True, default=1)
    note_text = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)


class InspectionReportSave(Base):
    """
    Saved inspection report edits (remarks, footer test fields, signatories).
    """
    __tablename__ = "inspection_report_save"
    __table_args__ = (
        UniqueConstraint(
            "part_number",
            "sales_order_id",
            "op_no",
            "quantity_no",
            "consolidated",
            name="uix_inspection_report_save_scope",
        ),
        {"schema": "quality"},
    )

    id = Column(Integer, primary_key=True, index=True)
    part_number = Column(String, nullable=False)
    sales_order_id = Column(Integer, nullable=False)
    op_no = Column(Integer, nullable=False)
    quantity_no = Column(Integer, nullable=False, server_default=text("1"))
    consolidated = Column(Boolean, nullable=False, server_default=text("false"))
    row_remarks = Column(JSON, nullable=True)
    footer_rows = Column(JSON, nullable=True)
    inspected_by = Column(String(255), nullable=True)
    checked_by = Column(String(255), nullable=True)
    saved_by_username = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
