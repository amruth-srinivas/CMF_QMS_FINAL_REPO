"""Persist and load saved inspection report edits."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from DB.models.quality import InspectionReportSave


def _find_save_row(
    db: Session,
    *,
    part_number: str,
    sales_order_id: int,
    op_no: int,
    quantity_no: int,
    consolidated: bool,
) -> Optional[InspectionReportSave]:
    return (
        db.query(InspectionReportSave)
        .filter(
            InspectionReportSave.part_number == part_number,
            InspectionReportSave.sales_order_id == sales_order_id,
            InspectionReportSave.op_no == op_no,
            InspectionReportSave.quantity_no == quantity_no,
            InspectionReportSave.consolidated == consolidated,
        )
        .first()
    )


def saved_edits_to_dict(row: InspectionReportSave) -> Dict[str, Any]:
    remarks = row.row_remarks or []
    if isinstance(remarks, dict) and remarks.get("sheets"):
        sheets = remarks.get("sheets") or []
        return {
            "sheets": sheets,
            "rows": [{"remarks": r.get("remarks", "")} for sheet in sheets for r in (sheet.get("rows") or [])],
            "footerRows": row.footer_rows or [],
            "inspectedBy": row.inspected_by or "",
            "checkedBy": row.checked_by or "",
            "savedAt": row.updated_at.isoformat() if row.updated_at else None,
            "savedByUsername": row.saved_by_username,
        }
    return {
        "rows": [{"remarks": item.get("remarks", "")} for item in remarks],
        "footerRows": row.footer_rows or [],
        "inspectedBy": row.inspected_by or "",
        "checkedBy": row.checked_by or "",
        "savedAt": row.updated_at.isoformat() if row.updated_at else None,
        "savedByUsername": row.saved_by_username,
    }


def get_saved_inspection_report_edits(
    db: Session,
    *,
    part_number: str,
    sales_order_id: int,
    op_no: int,
    quantity_no: int = 1,
    consolidated: bool = False,
) -> Optional[Dict[str, Any]]:
    row = _find_save_row(
        db,
        part_number=part_number,
        sales_order_id=sales_order_id,
        op_no=op_no,
        quantity_no=quantity_no,
        consolidated=consolidated,
    )
    if not row:
        return None
    return saved_edits_to_dict(row)


def upsert_saved_inspection_report_edits(
    db: Session,
    *,
    part_number: str,
    sales_order_id: int,
    op_no: int,
    quantity_no: int,
    consolidated: bool,
    saved_payload: Dict[str, Any],
    saved_by_username: Optional[str] = None,
) -> Dict[str, Any]:
    row = _find_save_row(
        db,
        part_number=part_number,
        sales_order_id=sales_order_id,
        op_no=op_no,
        quantity_no=quantity_no,
        consolidated=consolidated,
    )

    rows: List[Dict[str, Any]] = saved_payload.get("rows") or []
    sheets: List[Dict[str, Any]] = saved_payload.get("sheets") or []
    if consolidated and sheets:
        row_remarks = {
            "sheets": [
                {
                    "rows": [{"index": i, "remarks": str(r.get("remarks") or "")} for i, r in enumerate(sheet.get("rows") or [])],
                    "footerRows": sheet.get("footerRows"),
                    "inspectedBy": sheet.get("inspectedBy"),
                    "checkedBy": sheet.get("checkedBy"),
                }
                for sheet in sheets
            ]
        }
        footer_rows = sheets[0].get("footerRows") if sheets else saved_payload.get("footerRows")
        inspected_by = str((sheets[0].get("inspectedBy") if sheets else saved_payload.get("inspectedBy")) or "").strip() or None
        checked_by = str((sheets[0].get("checkedBy") if sheets else saved_payload.get("checkedBy")) or "").strip() or None
    else:
        row_remarks = [{"index": i, "remarks": str(r.get("remarks") or "")} for i, r in enumerate(rows)]
        footer_rows = saved_payload.get("footerRows")
        inspected_by = str(saved_payload.get("inspectedBy") or "").strip() or None
        checked_by = str(saved_payload.get("checkedBy") or "").strip() or None
    username = (saved_by_username or saved_payload.get("savedByUsername") or "").strip() or None

    if row is None:
        row = InspectionReportSave(
            part_number=part_number,
            sales_order_id=sales_order_id,
            op_no=op_no,
            quantity_no=quantity_no,
            consolidated=consolidated,
        )
        db.add(row)

    row.row_remarks = row_remarks
    row.footer_rows = footer_rows if footer_rows else None
    row.inspected_by = inspected_by
    row.checked_by = checked_by
    row.saved_by_username = username
    db.commit()
    db.refresh(row)
    return saved_edits_to_dict(row)


def merge_saved_edits_into_payload(base: Dict[str, Any], saved: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    saved_sheets = saved.get("sheets") or []
    if saved_sheets and merged.get("sheets"):
        base_sheets = list(merged.get("sheets") or [])
        for i, saved_sheet in enumerate(saved_sheets):
            if i >= len(base_sheets):
                break
            sheet = dict(base_sheets[i])
            saved_rows = saved_sheet.get("rows") or []
            sheet_rows = list(sheet.get("rows") or [])
            for j, saved_row in enumerate(saved_rows):
                if j >= len(sheet_rows):
                    break
                remarks = saved_row.get("remarks")
                if remarks is not None:
                    sheet_rows[j] = {**sheet_rows[j], "remarks": remarks}
            sheet["rows"] = sheet_rows
            if saved_sheet.get("footerRows"):
                sheet["footerRows"] = saved_sheet["footerRows"]
            if saved_sheet.get("inspectedBy") is not None:
                sheet["inspectedBy"] = saved_sheet.get("inspectedBy") or ""
            if saved_sheet.get("checkedBy") is not None:
                sheet["checkedBy"] = saved_sheet.get("checkedBy") or ""
            base_sheets[i] = sheet
        merged["sheets"] = base_sheets
        merged["rows"] = [row for sheet in base_sheets for row in (sheet.get("rows") or [])]
        if saved.get("footerRows"):
            merged["footerRows"] = saved["footerRows"]
        if saved.get("inspectedBy") is not None:
            merged["inspectedBy"] = saved.get("inspectedBy") or ""
        if saved.get("checkedBy") is not None:
            merged["checkedBy"] = saved.get("checkedBy") or ""
        if saved.get("savedAt"):
            merged["savedAt"] = saved["savedAt"]
        return merged

    saved_rows = saved.get("rows") or []
    if saved_rows:
        base_rows = list(merged.get("rows") or [])
        for i, saved_row in enumerate(saved_rows):
            if i >= len(base_rows):
                break
            remarks = saved_row.get("remarks")
            if remarks is not None:
                base_rows[i] = {**base_rows[i], "remarks": remarks}
        merged["rows"] = base_rows
        if merged.get("sheets"):
            offset = 0
            updated_sheets = []
            for sheet in merged["sheets"]:
                sheet_rows = list(sheet.get("rows") or [])
                for j in range(len(sheet_rows)):
                    flat_idx = offset + j
                    if flat_idx < len(saved_rows):
                        remarks = saved_rows[flat_idx].get("remarks")
                        if remarks is not None:
                            sheet_rows[j] = {**sheet_rows[j], "remarks": remarks}
                offset += len(sheet_rows)
                updated_sheets.append({**sheet, "rows": sheet_rows})
            merged["sheets"] = updated_sheets
    if saved.get("footerRows"):
        merged["footerRows"] = saved["footerRows"]
    if saved.get("inspectedBy") is not None:
        merged["inspectedBy"] = saved.get("inspectedBy") or ""
    if saved.get("checkedBy") is not None:
        merged["checkedBy"] = saved.get("checkedBy") or ""
    if saved.get("savedAt"):
        merged["savedAt"] = saved["savedAt"]
    return merged
