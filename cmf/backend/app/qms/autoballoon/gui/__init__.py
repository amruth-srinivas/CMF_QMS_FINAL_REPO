"""
GUI Package
============
PySide6-based graphical interface for the OCR pipeline.

Public API:
  - OCRWindow      — Main application window
  - load_app_fonts — Font loading utility
"""

from .window import OCRWindow
from .fonts import load_app_fonts

__all__ = [
    "OCRWindow",
    "load_app_fonts",
]
