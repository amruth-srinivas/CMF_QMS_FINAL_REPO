from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import exists
from DB.database import get_db
from DB.models.oms import Order, Part, Operation
from DB.models.scheduling import PartScheduleStatus, OrderScheduleStatus

router = APIRouter(prefix="/scheduling", tags=["Scheduling"])


@router.get("/orders-parts-status")
def get_all_orders_parts_status(db: Session = Depends(get_db)):
    orders = db.query(Order).all()
    response = []

    for order in orders:
        product = order.product
        if not product:
            continue

        # get parts of this product
        parts = db.query(Part).filter(Part.product_id == product.id).all()

        # get schedule records for this order
        schedule_records = db.query(PartScheduleStatus).filter(
            PartScheduleStatus.sale_order_id == order.id
        ).all()

        # create lookup dictionary
        schedule_map = {r.part_id: r for r in schedule_records}

        # build a supervisor lookup per part using operation assignees
        part_ids = [part.id for part in parts]
        supervisor_map = {}
        if part_ids:
            operations = db.query(Operation).filter(Operation.part_id.in_(part_ids)).all()
            for op in operations:
                if op.user and op.user.user_name:
                    supervisor_map.setdefault(op.part_id, set()).add(op.user.user_name)

        mc_name = (
            order.manufacturing_coordinator.user_name
            if order.manufacturing_coordinator
            else None
        )

        for part in parts:
            status_record = schedule_map.get(part.id)
            supervisors = sorted(supervisor_map.get(part.id, set()))

            response.append({
                "sale_order_id": order.id,
                "sale_order_number": order.sale_order_number,
                "product_id": product.id,
                "product_name": product.product_name,
                "mc": mc_name,
                "supervisors": supervisors,
                "part_id": part.id,
                "part_number": part.part_number,
                "part_name": part.part_name,
                "part_type": part.type.type_name if part.type else None,
                "status": status_record.status if status_record else "inactive",
                "start_date": getattr(status_record, "start_date", None) if status_record else None
            })

    response.sort(
        key=lambda x: (
            (x.get("mc") or "").lower(),
            ", ".join(x.get("supervisors") or []).lower(),
            x.get("sale_order_number") or "",
            x.get("part_number") or "",
        )
    )

    return {"orders": response}

@router.get("/order-status/{sale_order_id}")
def get_order_status(sale_order_id: int, db: Session = Depends(get_db)):
    """
    Order is active if any part is active.
    Otherwise inactive.
    """
    order = db.query(Order).filter(Order.id == sale_order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")

    # check if ANY active part exists
    active_exists = db.query(
        exists().where(
            PartScheduleStatus.sale_order_id == sale_order_id,
            PartScheduleStatus.status == "active"
        )
    ).scalar()

    order_status = "active" if active_exists else "inactive"

    return {
        "order_id": sale_order_id,
        "sale_order_number": order.sale_order_number,
        "order_status": order_status
    }
