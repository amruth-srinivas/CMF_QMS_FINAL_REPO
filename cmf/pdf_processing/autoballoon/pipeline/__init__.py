"""
OCR Pipeline Package
=====================
Self-contained, modular OCR pipeline for engineering drawing analysis.

Can be imported independently (``from pipeline import OCREngine``) and used
as a headless API without the GUI.

Public API
----------
  - OCREngine        — High-level facade
  - ImageLoader      — Image / PDF loading
  - Preprocessor     — Image preprocessing (grayscale, thresholding)
  - OCRRunner        — PaddleOCR wrapper (inference + result parsing)
  - GDTDetector      — YOLO-based GD&T symbol detection (full + tiled)
  - GDTGrouper       — FCF and diameter grouping logic
  - DimParser        — Dimension text parsing (nominal, tolerances, type)
  - ResultFilter     — Confidence & ROI filtering, GD&T character promotion
  - OCRPipeline      — Full pipeline orchestrator
  - RegionDetector   — Structural region & ISO 5457 zone detection
  - RegionType       — Region classification enum
  - ZoneInfo         — Zone grid data class
"""

from .image_loader import ImageLoader
from .preprocessor import Preprocessor
from .ocr_runner import OCRRunner
from .gdt_detector import GDTDetector
from .gdt_grouper import GDTGrouper
from .dim_parser import DimParser
from .result_filter import ResultFilter
from .pipeline import OCRPipeline
from .region_detector import RegionDetector, RegionType, ZoneInfo
from .engine import OCREngine

__all__ = [
    "OCREngine",
    "ImageLoader",
    "Preprocessor",
    "OCRRunner",
    "GDTDetector",
    "GDTGrouper",
    "DimParser",
    "ResultFilter",
    "OCRPipeline",
    "RegionDetector",
    "RegionType",
    "ZoneInfo",
]
