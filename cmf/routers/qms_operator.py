"""
Operator-facing QMS helpers: in-progress operations from scheduling service + local plan flags.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import exists
from sqlalchemy.orm import Session, joinedload

from DB.database import get_db
from DB.models.notifications import InspectionPlanNotification
from DB.models.oms import Operation, OperationDocument, Order, Part
from DB.models.quality import InspectionPlanStatus

router = APIRouter(prefix="/operator", tags=["operator-qms"])

SCHEDULING_API_BASE_URL = os.getenv(
    "SCHEDULING_API_BASE_URL",
    "http://172.18.7.85:8989/api/v1",
).rstrip("/")


def _fetch_scheduling_inprogress(machine_id: int) -> Dict[str, Any]:
    url = f"{SCHEDULING_API_BASE_URL}/scheduling/inprogress-operations/{machine_id}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode() or str(e.reason)
        raise HTTPException(status_code=e.code if 400 <= e.code < 600 else 502, detail=detail)
    except urllib.error.URLError as e:
        raise HTTPException(status_code=502, detail=f"Scheduling service unreachable: {e.reason}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Scheduling service error: {e}")


def _parse_op_no(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    try:
        s = str(raw).strip()
        if not s:
            return None
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _has_inspection_plan(db: Session, part_number: str, order_id: int, op_no: Optional[int]) -> bool:
    """
    Operators only see a released plan after a supervisor confirms it (quality.inspection_plan_status.status = confirmed).
    Draft plans or Master BOC rows alone do not unlock the operator queue.
    """
    if not part_number or not part_number.strip() or op_no is None:
        return False
    pn = part_number.strip()
    confirmed = db.query(
        exists().where(
            InspectionPlanStatus.part_number == pn,
            InspectionPlanStatus.sales_order_id == order_id,
            InspectionPlanStatus.op_no == op_no,
            InspectionPlanStatus.status == "confirmed",
        )
    ).scalar()
    return bool(confirmed)


def _first_operation_document(db: Session, operation_id: int) -> Optional[OperationDocument]:
    return (
        db.query(OperationDocument)
        .filter(OperationDocument.operation_id == operation_id)
        .order_by(OperationDocument.id.asc())
        .first()
    )


@router.get("/machine-inprogress/{machine_id}")
def get_machine_inprogress_with_plan(machine_id: int, db: Session = Depends(get_db)):
    """
    Proxies scheduling in-progress operations and adds has_inspection_plan and preview document hints.
    """
    data = _fetch_scheduling_inprogress(machine_id)
    operations: List[Dict[str, Any]] = list(data.get("operations") or [])
    enriched: List[Dict[str, Any]] = []

    for op in operations:
        order_id = op.get("order_id")
        part_number = op.get("part_number") or ""
        operation_id = op.get("operation_id")
        op_no = _parse_op_no(op.get("operation_number"))

        has_plan = False
        preview_document_id = None
        preview_endpoint: Optional[str] = None
        preview_document_name: Optional[str] = None
        project_name = None
        sale_order_number = None

        if order_id is not None:
            ord_row = (
                db.query(Order)
                .options(joinedload(Order.product))
                .filter(Order.id == order_id)
                .first()
            )
            if ord_row:
                sale_order_number = ord_row.sale_order_number
                if ord_row.product:
                    project_name = ord_row.product.product_name

        if isinstance(operation_id, int):
            doc = _first_operation_document(db, operation_id)
            if doc:
                preview_document_id = doc.id
                preview_endpoint = "operation-documents"
                preview_document_name = doc.document_name

        if isinstance(order_id, int) and part_number:
            has_plan = _has_inspection_plan(db, part_number, order_id, op_no)

        row = {**op}
        row["op_no"] = op_no
        row["has_inspection_plan"] = has_plan
        row["preview_document_id"] = preview_document_id
        row["preview_endpoint"] = preview_endpoint
        row["preview_document_name"] = preview_document_name
        row["project_name"] = project_name
        row["sale_order_number"] = sale_order_number
        enriched.append(row)

    return {
        "machine_id": data.get("machine_id", machine_id),
        "machine_name": data.get("machine_name"),
        "total_inprogress_operations": data.get("total_inprogress_operations", len(enriched)),
        "operations": enriched,
    }


class InspectionPlanRequestBody(BaseModel):
    machine_id: int = Field(..., description="Machine the operator is logged into")
    order_id: int
    part_id: int
    operation_id: int
    part_number: Optional[str] = Field(None, description="Part number (optional if part_id resolves)")
    op_no: Optional[int] = Field(None, description="Operation number; optional if operation_id resolves")
    requested_by_username: Optional[str] = Field(None, description="Operator login name")


class InspectionPlanAckBody(BaseModel):
    ack_by: str = Field(..., min_length=1, description="Supervisor user_name")


class InspectionPlanNotificationItem(BaseModel):
    id: int
    order_id: int
    sale_order_number: Optional[str] = None
    part_number: str
    op_no: int
    operation_id: int
    machine_id: Optional[int] = None
    requested_by_username: Optional[str] = None
    is_ack: bool
    ack_by: Optional[str] = None
    ack_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


def _resolve_part_number(db: Session, part_id: int, hint: Optional[str]) -> str:
    if hint and str(hint).strip():
        return str(hint).strip()
    p = db.query(Part).filter(Part.id == part_id).first()
    if not p or not (p.part_number or "").strip():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
    return str(p.part_number).strip()


def _resolve_op_no(db: Session, operation_id: int, hint: Optional[int]) -> int:
    if hint is not None:
        return int(hint)
    op_row = db.query(Operation).filter(Operation.id == operation_id).first()
    if not op_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operation not found")
    parsed = _parse_op_no(op_row.operation_number)
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not parse operation number for this operation",
        )
    return parsed


@router.post("/request-inspection-plan")
def request_inspection_plan(body: InspectionPlanRequestBody, db: Session = Depends(get_db)):
    """
    Persist a notification for supervisors: operator needs a confirmed inspection plan
    for this in-progress order line.
    """
    order = db.query(Order).filter(Order.id == body.order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    pn = _resolve_part_number(db, body.part_id, body.part_number)
    op_no = _resolve_op_no(db, body.operation_id, body.op_no)

    pending = (
        db.query(InspectionPlanNotification)
        .filter(
            InspectionPlanNotification.order_id == body.order_id,
            InspectionPlanNotification.part_number == pn,
            InspectionPlanNotification.op_no == op_no,
            InspectionPlanNotification.is_ack.is_(False),
        )
        .first()
    )
    if pending:
        return {
            "status": "already_pending",
            "message": "A request for this order and operation is already pending supervisor review.",
            "id": pending.id,
            "order_id": body.order_id,
            "part_number": pn,
            "op_no": op_no,
        }

    req_name = (body.requested_by_username or "").strip() or None
    row = InspectionPlanNotification(
        order_id=body.order_id,
        part_number=pn,
        op_no=op_no,
        operation_id=body.operation_id,
        machine_id=body.machine_id,
        requested_by_username=req_name,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "status": "created",
        "message": "Supervisors have been notified. They can acknowledge this request and create the inspection plan in Quality Management.",
        "id": row.id,
        "order_id": row.order_id,
        "part_number": row.part_number,
        "op_no": row.op_no,
    }


@router.get("/inspection-plan-notifications", response_model=List[InspectionPlanNotificationItem])
def list_inspection_plan_notifications(
    only_pending: bool = Query(False, description="If true, only rows not yet acknowledged"),
    db: Session = Depends(get_db),
):
    """Supervisor / admin: list inspection plan requests (newest first)."""
    q = (
        db.query(InspectionPlanNotification, Order.sale_order_number)
        .join(Order, Order.id == InspectionPlanNotification.order_id)
        .order_by(InspectionPlanNotification.created_at.desc())
    )
    if only_pending:
        q = q.filter(InspectionPlanNotification.is_ack.is_(False))
    rows = q.all()
    out: List[InspectionPlanNotificationItem] = []
    for n, sale_no in rows:
        out.append(
            InspectionPlanNotificationItem(
                id=n.id,
                order_id=n.order_id,
                sale_order_number=sale_no,
                part_number=n.part_number,
                op_no=n.op_no,
                operation_id=n.operation_id,
                machine_id=n.machine_id,
                requested_by_username=n.requested_by_username,
                is_ack=bool(n.is_ack),
                ack_by=n.ack_by,
                ack_at=n.ack_at,
                created_at=n.created_at,
                updated_at=n.updated_at,
            )
        )
    return out


@router.put("/inspection-plan-notifications/{notification_id}/ack")
def ack_inspection_plan_notification(
    notification_id: int,
    body: InspectionPlanAckBody,
    db: Session = Depends(get_db),
):
    """Supervisor acknowledges — then create/confirm the plan in Quality Management."""
    row = db.query(InspectionPlanNotification).filter(InspectionPlanNotification.id == notification_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if row.is_ack:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already acknowledged")
    ack_name = (body.ack_by or "").strip()
    if not ack_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ack_by is required")
    row.is_ack = True
    row.ack_by = ack_name[:255]
    row.ack_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return {
        "status": "ok",
        "id": row.id,
        "is_ack": row.is_ack,
        "ack_by": row.ack_by,
        "ack_at": row.ack_at,
    }
