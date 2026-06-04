import base64
from typing import Any, Optional

import cv2
import httpx
import numpy as np

from .gdt_grouper import GDTGrouper
from .image_loader import ImageLoader
from .region_detector import DetectedRegion, RegionType, ZoneInfo, ZoneInferenceSource
from .result_filter import ResultFilter


class APIEngineClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url.rstrip("/")
        self.conf_thresh = 0.85
        self.gdt_conf_thresh = 0.70
        self.use_tiled_gdt = True
        self._http = httpx.Client(timeout=600.0)
        self._image_loader = ImageLoader()
        self._gdt_grouper = GDTGrouper()

    def load_pdf_page(self, pdf_path: str, page_index: int = 0, dpi: int = 250):
        return self._image_loader.load_pdf_page(pdf_path, page_index, dpi)

    def get_pdf_page_count(self, pdf_path: str) -> int:
        return self._image_loader.get_pdf_page_count(pdf_path)

    def filter_results_by_confidence(self, ocr_results: list) -> list:
        return ResultFilter.filter_by_confidence(ocr_results, self.conf_thresh)

    def _group_feature_control_frames(self, ocr_detections, gdt_detections, max_dist_ratio=6.0):
        return self._gdt_grouper.group_feature_control_frames(ocr_detections, gdt_detections, max_dist_ratio)

    def _group_diameter_symbols(self, ocr_detections, diameter_detections, max_dist_ratio=6.0):
        return self._gdt_grouper.group_diameter_symbols(ocr_detections, diameter_detections, max_dist_ratio)

    def parse_results(self, result) -> list:
        return result

    def _decode_png_b64(self, b64_data: str, flag: int) -> Optional[np.ndarray]:
        if not b64_data:
            return None
        raw = base64.b64decode(b64_data)
        arr = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(arr, flag)

    def _deserialize_zone_info(self, zone_data: Any):
        if not zone_data:
            return None
        return ZoneInfo(
            col_labels=zone_data.get("col_labels", []),
            row_labels=zone_data.get("row_labels", []),
            col_boundaries=zone_data.get("col_boundaries", []),
            row_boundaries=zone_data.get("row_boundaries", []),
            roi_bbox=tuple(zone_data.get("roi_bbox", [0, 0, 0, 0])),
            zone_bbox=tuple(zone_data.get("zone_bbox", [0, 0, 0, 0])),
            col_source=ZoneInferenceSource(zone_data.get("col_source", "fallback")),
            row_source=ZoneInferenceSource(zone_data.get("row_source", "fallback")),
            paper_size=zone_data.get("paper_size"),
        )

    def _deserialize_regions(self, region_data: Any):
        if not region_data:
            return []
        regions = []
        for item in region_data:
            region_type_value = item.get("region_type", RegionType.UNKNOWN.value)
            if isinstance(region_type_value, str):
                region_type = RegionType(region_type_value)
            else:
                region_type = RegionType.UNKNOWN
            regions.append(
                DetectedRegion(
                    region_type=region_type,
                    bbox=tuple(item.get("bbox", [0, 0, 0, 0])),
                    confidence=float(item.get("confidence", 1.0)),
                    contour=None,
                    metadata=item.get("metadata", {}),
                )
            )
        return regions

    def predict_with_regions(
        self,
        image_input,
        page_index: int = 0,
        max_ocr_dim: int = 5120,
        user_region: list = None,
        cached_roi_boundary: dict = None,
        cached_zone_info=None,
        cached_regions: list = None,
    ):
        payload = {
            "image_path": str(image_input),
            "page_index": page_index,
            "max_ocr_dim": max_ocr_dim,
            "user_region": user_region,
            "use_tiled_gdt": self.use_tiled_gdt,
            "conf_thresh": self.conf_thresh,
            "gdt_conf_thresh": self.gdt_conf_thresh,
        }
        response = self._http.post(f"{self.base_url}/predict", json=payload)
        if response.status_code >= 400:
            detail = ""
            try:
                body = response.json()
                if isinstance(body, dict):
                    detail = str(body.get("detail", body))
                else:
                    detail = str(body)
            except Exception:
                detail = response.text
            raise RuntimeError(f"Backend {response.status_code}: {detail}")
        data = response.json()

        original_image = self._decode_png_b64(data.get("original_image_b64"), cv2.IMREAD_COLOR)
        roi_boundary = data.get("roi_boundary")
        if isinstance(roi_boundary, dict):
            roi_mask = self._decode_png_b64(roi_boundary.get("mask_b64"), cv2.IMREAD_GRAYSCALE)
            roi_boundary["mask"] = roi_mask
            roi_boundary.pop("mask_b64", None)

        data["original_image"] = original_image
        data["zone_info"] = self._deserialize_zone_info(data.get("zone_info"))
        data["regions"] = self._deserialize_regions(data.get("regions"))
        data.pop("original_image_b64", None)
        return data
