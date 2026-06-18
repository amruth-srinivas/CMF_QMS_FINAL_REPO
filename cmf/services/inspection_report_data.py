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


def _report_instrument(m: Optional[StageInspection], ch: MasterBoc) -> str:
    used = str(m.used_inst or "").strip() if m else ""
    if used:
        return used
    planned = str((m.measured_instrument if m else None) or ch.measured_instrument or "").strip()
    if planned and planned.lower() != "default":
        return planned
    return ""


def _report_title(op_no: int) -> str:
    return "FINAL INSPECTION REPORT" if int(op_no) == 0 else "INSPECTION REPORT"


_MIN_ORPHAN_ROWS = 8


def _max_data_rows_per_page(include_footer: bool, *, single_header_row: bool = False) -> int:
    page_content = 268.0
    banner, meta, data_row, footer = 22.0, 30.0, 8.2, 58.0
    headers = 8.0 if single_header_row else 16.0
    fixed = banner + meta + headers + (footer if include_footer else 0.0)
    raw = (page_content - fixed) / data_row
    safety = 0.88 if include_footer else 0.92
    return max(1, int(raw * safety))


def _word_page_row_capacity(*, single_header_row: bool = False) -> tuple[int, int]:
    """Word rows are shorter than the HTML preview; allow more per page."""
    page_content = 275.0
    banner, meta, data_row, footer = 18.0, 22.0, 5.8, 46.0
    headers = 7.0 if single_header_row else 13.0
    fixed_no_footer = banner + meta + headers
    fixed_with_footer = fixed_no_footer + footer
    max_no_footer = max(1, int(((page_content - fixed_no_footer) / data_row) * 0.98))
    max_with_footer = max(1, int(((page_content - fixed_with_footer) / data_row) * 0.96))
    # Keep the footer page modest so we do not create tiny lead pages.
    max_with_footer = min(max_with_footer, 18)
    return max_no_footer, max_with_footer


def _paginate_report_rows(
    rows: List[Dict[str, Any]],
    *,
    single_header_row: bool = False,
    max_no_footer: Optional[int] = None,
    max_with_footer: Optional[int] = None,
) -> List[Dict[str, Any]]:
    if not rows:
        return [{"rows": [], "showFooter": True}]
    if max_no_footer is None or max_with_footer is None:
        computed_no = _max_data_rows_per_page(False, single_header_row=single_header_row)
        computed_with = _max_data_rows_per_page(True, single_header_row=single_header_row)
        max_no_footer = computed_no if max_no_footer is None else max_no_footer
        max_with_footer = computed_with if max_with_footer is None else max_with_footer
    pages: List[Dict[str, Any]] = []
    i = 0
    n = len(rows)
    while i < n:
        remaining = n - i
        if remaining <= max_with_footer:
            pages.append({"rows": rows[i:], "showFooter": True})
            break
        if remaining <= max_no_footer:
            lead = remaining - max_with_footer
            if lead > 0 and lead < _MIN_ORPHAN_ROWS:
                first = remaining // 2
                if first > 0:
                    pages.append({"rows": rows[i : i + first], "showFooter": False})
                    i += first
                pages.append({"rows": rows[i:], "showFooter": True})
                break
            if lead > 0:
                pages.append({"rows": rows[i : i + lead], "showFooter": False})
                i += lead
            pages.append({"rows": rows[i:], "showFooter": True})
            break
        pages.append({"rows": rows[i : i + max_no_footer], "showFooter": False})
        i += max_no_footer
    return pages


def _table_column_layout(is_consolidated: bool, max_samples: int) -> Dict[str, int]:
    compact = is_consolidated and max_samples >= 4
    inst_cols = 1 if compact else 2
    rem_cols = 2 if compact else 4
    total_cols = 1 + 2 + 1 + max_samples + inst_cols + rem_cols
    return {
        "totalCols": total_cols,
        "instCols": inst_cols,
        "remCols": rem_cols,
        "compact": compact,
    }


def rebuild_pages_for_word_export(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Re-pack rows for Word — tighter row height and balanced page splits."""
    is_consolidated = bool(payload.get("isConsolidated"))
    quantity_count = int(payload.get("quantityCount") or 0)
    max_no_footer, max_with_footer = _word_page_row_capacity(single_header_row=is_consolidated)

    row_groups: List[Dict[str, Any]] = []
    sheets = payload.get("sheets")
    if sheets and not is_consolidated:
        for sheet in sheets:
            row_groups.append(
                {
                    "qty": sheet.get("qty"),
                    "rows": list(sheet.get("rows") or []),
                    "totalQuantity": sheet.get("totalQuantity"),
                    "footerRows": sheet.get("footerRows"),
                    "inspectedBy": sheet.get("inspectedBy"),
                    "checkedBy": sheet.get("checkedBy"),
                }
            )
    else:
        rows = list(payload.get("rows") or [])
        if not rows:
            for page in payload.get("pages") or []:
                rows.extend(page.get("rows") or [])
        row_groups.append(
            {
                "rows": rows,
                "totalQuantity": payload.get("totalQuantity"),
            }
        )

    pages: List[Dict[str, Any]] = []
    for group in row_groups:
        group_rows = group.get("rows") or []
        chunks = _paginate_report_rows(
            group_rows,
            single_header_row=is_consolidated,
            max_no_footer=max_no_footer,
            max_with_footer=max_with_footer,
        )
        for chunk_index, chunk in enumerate(chunks):
            chunk_rows = chunk["rows"]
            if is_consolidated:
                max_samples = quantity_count or int(payload.get("maxSamples") or 3)
            else:
                max_samples = max([3] + [len(r.get("measurements") or []) for r in chunk_rows], default=3)
            layout = _table_column_layout(is_consolidated, max_samples)
            show_footer = bool(chunk["showFooter"])
            pages.append(
                {
                    "qty": group.get("qty"),
                    "rows": chunk_rows,
                    "showFooter": show_footer,
                    "pageInGroup": f"{chunk_index + 1} of {len(chunks)}",
                    "qtyGroupStart": chunk_index == 0,
                    "totalQuantity": str(
                        group.get("totalQuantity")
                        or group.get("qty")
                        or payload.get("totalQuantity")
                        or ""
                    ),
                    "maxSamples": max_samples,
                    "quantityCount": quantity_count if is_consolidated else None,
                    "isConsolidated": is_consolidated,
                    "totalCols": layout["totalCols"],
                    "footerRows": (group.get("footerRows") or payload.get("footerRows")) if show_footer else None,
                    "inspectedBy": (group.get("inspectedBy") or payload.get("inspectedBy")) if show_footer else None,
                    "checkedBy": (group.get("checkedBy") or payload.get("checkedBy")) if show_footer else None,
                }
            )

    total = len(pages)
    for index, page in enumerate(pages):
        page["sheet"] = f"{index + 1} of {total}"
        page["pageIndex"] = index
    return pages


def _avg_measurements(measurements: List[Any]) -> str:
    nums: List[float] = []
    for value in measurements or []:
        if value is None or value == "":
            continue
        try:
            n = float(value)
            if n == n:  # not NaN
                nums.append(n)
        except (TypeError, ValueError):
            continue
    if not nums:
        return ""
    avg = sum(nums) / len(nums)
    rounded = round(avg, 3)
    if abs(rounded - round(rounded)) < 1e-9:
        return f"{int(round(rounded))}"
    return f"{rounded:g}"


def _build_consolidated_rows(qty_groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not qty_groups:
        return []
    first_rows = qty_groups[0].get("rows") or []
    consolidated: List[Dict[str, Any]] = []
    for idx, first in enumerate(first_rows):
        qty_averages = []
        for group in qty_groups:
            group_rows = group.get("rows") or []
            row = group_rows[idx] if idx < len(group_rows) else {}
            qty_averages.append(_avg_measurements(row.get("measurements")))
        consolidated.append(
            {
                "sno": first.get("sno"),
                "specified": first.get("specified"),
                "zone": first.get("zone"),
                "qtyAverages": qty_averages,
                "instrument": first.get("instrument"),
                "remarks": first.get("remarks", ""),
            }
        )
    return consolidated


def _build_page_list(
    row_groups: List[Dict[str, Any]],
    *,
    is_consolidated: bool = False,
    quantity_count: int = 0,
) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    for group in row_groups:
        group_rows = group.get("rows") or []
        chunks = _paginate_report_rows(group_rows, single_header_row=is_consolidated)
        for chunk_index, chunk in enumerate(chunks):
            if is_consolidated:
                max_samples = quantity_count
            else:
                max_samples = max([3] + [len(r.get("measurements") or []) for r in chunk["rows"]])
            layout = _table_column_layout(is_consolidated, max_samples)
            pages.append(
                {
                    "qty": group.get("qty"),
                    "rows": chunk["rows"],
                    "showFooter": chunk["showFooter"],
                    "pageInGroup": f"{chunk_index + 1} of {len(chunks)}",
                    "qtyGroupStart": chunk_index == 0,
                    "totalQuantity": str(group.get("qty") or group.get("totalQuantity") or ""),
                    "maxSamples": max_samples,
                    "quantityCount": quantity_count if is_consolidated else None,
                    "isConsolidated": is_consolidated,
                    "totalCols": layout["totalCols"],
                }
            )
    total = len(pages)
    for index, page in enumerate(pages):
        page["sheet"] = f"{index + 1} of {total}"
        page["pageIndex"] = index
    return pages


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

    qty_groups: List[Dict[str, Any]] = []
    report_rows: List[Dict[str, Any]] = []
    if consolidated:
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
                        "instrument": _report_instrument(m, ch),
                        "remarks": _stage_remarks(m),
                    }
                )
            qty_groups.append({"qty": qty, "rows": qty_rows, "totalQuantity": str(qty)})
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
                    "instrument": _report_instrument(m, ch),
                    "remarks": _stage_remarks(m),
                }
            )

    now = datetime.datetime.now()
    assembly = part.assembly.assembly_name if part.assembly is not None else "Main"
    part_qty = max(1, int(part.qty or 1))

    if consolidated:
        report_rows = _build_consolidated_rows(qty_groups)
        total_quantity = f"All (1–{part_qty})" if part_qty > 1 else "1"
        pages = _build_page_list(
            [{"rows": report_rows, "totalQuantity": total_quantity}],
            is_consolidated=True,
            quantity_count=part_qty,
        )
        max_samples = part_qty
    else:
        total_quantity = str(quantity_no)
        pages = _build_page_list([{"qty": quantity_no, "rows": report_rows, "totalQuantity": str(quantity_no)}])
        max_samples = max([3] + [len(r.get("measurements") or []) for r in report_rows])

    layout = _table_column_layout(consolidated, max_samples)
    sheet_label = pages[0]["sheet"] if pages else "1 of 1"

    result: Dict[str, Any] = {
        "reportNo": f"RPT-{sales_order_id}-{op_no}",
        "reportTitle": _report_title(op_no),
        "isFinalInspection": int(op_no) == 0,
        "componentTitle": part.part_name or "",
        "date": f"{now.month}/{now.day}/{now.year}",
        "projectNo": str(order.sale_order_number or sales_order_id),
        "drgNo": part.part_number,
        "sheet": sheet_label,
        "projectName": product.product_name if product else "",
        "totalQuantity": total_quantity,
        "assembly": assembly,
        "rows": report_rows,
        "pages": pages,
        "maxSamples": max_samples,
        "totalCols": layout["totalCols"],
        "isConsolidated": consolidated,
    }
    if consolidated:
        result["quantityCount"] = part_qty
        result["sheets"] = qty_groups
    return result
