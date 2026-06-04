from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Date, Time, Boolean, Text, TIMESTAMP, func
from sqlalchemy.orm import relationship
from ..database import Base

class OrderScheduleStatus(Base):
    __tablename__ = "order_schedule_status"
    __table_args__ = {"schema": "scheduling"}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    order_id = Column(Integer, ForeignKey("oms.orders.id"))
    product_id = Column(Integer, ForeignKey("oms.products.id"))

    active_parts_count = Column(Integer, default=0)
    active_inhouse_parts = Column(Integer, default=0)

    status = Column(String, default="inactive")

    activated_at = Column(DateTime)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    order = relationship("DB.models.oms.Order")

class PartScheduleStatus(Base):
    __tablename__ = "part_schedule_status"
    __table_args__ = {"schema": "scheduling"}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    sale_order_id = Column(Integer, ForeignKey("oms.orders.id"))
    part_id = Column(Integer, ForeignKey("oms.parts.id"))
    status = Column(String, default="inactive")
    
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class PlannedScheduleItem(Base):
    __tablename__ = "planned_schedule_items"
    __table_args__ = {"schema": "scheduling"}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    part_id = Column(Integer, ForeignKey("oms.parts.id"))
    part_number = Column(String)
    sale_order_id = Column(Integer, ForeignKey("oms.orders.id"))
    sale_order_number = Column(String)
    operation_id = Column(Integer, ForeignKey("oms.operations.id"))
    machine_id = Column(Integer, ForeignKey("configuration.machines.id"))
    status = Column(String)


class ProductionLog(Base):
    __tablename__ = "production_logs"
    __table_args__ = {"schema": "scheduling"}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    operation_id = Column(Integer, ForeignKey("oms.operations.id"), nullable=False)
    operator_id = Column(Integer)
    supervisor_id = Column(Integer)
    notes = Column(Text)
    remarks = Column(Text)
    from_date = Column(Date)
    from_time = Column(Time)
    to_date = Column(Date)
    to_time = Column(Time)
    status = Column(String)
    produced_quantity = Column(Integer)
    approved_quantity = Column(Integer)
    created_at = Column(DateTime)
    operator_status = Column(String)
    supervisor_acknowledged = Column(Boolean)
    supervisor_acknowledged_at = Column(DateTime)
    rework_quantity = Column(Integer)
    rejected_quantity = Column(Integer)
    remaining_quantity_to_be_produced = Column(Integer)
    operator_acknowledged = Column(Boolean)
    operator_acknowledged_at = Column(DateTime)

    operation = relationship("DB.models.oms.Operation")
