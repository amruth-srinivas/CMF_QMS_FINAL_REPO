"""
Region Detector for Engineering Drawings
=========================================
Uses OpenCV edge detection and contour analysis to identify structured regions
(title blocks, tables, revision blocks, etc.) in engineering drawings.

This is a POST-PROCESSOR: it works on the original image alongside existing
OCR detections to classify each detection into its respective region.

Pipeline Position:
    Full OCR → Region Detection → Detection Classification → Output

Supports both landscape (A3/A2 horizontal) and portrait (A4/A3 vertical) drawings.

Zone Detection & Recovery Strategy
------------------------------------
Engineering drawings (ISO 5457 / ASME Y14.1) use a grid of zones around the margin:
  - Numbers (1–N) define column zones  (top/bottom margin, left→right or right→left)
  - Letters (A–Z) define row zones     (left/right margin, top→bottom)

Because OCR can miss individual zone markers (especially single letters in the side
margin), the zone grid is reconstructed through a three-tier inference system:

  Tier 1 — ISO Standard Lookup
      Match the drawing's inner-frame aspect ratio + detected count to a known
      paper size (A0–A4) and look up the canonical zone count.  Most authoritative.

      Standard zone counts (cols × rows):
          A4 portrait    :  4 ×  4
          A3 landscape   :  8 ×  4
          A3 portrait    :  4 ×  6
          A2 landscape   :  8 ×  6
          A2 portrait    :  6 ×  8
          A1 landscape   : 16 ×  6
          A1 portrait    :  6 × 16
          A0 landscape   : 16 × 12
          A0 portrait    : 12 × 16

  Tier 2 — Cross-axis Inference
      ISO 5457 §6 specifies zones ≈ 50 mm × 50 mm (square cells).  If one axis
      has a reliable detected count, the other is derived from:
          n_rows = round(zone_height / zone_width * n_cols)

  Tier 3 — Sequence Gap-filling
      If partial markers were detected (e.g. 3 of 4 letters), the natural
      alphabetic/numeric sequence is reconstructed by filling identified gaps.

Author: OCR Engine Pipeline
"""

import cv2
import numpy as np
import re
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, NamedTuple
from enum import Enum


# ===========================================================================
# Enums & data classes
# ===========================================================================

class RegionType(Enum):
    """Classification of detected regions in an engineering drawing."""
    DRAWING_AREA   = "drawing_area"
    TITLE_BLOCK    = "title_block"
    TABLE          = "table"
    REVISION_BLOCK = "revision_block"
    BORDER         = "border"
    ZONE_MARKER    = "zone_marker"
    UNKNOWN        = "unknown"


class DrawingOrientation(Enum):
    LANDSCAPE = "landscape"
    PORTRAIT  = "portrait"


class ZoneInferenceSource(Enum):
    """How the final zone count was determined (for diagnostics)."""
    OCR_DETECTED = "ocr_detected"   # All markers found by OCR
    OCR_PARTIAL  = "ocr_partial"    # Some markers detected, gaps filled
    ISO_STANDARD = "iso_standard"   # Derived from ISO 5457 lookup table
    CROSS_AXIS   = "cross_axis"     # Inferred from other axis + aspect ratio
    FALLBACK     = "fallback"       # Could not infer; used safe default


@dataclass
class ZoneInfo:
    """Zone grid information derived from margin markers."""
    col_labels:     List[str]                   # e.g. ['1','2','3','4']  left→right
    row_labels:     List[str]                   # e.g. ['A','B','C','D']  top→bottom
    col_boundaries: List[int]                   # x-coords, len = n_cols + 1
    row_boundaries: List[int]                   # y-coords, len = n_rows + 1
    roi_bbox:       Tuple[int, int, int, int]   # (x1,y1,x2,y2) inner frame
    zone_bbox:      Tuple[int, int, int, int]   # (x1,y1,x2,y2) zone extent (title-clipped)
    col_source:     ZoneInferenceSource = ZoneInferenceSource.OCR_DETECTED
    row_source:     ZoneInferenceSource = ZoneInferenceSource.OCR_DETECTED
    paper_size:     Optional[str]       = None  # e.g. 'A3' if matched

    def get_zone_label(self, x: int, y: int) -> Optional[str]:
        """Return zone label (e.g. 'B3') for a point, or None if outside grid."""
        col_label = row_label = None
        for i in range(len(self.col_boundaries) - 1):
            if self.col_boundaries[i] <= x < self.col_boundaries[i + 1]:
                if i < len(self.col_labels):
                    col_label = self.col_labels[i]
                break
        for i in range(len(self.row_boundaries) - 1):
            if self.row_boundaries[i] <= y < self.row_boundaries[i + 1]:
                if i < len(self.row_labels):
                    row_label = self.row_labels[i]
                break
        if col_label and row_label:
            return f"{row_label}{col_label}"
        return col_label or row_label


@dataclass
class DetectedRegion:
    """A detected structural region in the drawing."""
    region_type: RegionType
    bbox:        Tuple[int, int, int, int]
    confidence:  float                = 1.0
    contour:     Optional[np.ndarray] = None
    metadata:    Dict                 = field(default_factory=dict)

    @property
    def area(self):
        x1, y1, x2, y2 = self.bbox
        return (x2 - x1) * (y2 - y1)

    @property
    def width(self):
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self):
        return self.bbox[3] - self.bbox[1]

    @property
    def center(self):
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @property
    def aspect_ratio(self):
        if self.height == 0:
            return float('inf')
        return self.width / self.height

    def contains_point(self, x, y):
        x1, y1, x2, y2 = self.bbox
        return x1 <= x <= x2 and y1 <= y <= y2

    def contains_bbox(self, bbox, threshold=0.5):
        bx1, by1, bx2, by2 = bbox
        ix1 = max(self.bbox[0], bx1); iy1 = max(self.bbox[1], by1)
        ix2 = min(self.bbox[2], bx2); iy2 = min(self.bbox[3], by2)
        if ix1 >= ix2 or iy1 >= iy2:
            return False
        inter     = (ix2 - ix1) * (iy2 - iy1)
        test_area = max((bx2 - bx1) * (by2 - by1), 1)
        return (inter / test_area) >= threshold


# ===========================================================================
# ISO 5457 standard zone table
# ===========================================================================

class _PaperSpec(NamedTuple):
    name:        str    # 'A0'..'A4'
    orientation: str    # 'landscape' | 'portrait'
    frame_ratio: float  # width / height of inner frame
    n_cols:      int
    n_rows:      int


# ISO 5457 zone counts.  All A-series share the same w/h ratio (√2 ≈ 1.414),
# so we use the detected zone count on one axis to disambiguate size.
_ISO_PAPER_SPECS: List[_PaperSpec] = [
    _PaperSpec("A4", "portrait",   0.707,  4,  4),
    _PaperSpec("A3", "landscape",  1.414,  8,  4),
    _PaperSpec("A3", "portrait",   0.707,  4,  6),
    _PaperSpec("A2", "landscape",  1.414,  8,  6),
    _PaperSpec("A2", "portrait",   0.707,  6,  8),
    _PaperSpec("A1", "landscape",  1.414, 16,  6),
    _PaperSpec("A1", "portrait",   0.707,  6, 16),
    _PaperSpec("A0", "landscape",  1.414, 16, 12),
    _PaperSpec("A0", "portrait",   0.707, 12, 16),
]

_RATIO_TOLERANCE = 0.08  # ±8% aspect-ratio tolerance for paper matching


def _best_paper_spec_for_count(
    n_detected:  int,
    axis:        str,              # 'col' or 'row'
    orientation: DrawingOrientation,
) -> Optional[_PaperSpec]:
    """
    Return the unique ISO spec whose zone count on `axis` equals n_detected,
    for the given orientation.  Returns None if no unique match.
    """
    orient_str = orientation.value
    key        = 'n_cols' if axis == 'col' else 'n_rows'
    matches    = [s for s in _ISO_PAPER_SPECS
                  if s.orientation == orient_str and getattr(s, key) == n_detected]
    if len(matches) == 1:
        return matches[0]
    # Multiple matches: accept if the OTHER axis count also agrees unanimously
    if matches:
        other_key   = 'n_rows' if axis == 'col' else 'n_cols'
        other_vals  = {getattr(m, other_key) for m in matches}
        if len(other_vals) == 1:
            return matches[0]
    return None


def _best_paper_spec_fuzzy(
    n_cols_detected: int,
    n_rows_detected: int,
    orientation:     DrawingOrientation,
    max_axis_dev:    int = 2,
) -> Optional[_PaperSpec]:
    """
    Fuzzy combined ISO spec lookup using BOTH detected axis counts.

    When exact single-axis matching fails (e.g. OCR reads '6' as '9',
    giving 9 detected cols instead of 8), this function finds the ISO
    spec whose (n_cols, n_rows) is closest to the detected pair,
    provided each axis deviation is within `max_axis_dev`.

    Returns the best-matching spec, or None if no spec is close enough.
    """
    orient_str = orientation.value
    best: Optional[_PaperSpec] = None
    best_dev = float('inf')

    for spec in _ISO_PAPER_SPECS:
        if spec.orientation != orient_str:
            continue
        col_dev = abs(spec.n_cols - n_cols_detected)
        row_dev = abs(spec.n_rows - n_rows_detected)
        if col_dev > max_axis_dev or row_dev > max_axis_dev:
            continue
        total_dev = col_dev + row_dev
        if total_dev < best_dev:
            best_dev = total_dev
            best = spec

    return best


# ===========================================================================
# Sequence helpers
# ===========================================================================

def _detect_orientation(img_w: int, img_h: int) -> DrawingOrientation:
    return DrawingOrientation.LANDSCAPE if img_w >= img_h else DrawingOrientation.PORTRAIT


def _bbox_area(bbox: Tuple[int, int, int, int]) -> int:
    x1, y1, x2, y2 = bbox
    return max(0, x2 - x1) * max(0, y2 - y1)


def _fill_sequence_gaps(
    detected_labels: List[str],
    expected_count:  int,
    is_descending:   Optional[bool] = None,
) -> Tuple[List[str], ZoneInferenceSource]:
    """
    Given a partial set of zone labels and the expected total count,
    reconstruct the full sequence by filling gaps.

    Works for both ascending/descending alphabetic and numeric sequences.

    :param is_descending: Explicit direction.  If None, inferred from the
        relative positions of detected label values.
    Returns (full_label_list, inference_source).
    """
    if not detected_labels:
        return [], ZoneInferenceSource.FALLBACK

    all_alpha = all(c.isalpha() for c in detected_labels)
    all_digit = all(c.isdigit() for c in detected_labels)

    if not all_alpha and not all_digit:
        return detected_labels, ZoneInferenceSource.OCR_PARTIAL

    if all_digit:
        values = [int(v) for v in detected_labels]
    else:
        values = [ord(v.upper()) for v in detected_labels]

    # Resolve direction
    if is_descending is not None:
        descending = is_descending
    else:
        ascending_pairs = sum(1 for i in range(len(values) - 1) if values[i] < values[i + 1])
        descending = ascending_pairs < len(values) // 2

    step = -1 if descending else 1

    # ── Anchoring to standard start ───────────────────────────────────────
    # Engineering zones always start at 1 (cols) or A (rows).  When OCR misses
    # the first marker(s), naive min/max anchoring extrapolates in the wrong
    # direction.  Example: detected ['2','3','4'], expected 4 → without anchoring
    # we'd generate ['2','3','4','5'], but the correct sequence is ['1','2','3','4'].
    #
    # Rule: anchor to the standard start if the detected values are "close enough"
    # to that start (within a small gap that OCR could plausibly have missed),
    # or if there is only a single detection (direction is ambiguous).
    #
    # The tolerance (≤3 missed at the start, i.e. value ≤ 4 for digits or ≤ D for
    # letters) is generous enough to handle real-world OCR noise.
    if all_digit:
        if not descending:
            # Ascending: anchor to 1 if detected values are near the standard start
            natural_start = 1 if (min(values) <= 4 or len(values) == 1) else min(values)
        else:
            # Descending: anchor to expected_count (the highest label) if near it
            natural_start = (expected_count
                             if (max(values) >= expected_count - 2 or len(values) == 1)
                             else max(values))
    else:  # all_alpha
        A_val = ord('A')
        if not descending:
            # Ascending: anchor to 'A' if detected values are near A
            natural_start = A_val if (min(values) <= A_val + 3 or len(values) == 1) else min(values)
        else:
            # Descending: anchor to the last expected letter (e.g. 'D' for 4 rows)
            top_val = A_val + expected_count - 1
            natural_start = (top_val
                             if (max(values) >= top_val - 2 or len(values) == 1)
                             else max(values))

    if all_digit:
        full_labels = [str(natural_start + step * i) for i in range(expected_count)]
    else:
        # Guard against going outside A-Z
        full_labels = []
        for i in range(expected_count):
            char_code = natural_start + step * i
            full_labels.append(chr(char_code) if ord('A') <= char_code <= ord('Z') else '?')

    source = (ZoneInferenceSource.OCR_DETECTED
              if len(full_labels) == len(detected_labels)
              else ZoneInferenceSource.OCR_PARTIAL)
    return full_labels, source


def _synthesise_labels(axis: str, count: int, descending: bool = False) -> List[str]:
    """
    Synthesise a zone label sequence when no OCR markers were found.

    :param axis:       'col' (numbers) or 'row' (letters)
    :param count:      Number of zones
    :param descending: True if the sequence runs in reverse order
                       (e.g. portrait columns often go 4→3→2→1 left→right)
    """
    if axis == 'col':
        # Columns: digits. Ascending → 1,2,3,… / Descending → N,N-1,…,1
        if descending:
            return [str(count - i) for i in range(count)]
        return [str(i + 1) for i in range(count)]
    else:
        # Rows: letters. Ascending → A,B,C,… / Descending → D,C,B,A
        if descending:
            return [chr(ord('A') + count - 1 - i) for i in range(count)]
        return [chr(ord('A') + i) for i in range(count)]


# ===========================================================================
# Main class
# ===========================================================================

class RegionDetector:
    """
    Detects structural regions in engineering drawings using OpenCV edge detection
    and contour analysis, with ISO-standard zone inference to recover OCR misses.
    """

    def __init__(
        self,
        canny_low:  int   = 50,
        canny_high: int   = 150,
        morph_kernel_size: int   = 3,
        morph_iterations:  int   = 2,
        min_region_area_ratio:   float = 0.005,
        max_region_area_ratio:   float = 0.60,
        approx_epsilon_ratio:    float = 0.02,
        title_block_max_area_ratio: float = 0.30,
        title_block_min_area_ratio: float = 0.01,
        table_min_aspect_ratio:  float = 0.3,
        table_max_aspect_ratio:  float = 5.0,
        classification_overlap_threshold: float = 0.5,
        # Zone marker OCR confidence gate (reject low-conf single chars from tables)
        zone_marker_min_score:   float = 0.5,
        # In portrait drawings the left margin is usually a machining table, not zones
        portrait_suppress_left_margin_zones: bool = True,
        # Minimum OCR-detected markers to trust an axis without inference
        zone_min_markers_per_axis: int = 2,
        # Enable ISO 5457 lookup to derive the expected zone count
        zone_use_iso_standard_inference: bool = True,
        # Enable cross-axis inference (square-zone heuristic)
        zone_use_cross_axis_inference: bool = True,
        # Max relative difference between detected and expected counts to auto-correct
        # e.g. 0.35 means ±35% → will correct "detected 3, expected 4"
        zone_inference_correction_tolerance: float = 0.35,
        # Constrain to strict ISO 5457 standard grids only. If True, rejects anything that
        # isn't an explicit known paper size, and forces exact regular ISO zone sequences.
        zone_strict_iso_5457: bool = True,
    ):
        self.canny_low                           = canny_low
        self.canny_high                          = canny_high
        self.morph_kernel_size                   = morph_kernel_size
        self.morph_iterations                    = morph_iterations
        self.min_region_area_ratio               = min_region_area_ratio
        self.max_region_area_ratio               = max_region_area_ratio
        self.approx_epsilon_ratio                = approx_epsilon_ratio
        self.title_block_max_area_ratio          = title_block_max_area_ratio
        self.title_block_min_area_ratio          = title_block_min_area_ratio
        self.table_min_aspect_ratio              = table_min_aspect_ratio
        self.table_max_aspect_ratio              = table_max_aspect_ratio
        self.classification_overlap_threshold    = classification_overlap_threshold
        self.zone_marker_min_score               = zone_marker_min_score
        self.portrait_suppress_left_margin_zones = portrait_suppress_left_margin_zones
        self.zone_min_markers_per_axis           = zone_min_markers_per_axis
        self.zone_use_iso_standard_inference     = zone_use_iso_standard_inference
        self.zone_use_cross_axis_inference       = zone_use_cross_axis_inference
        self.zone_inference_correction_tolerance = zone_inference_correction_tolerance
        self.zone_strict_iso_5457                = zone_strict_iso_5457

    # ======================================================================
    # PUBLIC API
    # ======================================================================

    def detect_regions(self, image: np.ndarray) -> List[DetectedRegion]:
        """Detect structural regions in an engineering drawing."""
        img_h, img_w = image.shape[:2]
        img_area     = img_h * img_w
        gray          = self._to_grayscale(image)
        edges         = self._detect_edges(gray)
        edges_closed  = self._close_edges(edges)
        contours      = self._find_contours(edges_closed)
        candidates    = self._filter_rectangular_contours(contours, img_area, img_w, img_h)
        candidates    = self._deduplicate_rects(candidates)
        border, inner = self._separate_border(candidates, img_area)
        regions       = self._classify_regions(inner, border, img_w, img_h, img_area)
        if border is not None:
            regions.insert(0, border)
        return regions

    def find_innermost_boundary(
        self, image: np.ndarray
    ) -> Tuple[Optional[np.ndarray], Optional[Tuple[int, int, int, int]]]:
        """Find the innermost boundary rectangle containing the main drawing."""
        gray    = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        thresh  = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2
        )
        contours, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        height, width = image.shape[:2]
        valid_rects   = []
        for cnt in contours:
            eps    = 0.01 * cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, eps, True)
            x, y, w, h = cv2.boundingRect(cnt)
            area       = cv2.contourArea(cnt)
            rect_area  = w * h
            if rect_area == 0:
                continue
            if (len(approx) >= 4 and w > width * 0.1 and h > height * 0.1
                    and abs(area - rect_area) / rect_area < 0.4 and x >= 0 and y >= 0):
                valid_rects.append({"contour": cnt, "area": area, "rect": (x, y, w, h)})
        if not valid_rects:
            return None, None
        valid_rects.sort(key=lambda r: r["area"], reverse=True)
        target = valid_rects[1] if len(valid_rects) > 1 else valid_rects[0]
        mask   = np.zeros((height, width), dtype=np.uint8)
        cv2.drawContours(mask, [target["contour"]], -1, 255, -1)
        return mask, target["rect"]

    def detect_zones(
        self,
        image:          np.ndarray,
        ocr_detections: list,
        roi_rect:       Optional[Tuple[int, int, int, int]] = None,
        border_bbox:    Optional[Tuple[int, int, int, int]] = None,
        regions:        Optional[List[DetectedRegion]]      = None,
        verbose:        bool = True,
    ) -> Tuple[Optional[ZoneInfo], List[int]]:
        """
        Detect zone markers along the drawing margins with three-tier OCR-miss recovery.

        Tier 1 — ISO 5457 standard lookup (most authoritative)
        Tier 2 — Cross-axis inference     (zone cells are ≈ square)
        Tier 3 — Sequence gap-filling     (partial markers → fill missing labels)

        :param image:          BGR image
        :param ocr_detections: All OCR detections [box, (text, score)]
        :param roi_rect:       (x, y, w, h) of inner boundary, or None to auto-detect
        :param border_bbox:    (x1, y1, x2, y2) of outer border, or None
        :param regions:        Already-detected regions (for title-block clipping)
        :param verbose:        If True, print diagnostics to console
        :return: (ZoneInfo or None, list of zone-marker detection indices)
        """
        img_h, img_w = image.shape[:2]
        orientation  = _detect_orientation(img_w, img_h)

        # ── Auto-detect ROI ──────────────────────────────────────────────
        if roi_rect is None:
            _, roi_rect = self.find_innermost_boundary(image)
        if roi_rect is None:
            return None, []

        rx, ry, rw, rh = roi_rect
        roi_x1, roi_y1, roi_x2, roi_y2 = rx, ry, rx + rw, ry + rh

        # ── Outer border ─────────────────────────────────────────────────
        bx1, by1, bx2, by2 = border_bbox if border_bbox else (0, 0, img_w, img_h)

        # ── Zone grid extent ─────────────────────────────────────────────
        #
        # The zone grid covers different extents depending on orientation:
        #
        # LANDSCAPE:
        #   Zone markers (numbers top/bottom, letters left/right) are evenly
        #   spaced across the FULL inner bordered area — i.e. from the inner
        #   border frame edge to edge.  We use the outer border bbox as the
        #   zone extent because the inner-frame detection can sometimes find a
        #   sub-frame (e.g. a table border) instead of the full drawing frame.
        #   Using the outer border ensures the zone grid aligns with the margin
        #   tick marks as drawn.
        #
        # PORTRAIT:
        #   Column zones span the full inner frame width (roi_x1 → roi_x2).
        #   Row zones span from the top of the inner frame down to the TOP of
        #   the title block — the title block itself is NOT zoned.
        #   The left margin in portrait contains the machining-deviation table
        #   and is NOT part of the zone extent.

        if orientation == DrawingOrientation.LANDSCAPE:
            # Use outer border extent for both axes
            zone_x1, zone_x2 = bx1, bx2
            zone_y1, zone_y2 = by1, by2
        else:
            # Portrait: clip rows at title block top
            title_block_top = roi_y2
            if regions:
                tb = [r for r in regions if r.region_type == RegionType.TITLE_BLOCK]
                if tb:
                    title_block_top = min(r.bbox[1] for r in tb)
            zone_x1, zone_x2 = bx1, bx2          # full width (border edge to edge)
            zone_y1, zone_y2 = roi_y1, title_block_top  # inner frame top → title block top

        zone_w = max(zone_x2 - zone_x1, 1)
        zone_h = max(zone_y2 - zone_y1, 1)

        # ── Margin strips ────────────────────────────────────────────
        # Expand each strip inward by MARGIN_SLACK pixels so zone markers
        # whose OCR-box centre lands just inside the inner frame are still
        # captured (common at high DPI where the marker overlaps the line).
        _MS = 8  # margin slack, pixels
        margin_top    = (bx1,          by1,          bx2,          roi_y1 + _MS)
        margin_bottom = (bx1,          roi_y2 - _MS, bx2,          by2)
        margin_left   = (bx1,          by1,          roi_x1 + _MS, by2)
        margin_right  = (roi_x2 - _MS, by1,          bx2,          by2)

        suppress_left = (
            orientation == DrawingOrientation.PORTRAIT
            and self.portrait_suppress_left_margin_zones
        )

        # ── Scan OCR detections ───────────────────────────────────────────
        #
        # TYPE-GATED scanning — enforce the ISO convention at the point of
        # collection, not as a post-hoc swap:
        #
        #   Top / Bottom margin  → COLUMN markers → must be DIGITS  (1,2,3…)
        #   Left / Right  margin → ROW    markers → must be LETTERS (A,B,C…)
        #
        # This prevents letters from the right-margin from bleeding into
        # col_markers when the top margin strip overlaps a corner, and prevents
        # machining-table digits leaking into row_markers.
        #
        # Exception: if ZERO digit markers are found in the top/bottom margins
        # after a full scan, we fall back to accepting letters there too (the
        # drawing may use letters for columns — rare, but handled downstream by
        # _enforce_zone_label_convention).
        digit_pat  = re.compile(r'^[0-9]$')
        letter_pat = re.compile(r'^[A-Za-z]$')
        any_pat    = re.compile(r'^[A-Za-z0-9]$')

        def _in(cx, cy, s):
            return s[0] <= cx <= s[2] and s[1] <= cy <= s[3]

        col_markers:  List[Tuple[float, str, int]] = []
        row_markers:  List[Tuple[float, str, int]] = []
        zone_indices: List[int]                    = []

        # First pass: strict type-gated scan
        for idx, (box, (text, score)) in enumerate(ocr_detections):
            if score < self.zone_marker_min_score:
                continue
            t = text.strip()
            if not any_pat.match(t):
                continue
            pts = np.array(box, dtype=np.float32).reshape(-1, 2)
            cx  = float(pts[:, 0].mean())
            cy  = float(pts[:, 1].mean())

            in_top    = _in(cx, cy, margin_top)
            in_bottom = _in(cx, cy, margin_bottom)
            in_left   = (not suppress_left) and _in(cx, cy, margin_left)
            in_right  = _in(cx, cy, margin_right)

            if in_top or in_bottom:
                # Columns: accept DIGITS only in this pass
                if digit_pat.match(t):
                    col_markers.append((cx, t.upper(), idx))
                    zone_indices.append(idx)
            elif in_left or in_right:
                # Rows: accept LETTERS only
                if letter_pat.match(t):
                    row_markers.append((cy, t.upper(), idx))
                    zone_indices.append(idx)

        # Fallback pass: if NO digit col-markers were found, accept letters in
        # top/bottom margin too (unusual drawings that letter their columns)
        if not col_markers:
            for idx, (box, (text, score)) in enumerate(ocr_detections):
                if score < self.zone_marker_min_score:
                    continue
                t = text.strip()
                if not letter_pat.match(t):
                    continue
                pts = np.array(box, dtype=np.float32).reshape(-1, 2)
                cx  = float(pts[:, 0].mean())
                cy  = float(pts[:, 1].mean())
                in_top    = _in(cx, cy, margin_top)
                in_bottom = _in(cx, cy, margin_bottom)
                if (in_top or in_bottom) and idx not in zone_indices:
                    col_markers.append((cx, t.upper(), idx))
                    zone_indices.append(idx)

        # ── Validate minimum per axis ─────────────────────────────────────
        if verbose:
            print(f"\n  Zone Detection Diagnostics:")
            print(f"    Orientation: {orientation.value}")
            print(f"    ROI rect: ({rx}, {ry}, {rw}, {rh})")
            print(f"    Border bbox: ({bx1}, {by1}, {bx2}, {by2})")
            print(f"    Zone extent: x=[{zone_x1}..{zone_x2}], y=[{zone_y1}..{zone_y2}]")
            print(f"    Margin strips: top={margin_top}, bottom={margin_bottom}")
            print(f"    Margin strips: left={margin_left}, right={margin_right}")
            print(f"    Suppress left margin: {suppress_left}")
            print(f"    Raw col_markers ({len(col_markers)}): {[(m[1], round(m[0])) for m in col_markers]}")
            print(f"    Raw row_markers ({len(row_markers)}): {[(m[1], round(m[0])) for m in row_markers]}")
        
        if len(col_markers) < self.zone_min_markers_per_axis:
            if verbose: print(f"    ⚠ col_markers below minimum ({self.zone_min_markers_per_axis}), clearing")
            col_markers = []
        if len(row_markers) < self.zone_min_markers_per_axis:
            if verbose: print(f"    ⚠ row_markers below minimum ({self.zone_min_markers_per_axis}), clearing")
            row_markers = []

        # ── Enforce label convention: numbers=cols, letters=rows ──────────
        col_markers, row_markers = self._enforce_zone_label_convention(
            col_markers, row_markers
        )

        # ── Deduplicate (same label in top+bottom or left+right) ─────────
        col_markers = self._deduplicate_zone_markers(col_markers)
        row_markers = self._deduplicate_zone_markers(row_markers)

        # ── Sort by natural label order ───────────────────────────────────
        col_markers.sort(key=lambda m: m[0])
        row_markers.sort(key=lambda m: m[0])
        col_markers = self._sort_markers_by_label(col_markers)
        row_markers = self._sort_markers_by_label(row_markers)

        detected_col_labels = [m[1] for m in col_markers]
        detected_row_labels = [m[1] for m in row_markers]

        # Determine label direction from detected markers (spatial position vs label value).
        # col_markers are sorted by x-position; if label values decrease left→right → descending.
        # row_markers are sorted by y-position; if label values decrease top→bottom → descending.
        col_descending = self._is_descending(detected_col_labels)
        row_descending = self._is_descending(detected_row_labels)

        # ── THREE-TIER INFERENCE ─────────────────────────────────────────
        print(f"    Detected col_labels: {detected_col_labels}, descending={col_descending}")
        print(f"    Detected row_labels: {detected_row_labels}, descending={row_descending}")
        print(f"    Strict ISO 5457 mode: {self.zone_strict_iso_5457}")
        # Resolve columns first, then use resolved col count to help rows.
        final_col_labels, col_source, paper_size = self._infer_zone_axis(
            axis                = 'col',
            detected_labels     = detected_col_labels,
            other_axis_detected = len(detected_row_labels),
            primary_span        = zone_w,
            secondary_span      = zone_h,
            orientation         = orientation,
            is_descending       = col_descending,
            verbose             = verbose,
        )
        if verbose: print(f"    → col result: {final_col_labels} (source={col_source}, paper={paper_size})")
        final_row_labels, row_source, _ = self._infer_zone_axis(
            axis                = 'row',
            detected_labels     = detected_row_labels,
            other_axis_detected = len(final_col_labels),   # use resolved count
            primary_span        = zone_h,
            secondary_span      = zone_w,
            orientation         = orientation,
            paper_size_hint     = paper_size,
            is_descending       = row_descending,
            verbose             = verbose,
        )
        if verbose: print(f"    → row result: {final_row_labels} (source={row_source})")

        if not final_col_labels and not final_row_labels:
            if verbose: print(f"    ✗ Both axes empty — returning None")
            return None, zone_indices

        col_boundaries = self._compute_zone_boundaries(len(final_col_labels), zone_x1, zone_x2)
        row_boundaries = self._compute_zone_boundaries(len(final_row_labels), zone_y1, zone_y2)

        zone_info = ZoneInfo(
            col_labels     = final_col_labels,
            row_labels     = final_row_labels,
            col_boundaries = col_boundaries,
            row_boundaries = row_boundaries,
            roi_bbox       = (roi_x1, roi_y1, roi_x2, roi_y2),
            zone_bbox      = (zone_x1, zone_y1, zone_x2, zone_y2),
            col_source     = col_source,
            row_source     = row_source,
            paper_size     = paper_size,
        )
        return zone_info, zone_indices

    # ======================================================================
    # THREE-TIER ZONE AXIS INFERENCE
    # ======================================================================

    def _infer_zone_axis(
        self,
        axis:                str,
        detected_labels:     List[str],
        other_axis_detected: int,
        primary_span:        int,
        secondary_span:      int,
        orientation:         DrawingOrientation,
        paper_size_hint:     Optional[str] = None,
        is_descending:       Optional[bool] = None,
        verbose:             bool = True,
    ) -> Tuple[List[str], ZoneInferenceSource, Optional[str]]:
        """
        Resolve the final zone label list for one axis.

        Resolution order:
          1. ISO 5457 standard lookup (most authoritative)
          2. Cross-axis inference (zone cells ≈ square)
          3. Sequence gap-filling / synthesise

        :param is_descending: Direction hint from detected markers.  None means
            unknown — falls back to standard convention (cols ascending left→right,
            rows ascending top→bottom).
        """
        n_det  = len(detected_labels)
        min_ok = self.zone_min_markers_per_axis

        # Direction: use detected direction when known, else standard convention.
        # ISO 5457 / most drawings: cols left→right ascending, rows top→bottom ascending.
        # Some portrait drawings number cols right→left (4,3,2,1) — detected direction wins.
        if is_descending is None:
            descending = False   # safe default: ascending
        else:
            descending = is_descending

        # ── Tier 1: ISO Standard Lookup ───────────────────────────────────
        paper_match: Optional[_PaperSpec] = None
        if self.zone_use_iso_standard_inference:
            # Try matching by THIS axis detected count
            if n_det >= min_ok:
                paper_match = _best_paper_spec_for_count(n_det, axis, orientation)
            # Try matching by OTHER axis detected count
            if paper_match is None and other_axis_detected >= min_ok:
                other = 'row' if axis == 'col' else 'col'
                paper_match = _best_paper_spec_for_count(other_axis_detected, other, orientation)
            # Tier 1b: Fuzzy combined match — use both axes to find the closest spec.
            # Handles OCR errors like '6' misread as '9' that throw off single-axis lookup.
            if paper_match is None and n_det >= min_ok and other_axis_detected >= min_ok:
                if axis == 'col':
                    paper_match = _best_paper_spec_fuzzy(n_det, other_axis_detected, orientation)
                else:
                    paper_match = _best_paper_spec_fuzzy(other_axis_detected, n_det, orientation)
                if paper_match:
                    if verbose:
                        print(f"    ℹ Fuzzy ISO match: {paper_match.name} "
                              f"({paper_match.n_cols}×{paper_match.n_rows} {paper_match.orientation})")
            # If a paper-size hint was already resolved for the other axis, honour it
            if paper_match is None and paper_size_hint:
                candidates = [
                    s for s in _ISO_PAPER_SPECS
                    if s.name == paper_size_hint and s.orientation == orientation.value
                ]
                if len(candidates) == 1:
                    paper_match = candidates[0]

        iso_count: Optional[int] = None
        paper_name: Optional[str] = None
        if paper_match is not None:
            iso_count  = paper_match.n_cols if axis == 'col' else paper_match.n_rows
            paper_name = paper_match.name

        # ── Tier 2: Cross-axis Inference ─────────────────────────────────
        # ISO 5457: zones ≈ square → n_this / n_other ≈ span_this / span_other
        cross_count: Optional[int] = None
        if not self.zone_strict_iso_5457 and self.zone_use_cross_axis_inference and other_axis_detected >= min_ok and secondary_span > 0:
            ratio       = primary_span / secondary_span
            cross_count = max(1, round(ratio * other_axis_detected))

        # ── Determine expected count ──────────────────────────────────────
        # ISO wins over cross-axis; cross-axis wins over "don't know"
        expected: Optional[int] = iso_count if iso_count is not None else cross_count

        if self.zone_strict_iso_5457 and iso_count is None:
            # In strict ISO 5457 mode, we reject axes that cannot be matched to the standard
            return [], ZoneInferenceSource.FALLBACK, None

        tol = self.zone_inference_correction_tolerance

        # ── No detections at all ─────────────────────────────────────────
        if n_det == 0:
            if expected is not None:
                src    = (ZoneInferenceSource.ISO_STANDARD if iso_count is not None
                          else ZoneInferenceSource.CROSS_AXIS)
                labels = _synthesise_labels(axis, expected, descending)
                return labels, src, paper_name
            return [], ZoneInferenceSource.FALLBACK, None

        # ── Detections present ────────────────────────────────────────────
        if expected is None:
            # Nothing to correct against → return detected as-is
            return detected_labels, ZoneInferenceSource.OCR_DETECTED, paper_name

        diff_ratio = abs(n_det - expected) / max(expected, 1)

        if self.zone_strict_iso_5457 or diff_ratio <= tol:
            # Counts are close, or strict enforcement is active: fill any sequence gaps up to expected count
            full_labels, fill_src = _fill_sequence_gaps(
                detected_labels, expected, descending
            )
            if fill_src == ZoneInferenceSource.OCR_DETECTED and n_det < expected:
                fill_src = ZoneInferenceSource.OCR_PARTIAL
                
            if self.zone_strict_iso_5457:
                fill_src = ZoneInferenceSource.ISO_STANDARD
                
            return full_labels, fill_src, paper_name
        else:
            # Counts differ too much: trust the OCR-detected labels as-is
            return detected_labels, ZoneInferenceSource.OCR_DETECTED, paper_name

    # ======================================================================
    # ZONE DETECTION INTERNALS
    # ======================================================================

    def _enforce_zone_label_convention(
        self,
        col_markers: List[Tuple[float, str, int]],
        row_markers: List[Tuple[float, str, int]],
    ) -> Tuple[List, List]:
        """
        Enforce the ISO convention: columns = digits, rows = letters.

        Handles all possible OCR classification errors:

          col=digits, row=letters → correct, no change
          col=letters, row=digits → swapped, fix by swapping back
          col=letters, row=letters → both letters ended up in wrong buckets;
              the larger set is likely the row markers (more rows than cols on
              portrait drawings), smaller set is likely col markers that OCR
              read as letters — discard col, keep row, let inference fill cols
          col=letters, row=empty  → all letters went to col bucket incorrectly;
              move them to row, let inference handle cols
          col=digits, row=empty   → fine, rows will be inferred
          col=empty, row=digits   → digits misclassified as rows; move to cols
          col=empty, row=letters  → correct placement but col empty; fine
          col=empty, row=empty    → nothing detected; fine
          mixed types on either axis → discard that axis entirely
        """
        def _all_dig(m): return bool(m) and all(x[1].isdigit() for x in m)
        def _all_alp(m): return bool(m) and all(x[1].isalpha() for x in m)
        def _mixed(m):   return bool(m) and not _all_dig(m) and not _all_alp(m)

        # Discard any axis that has mixed types (letters + digits together = noise)
        if _mixed(col_markers):
            col_markers = []
        if _mixed(row_markers):
            row_markers = []

        col_is_dig = _all_dig(col_markers)
        col_is_alp = _all_alp(col_markers)
        row_is_dig = _all_dig(row_markers)
        row_is_alp = _all_alp(row_markers)

        # Perfect: digits in cols, letters in rows
        if col_is_dig and row_is_alp:
            return col_markers, row_markers

        # Swapped: letters in cols, digits in rows → swap
        if col_is_alp and row_is_dig:
            return row_markers, col_markers

        # Both letters: top/bottom margin picked up letters (e.g. corner overlap).
        # Since type-gated scanning runs first, this should only happen in the
        # fallback path.  Merge both into rows; cols will be inferred.
        if col_is_alp and row_is_alp:
            # Merge, deduplicate by label
            merged = col_markers + [m for m in row_markers
                                    if m[1] not in {c[1] for c in col_markers}]
            return [], merged

        # Digits ended up in rows only (digits misclassified as row markers)
        if (not col_markers) and row_is_dig:
            return row_markers, []

        # Letters ended up in cols only (no rows detected at all)
        if col_is_alp and (not row_markers):
            return [], col_markers   # move to rows, infer cols

        # Digits in cols only, no rows → fine
        if col_is_dig and (not row_markers):
            return col_markers, []

        # Fallback: return as-is
        return col_markers, row_markers

    def _deduplicate_zone_markers(
        self, markers: List[Tuple[float, str, int]]
    ) -> List[Tuple[float, str, int]]:
        """Merge duplicate labels (same letter/digit in both margins)."""
        if not markers:
            return markers
        groups: Dict[str, List[Tuple[float, int]]] = {}
        for pos, label, idx in markers:
            groups.setdefault(label, []).append((pos, idx))
        result = []
        for label, entries in groups.items():
            avg = sum(e[0] for e in entries) / len(entries)
            result.append((avg, label, entries[0][1]))
        return result

    def _sort_markers_by_label(
        self, markers: List[Tuple[float, str, int]]
    ) -> List[Tuple[float, str, int]]:
        """Re-sort markers by natural label order to fix OCR position noise."""
        if len(markers) <= 1:
            return markers
        labels    = [m[1] for m in markers]
        all_alpha = all(c.isalpha() for c in labels)
        all_digit = all(c.isdigit() for c in labels)
        if not all_alpha and not all_digit:
            return markers
        values          = [int(m[1]) if all_digit else ord(m[1].upper()) for m in markers]
        asc_pairs       = sum(1 for i in range(len(values) - 1) if values[i] < values[i + 1])
        is_descending   = asc_pairs < len(values) // 2
        key_fn          = (lambda m: int(m[1])) if all_digit else (lambda m: m[1].upper())
        return sorted(markers, key=key_fn, reverse=is_descending)

    def _is_descending(self, labels: List[str]) -> Optional[bool]:
        """
        Determine the direction of a zone label sequence.

        Returns True if descending, False if ascending, None if unknown
        (fewer than 2 labels, or mixed type).

        This is determined from the SPATIAL order of the markers (they are
        already sorted by position at this point) vs their label values.
        A sequence like ['4','3','2','1'] (left→right) is descending.
        """
        if len(labels) < 2:
            return None
        all_alpha = all(c.isalpha() for c in labels)
        all_digit = all(c.isdigit() for c in labels)
        if not all_alpha and not all_digit:
            return None
        values      = [int(v) if all_digit else ord(v.upper()) for v in labels]
        asc_pairs   = sum(1 for i in range(len(values) - 1) if values[i] < values[i + 1])
        return asc_pairs < len(values) // 2

    def _compute_zone_boundaries(self, n: int, start: int, end: int) -> List[int]:
        """Compute evenly-spaced zone boundaries."""
        if n <= 0:
            return [start, end]
        sp = (end - start) / n
        return [int(start + i * sp) for i in range(n + 1)]

    # ======================================================================
    # CLASSIFICATION
    # ======================================================================

    def classify_detections(
        self,
        ocr_detections:      list,
        regions:             List[DetectedRegion],
        zone_info:           Optional[ZoneInfo]  = None,
        zone_marker_indices: Optional[List[int]] = None,
        roi_bbox:            Optional[Tuple[int, int, int, int]] = None,
    ) -> List[dict]:
        """Classify each OCR detection by region and assign zone labels."""
        zone_set = set(zone_marker_indices or [])
        excl     = [r for r in regions
                    if r.region_type not in (RegionType.DRAWING_AREA, RegionType.BORDER)]

        classified = []
        for idx, (box, (text, score)) in enumerate(ocr_detections):
            pts   = np.array(box, dtype=np.float32).reshape(-1, 2)
            xmn, ymn = pts.min(axis=0); xmx, ymx = pts.max(axis=0)
            det_bbox = (int(xmn), int(ymn), int(xmx), int(ymx))
            cx, cy   = int((xmn + xmx) / 2), int((ymn + ymx) / 2)

            if idx in zone_set:
                atype = RegionType.ZONE_MARKER
                aidx  = -1
            else:
                # Check specific regions first (Title Block, Tables, etc.)
                atype = RegionType.UNKNOWN
                aidx = -1
                for ridx, r in enumerate(excl):
                    if r.contains_bbox(det_bbox, self.classification_overlap_threshold):
                        atype = r.region_type
                        aidx = ridx
                        break
                
                # If not in a specific region, check if it's in the drawing ROI
                if atype == RegionType.UNKNOWN:
                    if roi_bbox:
                        rx1, ry1, rx2, ry2 = roi_bbox
                        if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
                            atype = RegionType.DRAWING_AREA
                        else:
                            atype = RegionType.UNKNOWN
                    else:
                        atype = RegionType.DRAWING_AREA  # Fallback if no ROI defined

            zone_label = None
            if zone_info and atype == RegionType.DRAWING_AREA:
                zx1, zy1, zx2, zy2 = zone_info.zone_bbox
                if zx1 <= cx <= zx2 and zy1 <= cy <= zy2:
                    zone_label = zone_info.get_zone_label(cx, cy)

            classified.append({
                'box': box, 'text': text, 'score': score,
                'bbox': det_bbox, 'center': (cx, cy),
                'region_type': atype, 'region_index': aidx, 'zone': zone_label,
            })
        return classified

    def get_roi_detections(self, classified: List[dict]) -> list:
        return [[d['box'], (d['text'], d['score'])]
                for d in classified if d['region_type'] == RegionType.DRAWING_AREA]

    def get_detections_by_region(self, classified: List[dict], rtype: RegionType) -> list:
        return [[d['box'], (d['text'], d['score'])]
                for d in classified if d['region_type'] == rtype]

    def compute_exclusion_overlays(
        self,
        roi_bbox:    Optional[Tuple[int, int, int, int]],
        border_bbox: Optional[Tuple[int, int, int, int]] = None,
        img_w: int = 0,
        img_h: int = 0,
    ) -> List[dict]:
        if roi_bbox is None:
            return []
        rx1, ry1, rx2, ry2 = roi_bbox
        bx1, by1, bx2, by2 = border_bbox if border_bbox else (0, 0, img_w, img_h)
        out = []
        if ry1 > by1: out.append({'bbox': [bx1, by1, bx2, ry1], 'label': 'excluded'})
        if ry2 < by2: out.append({'bbox': [bx1, ry2, bx2, by2], 'label': 'excluded'})
        if rx1 > bx1: out.append({'bbox': [bx1, ry1, rx1, ry2], 'label': 'excluded'})
        if rx2 < bx2: out.append({'bbox': [rx2, ry1, bx2, ry2], 'label': 'excluded'})
        return out

    # ======================================================================
    # STRUCTURAL REGION DETECTION
    # ======================================================================

    def _to_grayscale(self, img): 
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img.copy()

    def _detect_edges(self, gray):
        return cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), self.canny_low, self.canny_high)

    def _close_edges(self, edges):
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (self.morph_kernel_size,) * 2)
        return cv2.morphologyEx(edges, cv2.MORPH_CLOSE, k, iterations=self.morph_iterations)

    def _find_contours(self, edges):
        c, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        return c

    def _filter_rectangular_contours(self, contours, img_area, img_w, img_h):
        out = []
        lo, hi = img_area * self.min_region_area_ratio, img_area * self.max_region_area_ratio
        for cnt in contours:
            peri   = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, self.approx_epsilon_ratio * peri, True)
            if not (4 <= len(approx) <= 12):
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            ca = cv2.contourArea(cnt); ra = w * h
            if not (lo <= ra <= hi):
                continue
            if ra > 0 and ca / ra < 0.6:
                continue
            out.append((cnt, (x, y, x + w, y + h)))
        return out

    def _deduplicate_rects(self, cands, iou_thr=0.5):
        if not cands:
            return cands
        cands.sort(key=lambda c: _bbox_area(c[1]), reverse=True)
        kept = []
        for cnt, bbox in cands:
            if not any(self._iou(bbox, kb) > iou_thr for _, kb in kept):
                kept.append((cnt, bbox))
        return kept

    def _iou(self, a, b):
        x1 = max(a[0], b[0]); y1 = max(a[1], b[1])
        x2 = min(a[2], b[2]); y2 = min(a[3], b[3])
        if x1 >= x2 or y1 >= y2: return 0.0
        inter = (x2 - x1) * (y2 - y1)
        union = _bbox_area(a) + _bbox_area(b) - inter
        return inter / union if union > 0 else 0.0

    def _separate_border(self, cands, img_area):
        if not cands: return None, []
        cnt, bbox = cands[0]
        if _bbox_area(bbox) / img_area > 0.50:
            b = DetectedRegion(RegionType.BORDER, bbox,
                               _bbox_area(bbox) / img_area, cnt, {"is_outer_border": True})
            return b, cands[1:]
        return None, cands

    def _classify_regions(self, cands, border, img_w, img_h, img_area):
        out = []
        rx1, ry1, rx2, ry2 = border.bbox if border else (0, 0, img_w, img_h)
        rw = rx2 - rx1; rh = ry2 - ry1; ra = rw * rh

        for cnt, bbox in cands:
            x1, y1, x2, y2 = bbox
            w = x2 - x1; h = y2 - y1; area = w * h
            cx = (x1 + x2) // 2; cy = (y1 + y2) // 2
            rcx = (cx - rx1) / rw if rw else 0.5
            rcy = (cy - ry1) / rh if rh else 0.5
            ar  = area / ra       if ra else 0

            rtype = RegionType.UNKNOWN
            ts    = self.title_block_min_area_ratio <= ar <= self.title_block_max_area_ratio
            if ts and (
                (rcx > 0.55 and rcy > 0.70)
                or (rcy > 0.80 and w / rw > 0.50)
                or (rcx > 0.75 and h / rh > 0.30)
            ):
                rtype = RegionType.TITLE_BLOCK
            elif ar < 0.08 and rcx > 0.70 and rcy < 0.30:
                rtype = RegionType.REVISION_BLOCK
            elif (ar >= 0.005
                  and self.table_min_aspect_ratio <= (w / h if h else 0) <= self.table_max_aspect_ratio
                  and (rcx < 0.15 or rcx > 0.85 or rcy < 0.15 or rcy > 0.85 or ar > 0.02)):
                rtype = RegionType.TABLE

            if rtype == RegionType.UNKNOWN and ar < 0.003:
                continue

            out.append(DetectedRegion(
                rtype, bbox,
                cv2.contourArea(cnt) / area if area else 0,
                cnt,
                {"rel_position": (round(rcx, 3), round(rcy, 3)),
                 "area_ratio": round(ar, 4),
                 "aspect_ratio": round(w / h if h else 0, 2)},
            ))
        return out

    # ======================================================================
    # VISUALIZATION
    # ======================================================================

    REGION_COLORS = {
        RegionType.DRAWING_AREA:   (0, 200, 0),
        RegionType.TITLE_BLOCK:    (255, 100, 0),
        RegionType.TABLE:          (0, 165, 255),
        RegionType.REVISION_BLOCK: (255, 0, 255),
        RegionType.BORDER:         (128, 128, 128),
        RegionType.ZONE_MARKER:    (0, 200, 200),
        RegionType.UNKNOWN:        (100, 100, 100),
    }

    def draw_regions(self, image, regions):
        vis = image.copy(); ov = image.copy()
        for r in regions:
            c = self.REGION_COLORS.get(r.region_type, (100,100,100))
            x1, y1, x2, y2 = r.bbox
            cv2.rectangle(ov, (x1,y1), (x2,y2), c, -1)
            cv2.rectangle(vis,(x1,y1), (x2,y2), c,  2)
            lbl = f"{r.region_type.value} ({r.metadata.get('area_ratio',0):.1%})"
            (lw,lh),_ = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
            cv2.rectangle(vis,(x1,y1-lh-10),(x1+lw+4,y1),c,-1)
            cv2.putText(vis,lbl,(x1+2,y1-5),cv2.FONT_HERSHEY_SIMPLEX,0.6,(255,255,255),1)
        cv2.addWeighted(ov, 0.15, vis, 0.85, 0, vis)
        return vis

    def draw_classified_detections(self, image, classified):
        vis = image.copy()
        for d in classified:
            c = self.REGION_COLORS.get(d['region_type'],(100,100,100))
            x1,y1,x2,y2 = d['bbox']
            cv2.rectangle(vis,(x1,y1),(x2,y2),c,2)
            lbl = f"{d['text'][:20]} [{d['region_type'].value}]"
            (lw,lh),_ = cv2.getTextSize(lbl,cv2.FONT_HERSHEY_SIMPLEX,0.4,1)
            cv2.rectangle(vis,(x1,y1-lh-6),(x1+lw,y1),c,-1)
            cv2.putText(vis,lbl,(x1,y1-3),cv2.FONT_HERSHEY_SIMPLEX,0.4,(255,255,255),1)
        return vis

    def draw_zone_grid(
        self,
        image:     np.ndarray,
        zone_info: ZoneInfo,
        color:     Tuple[int,int,int] = (0, 180, 255),
        alpha:     float = 0.20,
    ) -> np.ndarray:
        """Overlay zone grid with cell labels and source annotation."""
        vis = image.copy(); ov = image.copy()

        for ci, _ in enumerate(zone_info.col_labels):
            for ri, _ in enumerate(zone_info.row_labels):
                cx1 = zone_info.col_boundaries[ci];  cx2 = zone_info.col_boundaries[ci+1]
                ry1 = zone_info.row_boundaries[ri];  ry2 = zone_info.row_boundaries[ri+1]
                cell_c = ((color[0]+ri*15)%255, (color[1]+ci*20)%255, color[2])
                cv2.rectangle(ov,(cx1,ry1),(cx2,ry2),cell_c,-1)
                lbl = zone_info.get_zone_label((cx1+cx2)//2,(ry1+ry2)//2)
                if lbl:
                    cv2.putText(vis,lbl,(cx1+4,ry1+18),cv2.FONT_HERSHEY_SIMPLEX,0.5,color,1)

        cv2.addWeighted(ov, alpha, vis, 1-alpha, 0, vis)
        for x in zone_info.col_boundaries:
            cv2.line(vis,(x,zone_info.row_boundaries[0]),(x,zone_info.row_boundaries[-1]),color,1)
        for y in zone_info.row_boundaries:
            cv2.line(vis,(zone_info.col_boundaries[0],y),(zone_info.col_boundaries[-1],y),color,1)

        # Diagnostic banner: shows source and paper size
        src = (f"cols={len(zone_info.col_labels)}[{zone_info.col_source.value[:3].upper()}] "
               f"rows={len(zone_info.row_labels)}[{zone_info.row_source.value[:3].upper()}]"
               + (f" paper={zone_info.paper_size}" if zone_info.paper_size else ""))
        cv2.putText(vis, src,
                    (zone_info.col_boundaries[0]+4, zone_info.row_boundaries[0]+16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0,0,180), 1)
        return vis


# ===========================================================================
# STANDALONE TEST / DEMO
# ===========================================================================

def main():
    import argparse
    from pipeline.engine import OCREngine

    parser = argparse.ArgumentParser(description="Region Detector for Engineering Drawings")
    parser.add_argument("image_path")
    parser.add_argument("--page",              type=int,   default=0)
    parser.add_argument("--conf-thresh",       type=float, default=0.5)
    parser.add_argument("--output-regions",    default="regions_detected.jpg")
    parser.add_argument("--output-classified", default="detections_classified.jpg")
    parser.add_argument("--output-roi",        default="roi_only.jpg")
    parser.add_argument("--output-zones",      default="zones_grid.jpg")
    args = parser.parse_args()

    print("="*60, "\nSTAGE 1: OCR\n", "="*60)
    engine               = OCREngine(conf_thresh=args.conf_thresh)
    raw, orig_img        = engine.predict(args.image_path, args.page)
    all_det              = engine.parse_results(raw)
    filtered             = engine.filter_results_by_confidence(all_det)
    img_h, img_w         = orig_img.shape[:2]
    print(f"  Detections: {len(all_det)} / {len(filtered)} filtered")
    print(f"  Orientation: {_detect_orientation(img_w, img_h).value}")

    print("="*60, "\nSTAGE 2: Region detection\n", "="*60)
    det     = RegionDetector()
    regions = det.detect_regions(orig_img)
    for r in regions:
        print(f"  [{r.region_type.value:>16}] {r.bbox}")

    print("="*60, "\nSTAGE 3: Inner ROI boundary\n", "="*60)
    _, roi_rect = det.find_innermost_boundary(orig_img)
    roi_bbox = border_bbox = None
    if roi_rect:
        rx, ry, rw, rh = roi_rect
        roi_bbox = (rx, ry, rx+rw, ry+rh)
        print(f"  ROI: {roi_bbox}")
    br = next((r for r in regions if r.region_type == RegionType.BORDER), None)
    if br:
        border_bbox = br.bbox

    print("="*60, "\nSTAGE 4: Zone detection\n", "="*60)
    zone_info, zone_idx = det.detect_zones(
        orig_img, filtered,
        roi_rect=roi_rect, border_bbox=border_bbox, regions=regions,
    )
    if zone_info:
        print(f"  Columns  : {zone_info.col_labels}  [{zone_info.col_source.value}]")
        print(f"  Rows     : {zone_info.row_labels}  [{zone_info.row_source.value}]")
        print(f"  Paper    : {zone_info.paper_size or 'unknown'}")
        print(f"  Zone bbox: {zone_info.zone_bbox}")
    else:
        print("  No zones detected.")

    print("="*60, "\nSTAGE 5: Classify\n", "="*60)
    classified = det.classify_detections(
        filtered, regions,
        zone_info=zone_info, zone_marker_indices=zone_idx, roi_bbox=roi_bbox,
    )
    from collections import Counter
    for t, c in sorted(Counter(d['region_type'].value for d in classified).items()):
        print(f"  {t:>16}: {c}")

    print("="*60, "\nSTAGE 6: Visualise\n", "="*60)
    cv2.imwrite(args.output_regions,    det.draw_regions(orig_img, regions))
    cv2.imwrite(args.output_classified, det.draw_classified_detections(orig_img, classified))
    cv2.imwrite(args.output_roi,        engine.draw_results(orig_img, det.get_roi_detections(classified)))
    if zone_info:
        cv2.imwrite(args.output_zones,  det.draw_zone_grid(orig_img, zone_info))
        print(f"  Zone grid: {args.output_zones}")
    print("\nPIPELINE COMPLETE")


if __name__ == "__main__":
    main()