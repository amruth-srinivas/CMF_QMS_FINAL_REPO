"""
Notifications schema: inspection plan requests from operators to supervisors.
"""
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, TIMESTAMP, func, text

from ..database import Base


class InspectionPlanNotification(Base):
    """
    Operator requests a confirmed inspection plan for an in-progress order/operation.
    Supervisors acknowledge and then create/confirm the plan in Quality Management.
    """

    __tablename__ = "inspection_notifications"
    __table_args__ = {"schema": "notifications"}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("oms.orders.id"), nullable=False)
    part_number = Column(String(255), nullable=False)
    op_no = Column(Integer, nullable=False)
    operation_id = Column(Integer, nullable=False)
    machine_id = Column(Integer, nullable=True)
    requested_by_username = Column(String(255), nullable=True)
    category = Column(String(50), nullable=False, server_default=text("'plan_request'"))  # 'plan_request' or 'ftp_request'

    is_ack = Column(Boolean, nullable=False, server_default=text("false"))
    ack_by = Column(String(255), nullable=True)
    ack_at = Column(TIMESTAMP(timezone=True), nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
