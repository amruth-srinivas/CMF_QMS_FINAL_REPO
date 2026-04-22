from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, TIMESTAMP, func
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
