"""
Autoballoon Service — Wrapper around the OCR pipeline.

Provides a clean API for running the autoballoon pipeline and mapping
its results to Balloon database records.  Does NOT modify the underlying
pipeline — only orchestrates it.
"""

import logging
import base64
import threading
import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ── Lazy singleton for OCREngine ──────────────────────────────────────
_engine_instance = None
_engine_lock = threading.Lock()


def _get_engine():
    """Lazy-initialise and return the singleton OCREngine."""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:  # double-check
                logger.info("Initialising OCREngine (first call — loading models)…")
                from app.qms.autoballoon.pipeline import OCREngine
                _engine_instance = OCREngine()
                logger.info("OCREngine ready.")
    return _engine_instance


# ── DPI constants ─────────────────────────────────────────────────────
PIPELINE_DPI = 250.0
PDF_POINT_DPI = 72.0
_SCALE = PDF_POINT_DPI / PIPELINE_DPI        # Default for PDFs ≈ 0.288

def get_fitz_scale(file_path: str, raw_w: int) -> float:
    """
    Calculate the scale factor between Fitz 'points' (72 DPI) and raw pixels.
    For PDFs at 250 DPI interpolation, this is 72/250.
    For images, it depends on how Fitz interprets the image file.
    """
    if not file_path.lower().endswith(".pdf"):
        import fitz
        try:
            doc = fitz.open(file_path)
            page = doc[0]
            fitz_w = page.rect.width
            doc.close()
            # If fitz reports 1500pts for a 2000px image, scale is 1500/2000 = 0.75
            return fitz_w / float(raw_w)
        except Exception as e:
            logger.warning(f"Failed to get Fitz scale for image {file_path}: {e}")
            return 1.0 # Fallback
    return PDF_POINT_DPI / PIPELINE_DPI


def run_pipeline(
    file_path: str,
    page_index: int = 0,
    user_region: list | None = None,
    max_ocr_dim: int = 5120,
    include_image: bool = True,
) -> dict:
    """
    Run the full OCR pipeline on a PDF/image and return parsed results.

    Parameters
    ----------
    file_path : str
        Absolute path to the PDF or image file.
    page_index : int
        0-based page index (for multi-page PDFs).
    user_region : list | None
        Optional [x, y, w, h] or [x1, y1, x2, y2] region in PDF points (72 DPI).
    max_ocr_dim : int
        Maximum dimension (px) for OCR input scaling.
    include_image : bool
        Whether to generate and return an annotated image as Base64.
    """
    engine = _get_engine()

    # Scale user_region from PDF points (72 DPI) to pipeline pixels (250 DPI)
    scaled_region = None
    if user_region:
        inv_scale = PIPELINE_DPI / PDF_POINT_DPI  # ≈ 3.47
        if len(user_region) == 4:
            # Check if it is [x, y, w, h] (common from frontend) or [x1, y1, x2, y2]
            # InspectionPlanner usually sends bounding_box with x, y, width, height.
            # But the pipeline expects [x1, y1, x2, y2].
            rx, ry, rw, rh = user_region
            # Handle both formats: if rw and rh are large, it might be coordinates.
            # But usually it's x, y, w, h. Let's assume x, y, w, h and convert to x1, y1, x2, y2.
            # Actually, the pipeline.py check: ux1, uy1, ux2, uy2 = user_region
            x1 = int(rx * inv_scale)
            y1 = int(ry * inv_scale)
            x2 = int((rx + rw) * inv_scale)
            y2 = int((ry + rh) * inv_scale)
            scaled_region = [x1, y1, x2, y2]
            logger.info(f"Scaling user region: {user_region} points -> {scaled_region} pixels")

    result = engine.predict_with_regions(
        file_path,
        page_index=page_index,
        user_region=scaled_region,
        max_ocr_dim=max_ocr_dim
    )


    parsed_dims = result.get("parsed_dimensions", [])
    original_img = result.get("original_image")

    # Build annotated image with highlighted dimension bboxes
    annotated_b64 = None
    img_h, img_w = 0, 0
    if original_img is not None:
        img_h, img_w = original_img.shape[:2]
        if include_image:
            annotated_img = _draw_dimension_highlights(
                original_img, parsed_dims, result.get("gdt_detections", [])
            )
            _, buf = cv2.imencode(".png", annotated_img)
            annotated_b64 = "data:image/png;base64," + base64.b64encode(buf).decode()

    # Calculate dynamic scale for this file
    dynamic_scale = get_fitz_scale(file_path, img_w)

    return {
        "parsed_dimensions": parsed_dims,
        "annotated_image_b64": annotated_b64,
        "image_width": img_w,
        "image_height": img_h,
        "fitz_scale": dynamic_scale,
        "gdt_detections": result.get("gdt_detections", []),
        "classified_detections": result.get("classified_detections", []),
    }


def sort_balloons_spatially(balloons_list: list) -> list:
    """
    Sort a list of balloon dictionaries or objects spatially.
    Expects items to have 'zone' and 'bbox' (or 'x', 'y', 'width', 'height').
    """
    def sort_key(d):
        # Handle both dict and object
        zone = d.get("zone") if isinstance(d, dict) else (getattr(d, "zone", None))
        
        # Determine bbox: [x1, y1, x2, y2]
        if isinstance(d, dict):
            if "bbox" in d:
                bbox = d["bbox"]
            else:
                # Fallback to x, y, width, height format
                x = float(d.get("x") or 0)
                y = float(d.get("y") or 0)
                w = float(d.get("width") or 0)
                h = float(d.get("height") or 0)
                bbox = [x, y, x + w, y + h]
        else:
            x = float(getattr(d, "x") or 0)
            y = float(getattr(d, "y") or 0)
            w = float(getattr(d, "width") or 0)
            h = float(getattr(d, "height") or 0)
            bbox = [x, y, x + w, y + h]

        row_rank = 0
        col_rank = 0
        
        if zone and len(zone) >= 2:
            row_letter = zone[0]
            col_number = zone[1:]
            row_rank = -ord(row_letter.upper())
            try:
                col_rank = -int(col_number)
            except (ValueError, TypeError):
                col_rank = 0
        else:
            row_rank = 0 
            col_rank = 0

        # Micro-sort within the same cell or for items without zones
        y_bucket = round(bbox[1] / 30) * 30 
        return (row_rank, col_rank, y_bucket, bbox[0])

    return sorted(balloons_list, key=sort_key)


def resequence_balloon_ids(balloons: list) -> list:
    """
    Takes a list of balloon objects/dicts, sorts them spatially, 
    and updates their 'balloon_id' to be strings "1", "2", "3"...
    Returns the list of UPDATED items.
    """
    sorted_list = sort_balloons_spatially(balloons)
    for idx, b in enumerate(sorted_list, start=1):
        if isinstance(b, dict):
            b["balloon_id"] = str(idx)
        else:
            b.balloon_id = str(idx)
    return sorted_list


def map_to_balloons(
    parsed_dimensions: list,
    part_id: int,
    document_id: int | None,
    page: int,
    is_pdf: bool = True,
    dynamic_scale: float | None = None,
) -> list[dict]:
    """
    Convert pipeline parsed_dimensions into dicts matching the Balloon
    database columns.

    Coordinates are scaled from pixel space to the target coordinate system
    expected by the frontend (usually 72 DPI points).
    """
    # Use dynamic_scale if provided (e.g. from run_pipeline), otherwise fallback to defaults
    if dynamic_scale is not None:
        scale = dynamic_scale
    else:
        scale = _SCALE if is_pdf else 1.0
    
    # Sort parsed_dimensions spatially before mapping
    sorted_dims = sort_balloons_spatially(parsed_dimensions)

    balloons: list[dict] = []
    for idx, dim in enumerate(sorted_dims, start=1):
        bbox = dim.get("bbox", [0, 0, 0, 0])  # [x1, y1, x2, y2]
        x1, y1, x2, y2 = [float(v) for v in bbox]

        # Scale to PDF-point space
        x = x1 * scale
        y = y1 * scale
        w = (x2 - x1) * scale
        h = (y2 - y1) * scale

        parsed = dim.get("parsed", {})
        nominal_raw = parsed.get("nominal", "")
        dim_type = parsed.get("type", dim.get("source", "Dimension"))

        # Try to parse nominal as float for the DB column
        nominal_float = None
        try:
            nominal_float = float(str(nominal_raw).replace(",", ".").strip())
        except (ValueError, TypeError):
            pass

        # Tolerances
        utol = parsed.get("max_tol", "") or ""
        ltol = parsed.get("min_tol", "") or ""

        # Zone from pipeline (if available through classified_detections)
        zone = dim.get("zone", None)

        balloons.append({
            "part_id": part_id,
            "document_id": document_id,
            "balloon_id": str(idx),
            "x": round(x, 2),
            "y": round(y, 2),
            "width": round(w, 2),
            "height": round(h, 2),
            "page": page,
            "nominal": nominal_float,
            "utol": str(utol) if utol else None,
            "ltol": str(ltol) if ltol else None,
            "type": str(dim_type) if dim_type else None,
            "zone": str(zone) if zone else None,
        })

    return balloons


# ── Visualisation helpers ─────────────────────────────────────────────

def _draw_dimension_highlights(
    image: np.ndarray,
    parsed_dims: list,
    gdt_detections: list | None = None,
) -> np.ndarray:
    """
    Draw semi-transparent bounding boxes over detected dimensions and
    GD&T symbols on a copy of *image*.
    """
    vis = image.copy()
    overlay = vis.copy()

    # Dimension bboxes — blue
    for dim in parsed_dims:
        bbox = dim.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        x1, y1, x2, y2 = map(int, bbox)
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (255, 140, 0), -1)  # filled
        cv2.rectangle(vis, (x1, y1), (x2, y2), (255, 80, 0), 2)        # border

    # GD&T bboxes — purple
    if gdt_detections:
        for gdt in gdt_detections:
            bbox = gdt.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            x1, y1, x2, y2 = map(int, bbox)
            cv2.rectangle(overlay, (x1, y1), (x2, y2), (182, 89, 155), -1)
            cv2.rectangle(vis, (x1, y1), (x2, y2), (140, 60, 120), 2)

    # Blend
    alpha = 0.15
    cv2.addWeighted(overlay, alpha, vis, 1 - alpha, 0, vis)

    return vis
