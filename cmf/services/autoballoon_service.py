"""
Autoballoon pipeline service for CMF QMS (PaddleOCR + GD&T YOLO).

Replaces the former cmf/backend/app/services/autoballoon_service module.
"""

from __future__ import annotations

import base64
import logging
import threading

import cv2
import numpy as np

logger = logging.getLogger(__name__)

PIPELINE_DPI = 250.0
PDF_POINT_DPI = 72.0
_SCALE = PDF_POINT_DPI / PIPELINE_DPI

_engine_instance = None
_engine_lock = threading.Lock()
_engine_init_failed = False


def _get_engine():
    global _engine_instance, _engine_init_failed
    if _engine_init_failed:
        raise RuntimeError("Autoballoon OCREngine failed to initialize")
    if _engine_instance is not None:
        return _engine_instance
    with _engine_lock:
        if _engine_init_failed:
            raise RuntimeError("Autoballoon OCREngine failed to initialize")
        if _engine_instance is not None:
            return _engine_instance
        try:
            from pdf_processing.autoballoon.pipeline.engine import OCREngine

            logger.info("Initialising autoballoon OCREngine (loading models)…")
            _engine_instance = OCREngine()
            logger.info("Autoballoon OCREngine ready.")
            return _engine_instance
        except Exception as exc:
            _engine_init_failed = True
            logger.error("Autoballoon engine init failed: %s", exc, exc_info=True)
            raise


def is_pipeline_available() -> bool:
    try:
        _get_engine()
        return True
    except Exception:
        return False


def get_fitz_scale(file_path: str, raw_w: int) -> float:
    if not file_path.lower().endswith(".pdf"):
        import fitz

        try:
            doc = fitz.open(file_path)
            page = doc[0]
            fitz_w = page.rect.width
            doc.close()
            return fitz_w / float(raw_w) if raw_w else 1.0
        except Exception as exc:
            logger.warning("Failed to get Fitz scale for image %s: %s", file_path, exc)
            return 1.0
    return PDF_POINT_DPI / PIPELINE_DPI


def _scale_user_region_to_pixels(user_region: list) -> list:
    inv_scale = PIPELINE_DPI / PDF_POINT_DPI
    rx, ry, rw, rh = user_region
    return [
        int(rx * inv_scale),
        int(ry * inv_scale),
        int((rx + rw) * inv_scale),
        int((ry + rh) * inv_scale),
    ]


def run_pipeline(
    file_path: str,
    page_index: int = 0,
    user_region: list | None = None,
    max_ocr_dim: int = 5120,
    include_image: bool = True,
) -> dict:
    engine = _get_engine()
    scaled_region = None
    if user_region and len(user_region) == 4:
        scaled_region = _scale_user_region_to_pixels(user_region)
        logger.info("Scaled user region %s points -> %s pixels", user_region, scaled_region)

    result = engine.predict_with_regions(
        file_path,
        page_index=page_index,
        user_region=scaled_region,
        max_ocr_dim=max_ocr_dim,
    )

    parsed_dims = result.get("parsed_dimensions", [])
    original_img = result.get("original_image")

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

    return {
        "parsed_dimensions": parsed_dims,
        "annotated_image_b64": annotated_b64,
        "image_width": img_w,
        "image_height": img_h,
        "fitz_scale": get_fitz_scale(file_path, img_w),
        "gdt_detections": result.get("gdt_detections", []),
        "classified_detections": result.get("classified_detections", []),
    }


def map_pipeline_dimensions_to_api(parsed_dims: list, inv_scale: float) -> list:
    """Map pipeline parsed_dimensions (250 DPI px) to CMF API dimension dicts (PDF points)."""
    mapped = []
    for dim in parsed_dims or []:
        bbox = dim.get("bbox", [0, 0, 0, 0])
        parsed = dim.get("parsed", {})
        mapped.append(
            {
                "text": dim.get("text", ""),
                "nominal_value": str(parsed.get("nominal", "")),
                "upper_tolerance": str(parsed.get("max_tol", "")),
                "lower_tolerance": str(parsed.get("min_tol", "")),
                "dimension_type": parsed.get("type", "Dimension"),
                "bbox": [float(v) * inv_scale for v in bbox],
            }
        )
    return mapped


def map_classified_detections_to_text_api(classified: list, inv_scale: float) -> list:
    """Map pipeline classified_detections to extract-text style detections."""
    out = []
    for det in classified or []:
        bbox = det.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        scaled = [float(v) * inv_scale for v in bbox]
        box = [
            [scaled[0], scaled[1]],
            [scaled[2], scaled[1]],
            [scaled[2], scaled[3]],
            [scaled[0], scaled[3]],
        ]
        out.append(
            {
                "text": det.get("text", ""),
                "box": box,
                "confidence": float(det.get("score", det.get("confidence", 1.0))),
                "rotation": int(det.get("rotation", 0)),
            }
        )
    return out


def _draw_dimension_highlights(image: np.ndarray, parsed_dims: list, gdt_detections: list | None = None) -> np.ndarray:
    vis = image.copy()
    overlay = vis.copy()
    for dim in parsed_dims:
        bbox = dim.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        x1, y1, x2, y2 = map(int, bbox)
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (255, 140, 0), -1)
        cv2.rectangle(vis, (x1, y1), (x2, y2), (255, 80, 0), 2)
    if gdt_detections:
        for gdt in gdt_detections:
            bbox = gdt.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            x1, y1, x2, y2 = map(int, bbox)
            cv2.rectangle(overlay, (x1, y1), (x2, y2), (182, 89, 155), -1)
            cv2.rectangle(vis, (x1, y1), (x2, y2), (140, 60, 120), 2)
    cv2.addWeighted(overlay, 0.15, vis, 0.85, 0, vis)
    return vis
