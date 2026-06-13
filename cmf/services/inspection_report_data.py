"""Build inspection report payload shared by preview API and DOCX export."""
from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from DB.models.oms import Order, Part, Product
from DB.models.quality import MasterBoc, StageInspection


def _master_boc_id_from_stage_bbox(bbox: str) -> Optional[int]:
    if not bbox or not str(bbox).strip():
        return None
    try:
        mid = json.loads(bbox).get("master_boc_id")
        return int(mid) if mid is not None else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _fmt_tol(value) -> str:
    if value is None:
        return "0"
    try:
        n = float(value)
        if abs(n) < 1e-12:
            return "0"
        if n > 0:
            return f"+{n:g}"
        return f"{n:g}"
    except (TypeError, ValueError):
        return str(value)


def _stage_row_for_master(stage_rows: List[StageInspection], master_id: int) -> Optional[StageInspection]:
    for row in stage_rows:
        if _master_boc_id_from_stage_bbox(row.bbox) == master_id:
            return row
    return None


def _stage_remarks(row: Optional[StageInspection]) -> str:
    """StageInspection has no remarks column; keep empty unless the model gains one."""
    if not row:
        return ""
    return str(getattr(row, "remarks", None) or "")


def build_inspection_report_payload(
    db: Session,
    *,
    part_number: str,
    sales_order_id: int,
    op_no: int,
    quantity_no: int = 1,
    consolidated: bool = False,
    qty_max: Optional[int] = None,
) -> Dict[str, Any]:
    part = (
        db.query(Part)
        .options(joinedload(Part.assembly))
        .filter(Part.part_number == part_number)
        .first()
    )
    if not part:
        raise ValueError("Part not found")

    order = db.query(Order).filter(Order.id == sales_order_id).first()
    if not order:
        raise ValueError("Order not found")

    product = db.query(Product).filter(Product.id == order.product_id).first()

    masters = (
        db.query(MasterBoc)
        .filter(
            MasterBoc.part_id == part_number,
            MasterBoc.sales_order_id == sales_order_id,
            MasterBoc.op_no == op_no,
        )
        .order_by(MasterBoc.id.asc())
        .all()
    )

    if qty_max is None:
        qty_max = max(1, int(part.qty or 1))

    def fetch_stage(qty: int) -> List[StageInspection]:
        return (
            db.query(StageInspection)
            .filter(
                StageInspection.part_id == part.id,
                StageInspection.sale_order_id == sales_order_id,
                StageInspection.op_no == op_no,
                StageInspection.quantity_no == qty,
            )
            .all()
        )

    sheets: List[Dict[str, Any]] = []
    report_rows: List[Dict[str, Any]] = []
    if consolidated:
        total_sheets = qty_max
        for qty in range(1, qty_max + 1):
            stage_rows = fetch_stage(qty)
            qty_rows: List[Dict[str, Any]] = []
            for idx, ch in enumerate(masters):
                m = _stage_row_for_master(stage_rows, ch.id)
                row_nominal = m.nominal_value if m and m.nominal_value is not None else ch.nominal
                row_upper = m.uppertol if m and m.uppertol is not None else ch.uppertol
                row_lower = m.lowertol if m and m.lowertol is not None else ch.lowertol
                qty_rows.append(
                    {
                        "sno": idx + 1,
                        "specified": (
                            f"{ch.dimension_type or 'Dim'}: {row_nominal} "
                            f"({_fmt_tol(row_upper)}/{_fmt_tol(row_lower)})"
                        ),
                        "zone": ch.zone or "",
                        "measurements": list(m.measurements or []) if m else [],
                        "instrument": (m.measured_instrument if m else None) or ch.measured_instrument or "default",
                        "remarks": _stage_remarks(m),
                    }
                )
            sheet_max_samples = max([3] + [len(r.get("measurements") or []) for r in qty_rows])
            sheets.append(
                {
                    "qty": qty,
                    "rows": qty_rows,
                    "sheet": f"{qty} of {total_sheets}",
                    "totalQuantity": str(qty),
                    "maxSamples": sheet_max_samples,
                    "totalCols": 10 + sheet_max_samples,
                }
            )
            report_rows.extend(qty_rows)
    else:
        stage_rows = fetch_stage(quantity_no)
        for idx, ch in enumerate(masters):
            m = _stage_row_for_master(stage_rows, ch.id)
            row_nominal = m.nominal_value if m and m.nominal_value is not None else ch.nominal
            row_upper = m.uppertol if m and m.uppertol is not None else ch.uppertol
            row_lower = m.lowertol if m and m.lowertol is not None else ch.lowertol
            report_rows.append(
                {
                    "sno": idx + 1,
                    "specified": (
                        f"{ch.dimension_type or 'Dim'}: {row_nominal} "
                        f"({_fmt_tol(row_upper)}/{_fmt_tol(row_lower)})"
                    ),
                    "zone": ch.zone or "",
                    "measurements": list(m.measurements or []) if m else [],
                    "instrument": (m.measured_instrument if m else None) or ch.measured_instrument or "default",
                    "remarks": _stage_remarks(m),
                }
            )

    max_samples = max([3] + [len(r.get("measurements") or []) for r in report_rows])
    now = datetime.datetime.now()
    assembly = part.assembly.assembly_name if part.assembly is not None else "Main"
    part_qty = max(1, int(part.qty or 1))
    if consolidated:
        total_quantity = f"All (1–{part_qty})" if part_qty > 1 else "1"
        sheet_label = f"1 of {part_qty}" if part_qty > 1 else "1 of 1"
    else:
        total_quantity = str(quantity_no)
        sheet_label = "1 of 1"

    result: Dict[str, Any] = {
        "reportNo": f"RPT-{sales_order_id}-{op_no}",
        "componentTitle": part.part_name or "",
        "date": f"{now.month}/{now.day}/{now.year}",
        "projectNo": str(order.sale_order_number or sales_order_id),
        "drgNo": part.part_number,
        "sheet": sheet_label,
        "projectName": product.product_name if product else "",
        "totalQuantity": total_quantity,
        "assembly": assembly,
        "rows": report_rows,
        "maxSamples": max_samples,
        "totalCols": 10 + max_samples,
        "isConsolidated": consolidated,
    }
    if consolidated:
        result["sheets"] = sheets
    return result
