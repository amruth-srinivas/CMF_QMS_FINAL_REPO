"""
Autoballoon OCR / GD&T pipeline (relocated from cmf/backend).

Models live in pdf_processing/autoballoon/models/.
"""

from .pipeline.engine import OCREngine

__all__ = ["OCREngine"]
