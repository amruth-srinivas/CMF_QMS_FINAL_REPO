"""
OCR Runner
===========
Wraps PaddleOCR initialization, inference, and raw result parsing.

No functional changes vs v1; DPI parameter forwarded to image_loader separately.
"""

import os

# OneDNN + PIR on Windows/Paddle 3.x can raise NotImplementedError during predict().
# Disable before importing paddle/paddleocr (see backend note extraction).
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_mkldnn", "0")

import numpy as np
from paddleocr import PaddleOCR


class OCRRunner:
    """PaddleOCR wrapper for initialization, inference, and result parsing."""

    def __init__(
        self,
        lang: str       = "en",
        det_thresh: float = 0.5,
        box_thresh: float = 0.5,
        enable_mkldnn: bool = False,
        cpu_threads: int  = None,
        models_dir: str   = None,
    ):
        print("Initializing PaddleOCR Engine...")

        if models_dir is None:
            base_dir   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            models_dir = os.path.join(base_dir, "models")

        det_model_path = os.path.join(models_dir, "PP-OCRv5_mobile_det")
        rec_model_path = os.path.join(models_dir, "en_PP-OCRv5_mobile_rec")
        cls_model_path = os.path.join(models_dir, "PP-LCNet_x1_0_textline_ori")

        if cpu_threads is None:
            cpu_threads = max(1, (os.cpu_count() or 4) - 2)

        self.ocr = PaddleOCR(
            enable_mkldnn                   = enable_mkldnn,
            cpu_threads                     = cpu_threads,
            use_textline_orientation        = True,
            text_det_thresh                 = det_thresh,
            text_det_box_thresh             = box_thresh,
            use_doc_unwarping               = False,
            textline_orientation_model_dir  = cls_model_path,
            text_detection_model_dir        = det_model_path,
            text_recognition_model_dir      = rec_model_path,
            textline_orientation_model_name = "PP-LCNet_x1_0_textline_ori",
            text_detection_model_name       = "PP-OCRv5_mobile_det",
            text_recognition_model_name     = "en_PP-OCRv5_mobile_rec",
        )
        print("Engine Ready.")

    def run(self, image: np.ndarray):
        """Run OCR inference on a preprocessed image."""
        return self.ocr.predict(image)

    @staticmethod
    def parse_results(result) -> list:
        """Simplify the raw nested PaddleOCR output into a clean detection list."""
        ocr_results = []
        if not result:
            return ocr_results

        pages = result if isinstance(result, list) else [result]
        if not pages:
            return ocr_results

        first_page = pages[0]
        if not first_page:
            return ocr_results

        # PaddleX OCRResult dict-like object
        if (
            hasattr(first_page, "keys")
            and "dt_polys" in first_page
            and "rec_texts" in first_page
        ):
            for box, text, score in zip(
                first_page["dt_polys"],
                first_page["rec_texts"],
                first_page["rec_scores"],
            ):
                ocr_results.append([box, (text, score)])
            return ocr_results

        # Standard list format: [ [[box], (text, score)], ... ]
        if isinstance(first_page, list):
            for line in first_page:
                if isinstance(line, list) and len(line) >= 2:
                    box, (text, score) = line[0], line[1]
                    # Attempt to extract angle from result if cls=True was used
                    angle = 0
                    if len(line) > 2:
                        cls_info = line[2]
                        if isinstance(cls_info, (list, tuple)) and len(cls_info) > 0:
                            # Usually ('0', 0.99) or ('90', 0.99)
                            try:
                                angle = int(cls_info[0])
                            except (ValueError, TypeError):
                                angle = 0
                        elif isinstance(cls_info, (int, float)):
                            angle = cls_info
                    ocr_results.append([box, (text, score, angle)])

        return ocr_results
