"""
Hybrid region text extraction: PaddleOCR (autoballoon pipeline) first, PyMuPDF vector text as fallback.
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def has_meaningful_text(results: Optional[List[Dict]]) -> bool:
    if not results:
        return False
    return any((item.get("text") or "").strip() for item in results)


def extract_text_from_region_hybrid(
    pdf_path: str,
    page_number: int,
    region: Dict[str, float],
    *,
    scale_factor: float = 2.0,
    check_overlaps: bool = False,
    existing_boxes: Optional[List] = None,
    iou_threshold: float = 0.3,
    rotation_angles: Optional[List[int]] = None,
    confidence_threshold: float = 0.3,
    get_ocr_extractor: Callable[[], Optional[object]],
    pymupdf_extractor,
) -> List[Dict]:
    """
    Try backend PaddleOCR on the region; if it fails or returns no text, use PyMuPDF.
    """
    results: List[Dict] = []
    ocr_extractor = get_ocr_extractor()
    if ocr_extractor is not None:
        try:
            if check_overlaps and existing_boxes:
                results = ocr_extractor.extract_text_with_overlap_check(
                    pdf_path=pdf_path,
                    page_number=page_number,
                    region=region,
                    existing_boxes=existing_boxes,
                    iou_threshold=iou_threshold,
                    scale_factor=scale_factor,
                    confidence_threshold=confidence_threshold,
                    rotation_angles=rotation_angles,
                )
            else:
                results = ocr_extractor.extract_text_from_region(
                    pdf_path=pdf_path,
                    page_number=page_number,
                    region=region,
                    scale_factor=scale_factor,
                    confidence_threshold=confidence_threshold,
                    rotation_angles=rotation_angles,
                )
        except Exception as exc:
            logger.warning("OCR extraction error, will try PyMuPDF: %s", exc, exc_info=True)
            results = []

        if has_meaningful_text(results):
            logger.info("Using PaddleOCR results (%s detection(s))", len(results))
            return results
        logger.info("PaddleOCR returned no text; falling back to PyMuPDF")

    if not pymupdf_extractor:
        return results

    if check_overlaps and existing_boxes:
        return pymupdf_extractor.extract_text_with_overlap_check(
            pdf_path=pdf_path,
            page_number=page_number,
            region=region,
            existing_boxes=existing_boxes,
            iou_threshold=iou_threshold,
            scale_factor=scale_factor,
        )
    return pymupdf_extractor.extract_text_from_region(
        pdf_path=pdf_path,
        page_number=page_number,
        region=region,
        scale_factor=scale_factor,
    )
