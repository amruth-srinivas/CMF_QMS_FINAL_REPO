from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Any, Dict, Optional

from DB.database import get_db
from services.inspection_report_data import build_inspection_report_payload
from services.inspection_report_docx import build_inspection_report_docx
from services.inspection_report_save import (
    get_saved_inspection_report_edits,
    merge_saved_edits_into_payload,
    upsert_saved_inspection_report_edits,
)

router = APIRouter(prefix="/reports", tags=["reports"])


def _docx_response(output, part_number: str, op_no: int) -> StreamingResponse:
    filename = f"Inspection_Report_{part_number}_OP{op_no}.docx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


def _report_scope_params(
    part_number: str,
    sales_order_id: int,
    op_no: int,
    quantity_no: int,
    consolidated: bool,
) -> dict:
    return {
        "part_number": part_number,
        "sales_order_id": sales_order_id,
        "op_no": op_no,
        "quantity_no": quantity_no,
        "consolidated": consolidated,
    }


@router.get("/inspection-report/saved")
def get_inspection_report_saved(
    part_number: str = Query(..., description="oms.parts.part_number"),
    sales_order_id: int = Query(...),
    op_no: int = Query(...),
    quantity_no: int = Query(1, ge=1),
    consolidated: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Load saved report edits (remarks, footer fields, signatories)."""
    saved = get_saved_inspection_report_edits(
        db, **_report_scope_params(part_number, sales_order_id, op_no, quantity_no, consolidated)
    )
    if not saved:
        return {"saved": False}
    return {"saved": True, **saved}


@router.put("/inspection-report/saved")
def put_inspection_report_saved(
    saved_payload: Dict[str, Any] = Body(...),
    part_number: str = Query(..., description="oms.parts.part_number"),
    sales_order_id: int = Query(...),
    op_no: int = Query(...),
    quantity_no: int = Query(1, ge=1),
    consolidated: bool = Query(False),
    saved_by_username: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Persist saved report edits to the database."""
    try:
        saved = upsert_saved_inspection_report_edits(
            db,
            **_report_scope_params(part_number, sales_order_id, op_no, quantity_no, consolidated),
            saved_payload=saved_payload,
            saved_by_username=saved_by_username,
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save report: {exc}") from exc
    return {"ok": True, **saved}


@router.post("/inspection-report/docx")
def post_inspection_report_docx(
    saved_payload: Dict[str, Any] = Body(...),
    part_number: str = Query(..., description="oms.parts.part_number"),
    sales_order_id: int = Query(...),
    op_no: int = Query(...),
    quantity_no: int = Query(1, ge=1),
    consolidated: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Generate Word report using saved preview edits (remarks, footer values)."""
    try:
        base = build_inspection_report_payload(
            db,
            part_number=part_number,
            sales_order_id=sales_order_id,
            op_no=op_no,
            quantity_no=quantity_no,
            consolidated=consolidated,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    payload = merge_saved_edits_into_payload(base, saved_payload)
    output = build_inspection_report_docx(payload)
    return _docx_response(output, part_number, op_no)


@router.get("/inspection-report/docx")
def get_inspection_report_docx(
    part_number: str = Query(..., description="oms.parts.part_number"),
    sales_order_id: int = Query(...),
    op_no: int = Query(...),
    quantity_no: int = Query(1, ge=1),
    consolidated: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Generate inspection report as Word (.docx) using python-docx."""
    try:
        payload = build_inspection_report_payload(
            db,
            part_number=part_number,
            sales_order_id=sales_order_id,
            op_no=op_no,
            quantity_no=quantity_no,
            consolidated=consolidated,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    saved = get_saved_inspection_report_edits(
        db, **_report_scope_params(part_number, sales_order_id, op_no, quantity_no, consolidated)
    )
    if saved:
        payload = merge_saved_edits_into_payload(payload, saved)

    output = build_inspection_report_docx(payload)
    return _docx_response(output, part_number, op_no)
