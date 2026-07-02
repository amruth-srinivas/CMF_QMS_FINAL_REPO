"""
OCR Engine — Thin Facade
=========================
Backward-compatible facade over the modular pipeline.
"""

import os
import cv2
import numpy as np

from .dim_parser   import DimParser
from .image_loader import ImageLoader
from .preprocessor import Preprocessor
from .ocr_runner   import OCRRunner
from .gdt_detector import GDTDetector
from .gdt_grouper  import GDTGrouper
from .result_filter import ResultFilter
from .pipeline     import OCRPipeline
from .region_detector import RegionDetector, RegionType, ZoneInfo


class OCREngine:
    """Streamlined OCR Engine for Engineering Drawings (facade)."""

    def __init__(
        self,
        lang: str   = "en",
        det_thresh: float = 0.5,
        box_thresh: float = 0.5,
        conf_thresh: float = 0.85,
        enable_mkldnn: bool = False,
        cpu_threads: int  = None,
        gdt_conf_thresh: float = 0.70,  # lowered default (was 0.75)
    ):
        self.conf_thresh     = conf_thresh
        self.gdt_conf_thresh = gdt_conf_thresh

        # Feature flags
        self.use_tiled_gdt = True

        base_dir   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        models_dir = os.path.join(base_dir, "models")

        self._image_loader = ImageLoader()
        self._preprocessor = Preprocessor()
        self._ocr_runner   = OCRRunner(
            lang=lang,
            det_thresh=det_thresh,
            box_thresh=box_thresh,
            enable_mkldnn=enable_mkldnn,
            cpu_threads=cpu_threads,
            models_dir=models_dir,
        )

        gdt_model_path  = os.path.join(models_dir, "gdt_model_2.pt")
        self._gdt_detector = GDTDetector(gdt_model_path, conf_thresh=self.gdt_conf_thresh)
        self._gdt_grouper  = GDTGrouper()
        self._result_filter = ResultFilter()
        self.region_detector = RegionDetector()

        self._pipeline = OCRPipeline(
            image_loader    = self._image_loader,
            preprocessor    = self._preprocessor,
            ocr_runner      = self._ocr_runner,
            gdt_detector    = self._gdt_detector,
            gdt_grouper     = self._gdt_grouper,
            region_detector = self.region_detector,
            conf_thresh     = self.conf_thresh,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def preprocess_image(self, img, binary: bool = False):
        return self._preprocessor.preprocess(img, binary=binary)

    def load_pdf_page(self, pdf_path: str, page_index: int = 0, dpi: int = 250):
        return self._image_loader.load_pdf_page(pdf_path, page_index, dpi)

    def get_pdf_page_count(self, pdf_path: str) -> int:
        return self._image_loader.get_pdf_page_count(pdf_path)

    def predict(self, image_input, page_index: int = 0):
        original_img   = self._image_loader.load(image_input, page_index)
        processed_img  = self._preprocessor.preprocess(original_img)
        raw_result     = self._ocr_runner.run(processed_img)
        return raw_result, original_img

    def predict_with_regions(
        self,
        image_input,
        page_index: int = 0,
        max_ocr_dim: int = 5120,
        user_region: list = None,
        cached_roi_boundary: dict = None,
        cached_zone_info = None,
        cached_regions: list = None,
    ):
        # Sync thresholds before run
        self._pipeline.conf_thresh         = self.conf_thresh
        self._gdt_detector.conf_thresh     = self.gdt_conf_thresh
        return self._pipeline.run(
            image_input,
            page_index    = page_index,
            max_ocr_dim   = max_ocr_dim,
            use_tiled_gdt = self.use_tiled_gdt,
            user_region   = user_region,
            cached_roi_boundary = cached_roi_boundary,
            cached_zone_info    = cached_zone_info,
            cached_regions      = cached_regions,
        )

    def filter_results_by_confidence(self, ocr_results: list) -> list:
        return ResultFilter.filter_by_confidence(ocr_results, self.conf_thresh)

    @staticmethod
    def parse_results(result) -> list:
        return OCRRunner.parse_results(result)

    def _group_feature_control_frames(self, ocr_detections, gdt_detections, max_dist_ratio=6.0):
        return self._gdt_grouper.group_feature_control_frames(
            ocr_detections, gdt_detections, max_dist_ratio
        )

    def _group_diameter_symbols(self, ocr_detections, diameter_detections, max_dist_ratio=3.0):
        return self._gdt_grouper.group_diameter_symbols(
            ocr_detections, diameter_detections, max_dist_ratio
        )

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------

    def draw_results(self, image, ocr_results, gdt_results=None):
        vis_img = image.copy()
        for box, (text, score) in ocr_results:
            pts   = np.array(box, dtype=np.int32).reshape(-1, 2)
            x_min, y_min = pts.min(axis=0)
            x_max, y_max = pts.max(axis=0)
            cv2.rectangle(vis_img, (x_min, y_min), (x_max, y_max), (0, 0, 255), 2)
            label = f"{text} ({score:.2f})"
            (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(vis_img, (x_min, y_min - lh - 10),
                          (x_min + lw, y_min), (0, 0, 255), cv2.FILLED)
            cv2.putText(vis_img, label, (x_min, y_min - 7),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        if gdt_results:
            for gdt in gdt_results:
                x1, y1, x2, y2 = map(int, gdt["bbox"])
                cv2.rectangle(vis_img, (x1, y1), (x2, y2), (182, 89, 155), 2)
                label = f"GDT: {gdt['class']} ({gdt['score']:.2f})"
                (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
                cv2.rectangle(vis_img, (x1, y1 - lh - 6),
                              (x1 + lw, y1), (182, 89, 155), cv2.FILLED)
                cv2.putText(vis_img, label, (x1, y1 - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        return vis_img