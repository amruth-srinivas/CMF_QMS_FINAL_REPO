"""
Region text extraction using the PaddleOCR autoballoon pipeline (pdf_processing/autoballoon).
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

# Must be set before paddle is imported by OCRRunner.
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_mkldnn", "0")

import cv2
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_OCR_DPI = 250
DEFAULT_CONFIDENCE = 0.3

_runner = None
_preprocessor = None
_image_loader = None
_init_lock = __import__("threading").Lock()
_init_failed = False


def _ensure_pipeline():
    global _runner, _preprocessor, _image_loader, _init_failed
    if _init_failed:
        raise RuntimeError("PaddleOCR pipeline failed to initialize earlier")
    if _runner is not None:
        return _runner, _preprocessor, _image_loader
    with _init_lock:
        if _init_failed:
            raise RuntimeError("PaddleOCR pipeline failed to initialize earlier")
        if _runner is not None:
            return _runner, _preprocessor, _image_loader
        try:
            from pdf_processing.autoballoon.pipeline.image_loader import ImageLoader
            from pdf_processing.autoballoon.pipeline.ocr_runner import OCRRunner
            from pdf_processing.autoballoon.pipeline.preprocessor import Preprocessor

            logger.info("Initializing PaddleOCR pipeline …")
            _image_loader = ImageLoader()
            _preprocessor = Preprocessor()
            _runner = OCRRunner(enable_mkldnn=False)
            logger.info("PaddleOCR pipeline ready.")
            return _runner, _preprocessor, _image_loader
        except Exception as exc:
            _init_failed = True
            logger.error("Failed to initialize PaddleOCR: %s", exc, exc_info=True)
            raise


def is_backend_ocr_available() -> bool:
    try:
        _ensure_pipeline()
        return True
    except Exception:
        return False


class TextExtractor:
    """PaddleOCR region extractor compatible with pdf_annotation router expectations."""

    def __init__(self, dpi: int = DEFAULT_OCR_DPI, confidence_threshold: float = DEFAULT_CONFIDENCE):
        self.dpi = dpi
        self.confidence_threshold = confidence_threshold
        _ensure_pipeline()

    def extract_text_from_region(
        self,
        pdf_path: str,
        page_number: int,
        region: Dict[str, float],
        scale_factor: float = 2.0,
        confidence_threshold: Optional[float] = None,
        rotation_angles: Optional[List[int]] = None,
    ) -> List[Dict]:
        del rotation_angles
        conf = confidence_threshold if confidence_threshold is not None else self.confidence_threshold
        try:
            runner, preprocessor, image_loader = _ensure_pipeline()
            full_image = image_loader.load_pdf_page(str(pdf_path), page_number, dpi=self.dpi)
            if full_image is None:
                logger.error("Failed to render PDF page for OCR")
                return []

            img_h, img_w = full_image.shape[:2]
            x0, y0, x1, y1 = _region_to_pixels(region, scale_factor, self.dpi, img_w, img_h)
            if x1 <= x0 or y1 <= y0:
                logger.warning("OCR region has no area after clamp")
                return []

            crop = full_image[y0:y1, x0:x1]
            if crop.size == 0:
                return []

            crop, upscale = _maybe_upscale_crop(crop)
            processed = preprocessor.preprocess(crop, binary=False, clahe=True, denoise=False)
            raw = runner.run(processed)
            detections = runner.parse_results(raw)

            out: List[Dict] = []
            for item in detections:
                if not item or len(item) < 2:
                    continue
                box, text_info = item[0], item[1]
                if not text_info:
                    continue
                text = str(text_info[0]).strip()
                score = float(text_info[1]) if len(text_info) > 1 else 0.0
                angle = int(text_info[2]) if len(text_info) > 2 else 0
                if not text or score < conf:
                    continue
                pdf_box = _quad_to_pdf_box(box, x0, y0, scale_factor, self.dpi, upscale)
                if not pdf_box:
                    continue
                out.append(
                    {
                        "text": text,
                        "box": pdf_box,
                        "confidence": score,
                        "rotation": angle,
                    }
                )

            logger.info("PaddleOCR extracted %s text detection(s) from region", len(out))
            return out
        except Exception as exc:
            logger.warning("PaddleOCR region extraction failed: %s", exc, exc_info=True)
            raise

    def extract_text_with_overlap_check(
        self,
        pdf_path: str,
        page_number: int,
        region: Dict[str, float],
        existing_boxes: List[List],
        iou_threshold: float = 0.3,
        scale_factor: float = 2.0,
        confidence_threshold: Optional[float] = None,
        rotation_angles: Optional[List[int]] = None,
    ) -> List[Dict]:
        all_results = self.extract_text_from_region(
            pdf_path,
            page_number,
            region,
            scale_factor=scale_factor,
            confidence_threshold=confidence_threshold,
            rotation_angles=rotation_angles,
        )
        if not existing_boxes:
            return all_results
        return [
            r
            for r in all_results
            if not any(_calculate_iou(r["box"], existing) > iou_threshold for existing in existing_boxes)
        ]


def _region_to_pixels(
    region: Dict[str, float],
    scale_factor: float,
    dpi: int,
    img_w: int,
    img_h: int,
) -> Tuple[int, int, int, int]:
    points_to_pixels = dpi / 72.0
    sf = scale_factor if scale_factor and scale_factor > 0 else 1.0
    x0 = (region["x"] / sf) * points_to_pixels
    y0 = (region["y"] / sf) * points_to_pixels
    x1 = ((region["x"] + region["width"]) / sf) * points_to_pixels
    y1 = ((region["y"] + region["height"]) / sf) * points_to_pixels
    pad = 5
    x0 = max(0, int(x0) - pad)
    y0 = max(0, int(y0) - pad)
    x1 = min(img_w, int(x1) + pad)
    y1 = min(img_h, int(y1) + pad)
    return x0, y0, x1, y1


def _maybe_upscale_crop(crop: np.ndarray) -> Tuple[np.ndarray, float]:
    min_side = min(crop.shape[0], crop.shape[1])
    if min_side >= 80:
        return crop, 1.0
    new_w = max(1, crop.shape[1] * 2)
    new_h = max(1, crop.shape[0] * 2)
    return cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_CUBIC), 2.0


def _quad_to_pdf_box(
    box,
    region_x: float,
    region_y: float,
    scale_factor: float,
    dpi: int,
    upscale: float = 1.0,
) -> Optional[List[List[float]]]:
    try:
        pts = np.asarray(box, dtype=float).reshape(-1, 2) / max(upscale, 1.0)
    except Exception:
        return None
    if pts.size < 4:
        return None
    xs = pts[:, 0] + region_x
    ys = pts[:, 1] + region_y
    x_min, x_max = float(xs.min()), float(xs.max())
    y_min, y_max = float(ys.min()), float(ys.max())
    pixels_to_points = 72.0 / dpi
    sf = scale_factor if scale_factor and scale_factor > 0 else 1.0

    def to_scene(px: float, py: float) -> List[float]:
        return [px * pixels_to_points * sf, py * pixels_to_points * sf]

    return [
        to_scene(x_min, y_min),
        to_scene(x_max, y_min),
        to_scene(x_max, y_max),
        to_scene(x_min, y_max),
    ]


def _calculate_iou(box1: List[List[float]], box2: List[List[float]]) -> float:
    try:
        x1_min = min(p[0] for p in box1)
        y1_min = min(p[1] for p in box1)
        x1_max = max(p[0] for p in box1)
        y1_max = max(p[1] for p in box1)
        x2_min = min(p[0] for p in box2)
        y2_min = min(p[1] for p in box2)
        x2_max = max(p[0] for p in box2)
        y2_max = max(p[1] for p in box2)
        inter_x_min = max(x1_min, x2_min)
        inter_y_min = max(y1_min, y2_min)
        inter_x_max = min(x1_max, x2_max)
        inter_y_max = min(y1_max, y2_max)
        if inter_x_max <= inter_x_min or inter_y_max <= inter_y_min:
            return 0.0
        inter_area = (inter_x_max - inter_x_min) * (inter_y_max - inter_y_min)
        area1 = (x1_max - x1_min) * (y1_max - y1_min)
        area2 = (x2_max - x2_min) * (y2_max - y2_min)
        union_area = area1 + area2 - inter_area
        return inter_area / union_area if union_area > 0 else 0.0
    except Exception:
        return 0.0
