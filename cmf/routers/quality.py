"""
Quality schema API: Master BOC (bill of characteristics) persistence aligned with DB.models.quality.MasterBoc.
"""
import json
from datetime import datetime, timezone

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
# pyrefly: ignore [missing-import]
from sqlalchemy import and_, or_, func
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session, aliased
from typing import List, Optional

from DB.database import get_db
from DB.models.inventory import ToolsList as ToolsListModel, Category
from DB.models.quality import MasterBoc, StageInspection, Note, InspectionPlanStatus, FTP
from DB.schemas.inventory import ToolsList
from DB.models.notifications import InspectionPlanNotification
from DB.models.oms import Part, Order, Operation
from DB.models.scheduling import ProductionLog
from DB.models.access_control import AccessUser
from DB.schemas.quality_api import (
    MasterBocBulkCreate,
    MasterBocCreate,
    MasterBocResponse,
    MasterBocUpdate,
    StageInspectionResponse,
    StageInspectionUpdate,
    StageInspectionMeasurementSummary,
    FTPStatusUpsert,
    FTPStatusResponse,
    NoteCreate,
    NoteUpdate,
    NoteResponse,
    InspectionPlanStatusUpsert,
    InspectionPlanStatusResponse,
    OperationProductionSummaryItem,
)

router = APIRouter(prefix="/quality", tags=["quality"])

_ALLOWED_INSPECTION_PLAN_STATUS = frozenset({"draft", "confirmed"})
_ALLOWED_FTP_STATUS = frozenset({"pending", "approved", "rejected"})


def _master_boc_id_from_stage_bbox(bbox: Optional[str]) -> Optional[int]:
    if not bbox or not bbox.strip():
        return None
    try:
        o = json.loads(bbox)
        mid = o.get("master_boc_id")
        if mid is None:
            return None
        return int(mid)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _resolve_stage_inspection_user_id(db: Session, requested: Optional[int]) -> int:
    """
    quality.stage_inspection.user_id is NOT NULL in PostgreSQL. Always return an integer:
    use the query param when provided (even if not present in access_users), else first user or 1.
    """
    if requested is not None:
        return requested
    u = db.query(AccessUser).order_by(AccessUser.id.asc()).first()
    return u.id if u is not None else 1


def _normalized_ipid(ipid: Optional[str], op_no: Optional[int]) -> str:
    raw = (ipid or "").strip()
    if raw and raw.upper() != "AUTO":
        return raw[:255]
    if op_no is not None:
        return f"OP_{op_no}"[:255]
    return "AUTO"


def _serialize_tools_list_row(
    tool: ToolsListModel,
    category_name: Optional[str],
    sub_category_name: Optional[str],
) -> ToolsList:
    item = ToolsList.model_validate(tool)
    item.category_name = category_name
    item.sub_category_name = sub_category_name
    return item


def _query_tools_with_categories(
    db: Session,
    category: Optional[str] = None,
    sub_category: Optional[str] = None,
):
    cat = aliased(Category)
    sub = aliased(Category)
    q = (
        db.query(ToolsListModel, cat.name, sub.name)
        .outerjoin(cat, ToolsListModel.category_id == cat.id)
        .outerjoin(sub, ToolsListModel.sub_category_id == sub.id)
    )
    if category:
        q = q.filter(func.lower(cat.name) == category.strip().lower())
    if sub_category:
        q = q.filter(func.lower(sub.name) == sub_category.strip().lower())
    return q.order_by(ToolsListModel.id.asc()).all()


def _is_ftp_approved(db: Session, order_id: int, ipid: str) -> bool:
    row = (
        db.query(FTP)
        .filter(
            FTP.order_id == order_id,
            FTP.ipid == ipid,
        )
        .first()
    )
    return bool(row and row.status == "approved" and row.is_completed)


@router.get("/inspection-plan-status", response_model=List[InspectionPlanStatusResponse])
def list_inspection_plan_status(
    part_number: str = Query(..., description="oms.parts.part_number"),
    sales_order_id: int = Query(...),
    op_no: Optional[int] = Query(None, description="Filter by operation number; omit for all ops on this part/order"),
    db: Session = Depends(get_db),
):
    q = db.query(InspectionPlanStatus).filter(
        InspectionPlanStatus.part_number == part_number.strip(),
        InspectionPlanStatus.sales_order_id == sales_order_id,
    )
    if op_no is not None:
        q = q.filter(InspectionPlanStatus.op_no == op_no)
    return q.order_by(InspectionPlanStatus.op_no.asc()).all()


def _parse_op_no(operation_number: Optional[str]) -> int:
    try:
        n = int(str(operation_number or "").strip())
        return n if n >= 0 else 10
    except (TypeError, ValueError):
        return 10


def _latest_production_log_by_operation(
    db: Session, operation_ids: List[int]
) -> dict[int, ProductionLog]:
    if not operation_ids:
        return {}
    logs = (
        db.query(ProductionLog)
        .filter(ProductionLog.operation_id.in_(operation_ids))
        .order_by(
            ProductionLog.operation_id.asc(),
            ProductionLog.created_at.desc(),
            ProductionLog.id.desc(),
        )
        .all()
    )
    latest: dict[int, ProductionLog] = {}
    for log in logs:
        if log.operation_id not in latest:
            latest[log.operation_id] = log
    return latest


@router.get("/operation-production-summary", response_model=List[OperationProductionSummaryItem])
def operation_production_summary(
    part_id: int = Query(..., description="oms.parts.id"),
    db: Session = Depends(get_db),
):
    """Per-operation qty/yield from part quantity and the latest production log row."""
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")

    required_qty = max(1, int(part.qty or 1))
    operations = (
        db.query(Operation)
        .filter(Operation.part_id == part_id)
        .order_by(Operation.operation_number.asc())
        .all()
    )
    op_ids = [op.id for op in operations]
    latest_by_op = _latest_production_log_by_operation(db, op_ids)

    results: List[OperationProductionSummaryItem] = []
    for op in operations:
        latest = latest_by_op.get(op.id)
        completed = int(latest.produced_quantity or 0) if latest else 0
        accepted = int(latest.approved_quantity or 0) if latest else 0
        rejected = 0
        if latest:
            rejected = int(latest.rejected_quantity or 0) + int(latest.rework_quantity or 0)
        yield_pct = round((accepted / completed) * 100, 1) if completed > 0 else 0.0
        results.append(
            OperationProductionSummaryItem(
                operation_id=op.id,
                op_no=_parse_op_no(op.operation_number),
                required_quantity=required_qty,
                completed_quantity=completed,
                accepted_quantity=accepted,
                rejected_quantity=rejected,
                yield_percentage=yield_pct,
            )
        )
    return results


@router.get("/ftp-status", response_model=Optional[FTPStatusResponse])
def get_ftp_status(
    order_id: int = Query(...),
    ipid: str = Query(...),
    op_no: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    norm_ipid = _normalized_ipid(ipid, op_no)
    row = (
        db.query(FTP)
        .filter(
            FTP.order_id == order_id,
            FTP.ipid == norm_ipid,
        )
        .first()
    )
    return row


@router.put("/ftp-status", response_model=FTPStatusResponse)
def upsert_ftp_status(body: FTPStatusUpsert, db: Session = Depends(get_db)):
    norm_ipid = _normalized_ipid(body.ipid, None)
    st = (body.status or "pending").strip().lower()
    if st not in _ALLOWED_FTP_STATUS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of: {', '.join(sorted(_ALLOWED_FTP_STATUS))}",
        )
    row = (
        db.query(FTP)
        .filter(
            FTP.order_id == body.order_id,
            FTP.ipid == norm_ipid,
        )
        .first()
    )
    completed = body.is_completed if body.is_completed is not None else (st == "approved")
    if row:
        row.status = st
        row.is_completed = bool(completed)
        if st == "approved":
            row.approved_by_username = body.approved_by_username
            row.approved_at = body.approved_at or func.now()
    else:
        row = FTP(
            order_id=body.order_id,
            ipid=norm_ipid,
            status=st,
            is_completed=bool(completed),
            approved_by_username=body.approved_by_username if st == "approved" else None,
            approved_at=(body.approved_at or func.now()) if st == "approved" else None,
        )
        db.add(row)
    db.commit()
    db.refresh(row)

    # Create notification if pending
    if st == "pending" and body.part_number and body.op_no and body.operation_id:
        existing_notif = db.query(InspectionPlanNotification).filter(
            InspectionPlanNotification.order_id == body.order_id,
            InspectionPlanNotification.part_number == body.part_number,
            InspectionPlanNotification.op_no == body.op_no,
            InspectionPlanNotification.category == "ftp_request",
            InspectionPlanNotification.is_ack.is_(False)
        ).first()
        if not existing_notif:
            notif = InspectionPlanNotification(
                order_id=body.order_id,
                part_number=body.part_number,
                op_no=body.op_no,
                operation_id=body.operation_id,
                requested_by_username=body.requested_by_username,
                category="ftp_request"
            )
            db.add(notif)
            db.commit()

    return row


@router.put("/inspection-plan-status", response_model=InspectionPlanStatusResponse)
def upsert_inspection_plan_status(body: InspectionPlanStatusUpsert, db: Session = Depends(get_db)):
    pn = (body.part_number or "").strip()
    if not pn:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="part_number is required")
    st = (body.status or "draft").strip().lower()
    if st not in _ALLOWED_INSPECTION_PLAN_STATUS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of: {', '.join(sorted(_ALLOWED_INSPECTION_PLAN_STATUS))}",
        )
    part = db.query(Part).filter(Part.part_number == pn).first()
    if not part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Part number not found: {pn}")
    order = db.query(Order).filter(Order.id == body.sales_order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Order not found: {body.sales_order_id}")

    row = (
        db.query(InspectionPlanStatus)
        .filter(
            InspectionPlanStatus.part_number == pn,
            InspectionPlanStatus.sales_order_id == body.sales_order_id,
            InspectionPlanStatus.op_no == body.op_no,
        )
        .first()
    )
    if row:
        row.status = st
    else:
        row = InspectionPlanStatus(
            part_number=pn,
            sales_order_id=body.sales_order_id,
            op_no=body.op_no,
            status=st,
        )
        db.add(row)

    if st == "confirmed":
        raw_name = (body.confirmed_by_username or "").strip()
        row.confirmed_by_username = raw_name[:255] if raw_name else None
        ack_name = raw_name or "Supervisor"
        now = datetime.now(timezone.utc)
        pending_plan_notifs = (
            db.query(InspectionPlanNotification)
            .filter(
                InspectionPlanNotification.order_id == body.sales_order_id,
                InspectionPlanNotification.part_number == pn,
                InspectionPlanNotification.op_no == body.op_no,
                InspectionPlanNotification.category == "plan_request",
                InspectionPlanNotification.is_ack.is_(False),
            )
            .all()
        )
        for notif in pending_plan_notifs:
            notif.is_ack = True
            notif.ack_by = ack_name[:255]
            notif.ack_at = now
    else:
        row.confirmed_by_username = None

    db.commit()
    db.refresh(row)
    return row


@router.get("/master-boc", response_model=List[MasterBocResponse])
def list_master_boc_for_plan(
    part_id: str = Query(..., description="Part number (oms.parts.part_number)"),
    sales_order_id: int = Query(...),
    op_no: Optional[int] = Query(None, description="Filter by operation number; omit for all ops"),
    db: Session = Depends(get_db),
):
    """List Master BOC rows for a part + sales order (Inspector plan / characteristics panel)."""
    q = db.query(MasterBoc).filter(
        MasterBoc.part_id == part_id,
        MasterBoc.sales_order_id == sales_order_id,
    )
    if op_no is not None:
        q = q.filter(MasterBoc.op_no == op_no)
    return q.order_by(MasterBoc.id.asc()).all()


@router.post("/master-boc/bulk", response_model=List[MasterBocResponse])
def create_master_boc_bulk(payload: MasterBocBulkCreate, db: Session = Depends(get_db)):
    """Create multiple Master BOC rows (e.g. after PDF region detection)."""
    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="items is required")
    resolved_user_id = None
    if payload.user_id:
        user_exists = db.query(AccessUser).filter(AccessUser.id == payload.user_id).first()
        if user_exists:
            resolved_user_id = payload.user_id

    created = []
    for item in payload.items:
        part = db.query(Part).filter(Part.part_number == item.part_id).first()
        if not part:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Part number not found: {item.part_id}",
            )
        order = db.query(Order).filter(Order.id == item.sales_order_id).first()
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order not found: {item.sales_order_id}",
            )
        row = MasterBoc(
            part_id=item.part_id,
            sales_order_id=item.sales_order_id,
            nominal=item.nominal,
            uppertol=item.uppertol,
            lowertol=item.lowertol,
            zone=item.zone,
            dimension_type=item.dimension_type,
            measured_instrument=(item.measured_instrument or "").strip() or "default",
            op_no=item.op_no,
            bbox=item.bbox,
            ipid=item.ipid,
            user_id=resolved_user_id,
        )
        db.add(row)
        created.append(row)
    db.commit()
    for row in created:
        db.refresh(row)
    return created


@router.get("/master-boc/order/{order_id}", response_model=List[MasterBocResponse])
def list_master_boc_by_order(order_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(MasterBoc)
        .filter(MasterBoc.sales_order_id == order_id)
        .order_by(MasterBoc.id.asc())
        .all()
    )
    return rows


@router.get("/master-boc/part/{part_number}", response_model=List[MasterBocResponse])
def list_master_boc_by_part(part_number: str, db: Session = Depends(get_db)):
    rows = (
        db.query(MasterBoc)
        .filter(MasterBoc.part_id == part_number)
        .order_by(MasterBoc.id.asc())
        .all()
    )
    return rows


@router.delete("/master-boc/{row_id}")
def delete_master_boc_row(row_id: int, db: Session = Depends(get_db)):
    row = db.query(MasterBoc).filter(MasterBoc.id == row_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Master BOC row not found")
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/master-boc/{row_id}", response_model=MasterBocResponse)
def patch_master_boc_row(row_id: int, body: MasterBocUpdate, db: Session = Depends(get_db)):
    row = db.query(MasterBoc).filter(MasterBoc.id == row_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Master BOC row not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


@router.get("/stage-inspection", response_model=List[StageInspectionResponse])
def list_stage_inspection(
    part_id: int = Query(..., description="OMS parts.id (integer)"),
    sale_order_id: int = Query(...),
    op_no: int = Query(...),
    quantity_no: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    """Stage inspection rows for measure mode (linked to master BOC via bbox JSON master_boc_id)."""
    q = db.query(StageInspection).filter(
        StageInspection.part_id == part_id,
        StageInspection.sale_order_id == sale_order_id,
        StageInspection.op_no == op_no,
    )
    q = q.filter(
        or_(
            StageInspection.quantity_no == quantity_no,
            and_(StageInspection.quantity_no.is_(None), quantity_no == 1),
        )
    )
    return q.order_by(StageInspection.id.asc()).all()


def _stage_row_has_measurement(row: StageInspection) -> bool:
    if row.measurements:
        for v in row.measurements:
            if str(v).strip():
                return True
    if row.measured_mean and str(row.measured_mean).strip():
        return True
    return False


@router.get("/stage-inspection/measurement-summary", response_model=StageInspectionMeasurementSummary)
def stage_inspection_measurement_summary(
    part_id: int = Query(..., description="OMS parts.id (integer)"),
    sale_order_id: int = Query(...),
    op_no: int = Query(...),
    db: Session = Depends(get_db),
):
    """Across all quantity rows: whether any measurement value has been entered and if Qty 1 is fully finished."""
    rows = db.query(StageInspection).filter(
        StageInspection.part_id == part_id,
        StageInspection.sale_order_id == sale_order_id,
        StageInspection.op_no == op_no,
    ).all()
    
    any_recorded = any(_stage_row_has_measurement(r) for r in rows)
    
    qty1_complete = False
    if rows:
        part_number = db.query(Part).filter(Part.id == part_id).value(Part.part_number)
        if part_number:
            masters_count = db.query(MasterBoc).filter(
                MasterBoc.part_id == part_number,
                MasterBoc.sales_order_id == sale_order_id,
                MasterBoc.op_no == op_no
            ).count()
            
            if masters_count > 0:
                # Count how many Qty 1 rows have at least one measurement
                qty1_rows = [r for r in rows if (r.quantity_no == 1 or r.quantity_no is None)]
                qty1_measured_count = sum(1 for r in qty1_rows if _stage_row_has_measurement(r))
                print(f"DEBUG: part_id={part_id} op_no={op_no} masters={masters_count} qty1_measured={qty1_measured_count}")
                qty1_complete = (qty1_measured_count >= masters_count)
    
    # Get the max quantity for this part from the parts table
    qty_max = db.query(Part.qty).filter(Part.id == part_id).scalar() or 1

    return StageInspectionMeasurementSummary(any_recorded=any_recorded, qty1_complete=qty1_complete, qty_max=qty_max)


def _master_boc_id_from_stage_bbox(bbox_str: str) -> Optional[int]:
    if not bbox_str:
        return None
    try:
        o = json.loads(bbox_str)
        mid = o.get("master_boc_id")
        return int(mid) if mid is not None else None
    except:
        return None


def _master_boc_id_from_stage_bbox(bbox_str: str) -> Optional[int]:
    if not bbox_str:
        return None
    try:
        o = json.loads(bbox_str)
        mid = o.get("master_boc_id")
        return int(mid) if mid is not None else None
    except:
        return None


@router.post("/stage-inspection/ensure", response_model=List[StageInspectionResponse])
def ensure_stage_inspection_rows(
    part_id: int = Query(..., description="OMS parts.id"),
    part_number: str = Query(..., description="Part number for MasterBoc.part_id"),
    sale_order_id: int = Query(...),
    op_no: int = Query(...),
    quantity_no: int = Query(1, ge=1),
    user_id: Optional[int] = Query(None),
    ipid: Optional[str] = Query(None, description="FTP key for this operation"),
    db: Session = Depends(get_db),
):
    """
    For each Master BOC row for this part/order/op, ensure a StageInspection row exists
    with bbox {\"master_boc_id\": <id>} so measure fields can be edited.
    """
    resolved_user_id = _resolve_stage_inspection_user_id(db, user_id)
    norm_ipid = _normalized_ipid(ipid, op_no)
    if quantity_no > 1 and not _is_ftp_approved(db, sale_order_id, norm_ipid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FTP approval is required before measuring quantity 2 or above.",
        )

    masters = (
        db.query(MasterBoc)
        .filter(
            MasterBoc.part_id == part_number,
            MasterBoc.sales_order_id == sale_order_id,
            MasterBoc.op_no == op_no,
        )
        .order_by(MasterBoc.id.asc())
        .all()
    )

    existing = (
        db.query(StageInspection)
        .filter(
            StageInspection.part_id == part_id,
            StageInspection.sale_order_id == sale_order_id,
            StageInspection.op_no == op_no,
        )
        .all()
    )
    by_master_qty: dict[tuple[int, int], StageInspection] = {}
    for row in existing:
        mid = None
        try:
            mid = _master_boc_id_from_stage_bbox(row.bbox)
        except:
            pass

        if mid is None:
            # Fallback for older rows: match by characteristic values
            for m in masters:
                if (str(m.nominal) == str(row.nominal_value) and 
                    str(m.zone) == str(row.zone) and 
                    str(m.dimension_type) == str(row.dimension_type)):
                    mid = m.id
                    try:
                        row.bbox = json.dumps({"master_boc_id": mid})
                    except:
                        pass
                    break
        
        if mid is not None:
            try:
                row_q = int(row.quantity_no) if row.quantity_no is not None else 1
                by_master_qty[(mid, row_q)] = row
            except:
                continue

    for m in masters:
        key = (m.id, int(quantity_no))
        if key in by_master_qty:
            continue
        bbox = json.dumps({"master_boc_id": m.id})
        inst = (m.measured_instrument or "").strip() or "default"
        new_row = StageInspection(
            user_id=resolved_user_id,
            part_id=part_id,
            sale_order_id=sale_order_id,
            nominal_value=m.nominal,
            uppertol=m.uppertol,
            lowertol=m.lowertol,
            zone=m.zone,
            dimension_type=m.dimension_type,
            measurements=[],
            measured_mean="",
            measured_instrument=inst,
            used_inst="",
            op_no=m.op_no,
            quantity_no=quantity_no,
            bbox=bbox,
            is_done=False,
        )
        db.add(new_row)
        by_master_qty[key] = new_row

    db.commit()
    return (
        db.query(StageInspection)
        .filter(
            StageInspection.part_id == part_id,
            StageInspection.sale_order_id == sale_order_id,
            StageInspection.op_no == op_no,
        )
        .filter(
            or_(
                StageInspection.quantity_no == quantity_no,
                and_(StageInspection.quantity_no.is_(None), quantity_no == 1),
            )
        )
        .order_by(StageInspection.id.asc())
        .all()
    )


@router.patch("/stage-inspection/{row_id}", response_model=StageInspectionResponse)
def patch_stage_inspection(
    row_id: int,
    body: StageInspectionUpdate,
    db: Session = Depends(get_db),
):
    row = db.query(StageInspection).filter(StageInspection.id == row_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage inspection row not found")
    row_q = row.quantity_no if row.quantity_no is not None else 1
    if row_q > 1:
        mid = _master_boc_id_from_stage_bbox(row.bbox)
        master = db.query(MasterBoc).filter(MasterBoc.id == mid).first() if mid is not None else None
        norm_ipid = _normalized_ipid(master.ipid if master else None, row.op_no)
        if not _is_ftp_approved(db, row.sale_order_id, norm_ipid):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="FTP approval is required before measuring quantity 2 or above.",
            )
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    try:
        db.commit()
        db.refresh(row)
        return row
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notes", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
def create_note(body: NoteCreate, db: Session = Depends(get_db)):
    row = Note(**body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/notes/part/{part_id}", response_model=List[NoteResponse])
def get_notes_by_part(
    part_id: int,
    document_id: Optional[int] = Query(None),
    op_no: Optional[int] = Query(None),
    is_operation_document: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Note).filter(Note.part_id == part_id)
    if document_id is not None:
        q = q.filter(Note.document_id == document_id)
    if op_no is not None:
        q = q.filter(Note.op_no == op_no)
    if is_operation_document is not None:
        q = q.filter(Note.is_operation_document == is_operation_document)
    return q.order_by(Note.id.asc()).all()


@router.put("/notes/{note_id}", response_model=NoteResponse)
def update_note(note_id: int, body: NoteUpdate, db: Session = Depends(get_db)):
    row = db.query(Note).filter(Note.id == note_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: int, db: Session = Depends(get_db)):
    row = db.query(Note).filter(Note.id == note_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/notes/part/{part_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notes_for_part(
    part_id: int,
    document_id: Optional[int] = Query(None),
    op_no: Optional[int] = Query(None),
    is_operation_document: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Note).filter(Note.part_id == part_id)
    if document_id is not None:
        q = q.filter(Note.document_id == document_id)
    if op_no is not None:
        q = q.filter(Note.op_no == op_no)
    if is_operation_document is not None:
        q = q.filter(Note.is_operation_document == is_operation_document)
    q.delete()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/instruments", response_model=List[ToolsList])
def list_instruments(
    category: Optional[str] = Query(None),
    sub_category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """List inventory instruments/tools with calibration fields for QMS inspector."""
    rows = _query_tools_with_categories(db, category=category, sub_category=sub_category)
    return [_serialize_tools_list_row(tool, cat_name, sub_name) for tool, cat_name, sub_name in rows]


@router.get("/instruments/category/{category}/sub/{sub_category}", response_model=List[ToolsList])
def list_instruments_by_sub_category(
    category: str,
    sub_category: str,
    db: Session = Depends(get_db),
):
    """List instruments in a category/sub-category, including calibration_due_date."""
    rows = _query_tools_with_categories(db, category=category, sub_category=sub_category)
    return [_serialize_tools_list_row(tool, cat_name, sub_name) for tool, cat_name, sub_name in rows]
