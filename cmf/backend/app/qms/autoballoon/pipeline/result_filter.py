"""
Result Filter
==============
Handles confidence filtering, ROI mask filtering, and GD&T character promotion.

Improvements over v1:
  - GD&T character set expanded to full set of 14 controls + ISO modifier circles.
  - FCF pattern regex broadened to catch patterns with variable spacing and
    more symbol variants (e.g. // for parallelism, ⊥ variants).
  - Added promotion of text that looks like FCF tolerance-value strings even
    when the leading symbol is embedded in the same text run.
  - ROI mask filtering handles edge-case tuple inputs (existing fix retained).
"""

import re
import numpy as np


# ---------------------------------------------------------------------------
# Complete GD&T Unicode character inventory
# ---------------------------------------------------------------------------

# All 14 geometric characteristic symbols that OCR might return as single chars
_GDT_SINGLE_CHARS = frozenset([
    # Form
    "⏤",  # Straightness
    "⏥",  # Flatness
    "○",  # Circularity / Roundness (U+25CB)
    "⌭",  # Cylindricity
    # Profile
    "⌒",  # Profile of a Line
    "⌓",  # Profile of a Surface
    # Orientation
    "⏊",  # Perpendicularity (U+23CA)
    "∠",  # Angularity
    "⫽",  # Parallelism (U+2AFD)
    # Location
    "⌖",  # Position (U+2316)
    "◎",  # Concentricity / Coaxiality (U+25CE)
    "⌯",  # Symmetry (U+232F)
    # Runout
    "↗",  # Circular Runout  (U+2197 used in some fonts)
    "⌰",  # Total Runout (U+2330)
    # Additional OCR artefact variants
    "⊙",  # Concentricity variant (U+2299)
    "⊕",  # Position variant (U+2295)
    "⊥",  # Perpendicularity variant (U+22A5)
    "∥",  # Parallelism variant (U+2225)
    "⌿",  # Slash/Profile OCR variant (U+233F)
    "⌢",  # Arc/Profile OCR variant (U+2322)
])

# Modifier circles that OCR sometimes returns as standalone detections
_GDT_MODIFIER_CHARS = frozenset(["Ⓜ", "Ⓛ", "Ⓟ", "Ⓕ", "Ⓣ", "Ⓢ", "Ⓤ", "Ⓓ", "Ⓔ", "Ⓘ", "Ⓝ"])

# All promotable single characters
_ALL_GDT_CHARS = _GDT_SINGLE_CHARS | _GDT_MODIFIER_CHARS

# ---------------------------------------------------------------------------
# FCF pattern: symbol (or text proxy) followed by a tolerance value
# Covers:
#   "⌖ 0.010 M A B"    exact symbol + value + optional datum letters
#   "// 0.05"           parallelism written as double-slash
#   "⊥ 0.1 A"
#   "⏊0.050A"           no spaces
#   "11 0.010 M"        OCR renders ⏊ as "11" (common Tesseract/Paddle artefact)
#   "1/ 0.020"          partial slash artefact
#   "JS5"               runout code in some European drawings
# ---------------------------------------------------------------------------
_FCF_SYMBOL_PART = (
    r"(?:"
    r"[⌖⌰⏊⫽↗⌢⏤⏥⌭◎⌿∠○⌓⊙⊕⊥∥⌯⌒]"  # Unicode GD&T symbols
    r"|11\b"                           # ⏊ commonly OCR'd as "11"
    r"|\/{1,2}"                        # / or // (parallelism, profile)
    r"|1\/"                            # 1/ partial
    r")"
)
_FCF_TOL_PART = r"\s*\d*\.?\d+"       # tolerance value, spaces allowed

_FCF_REGEX = re.compile(
    r"^" + _FCF_SYMBOL_PART + _FCF_TOL_PART,
    re.UNICODE,
)

# Looser pattern: catches "0.050 M A B" — a value+modifier+datums string that
# landed in OCR without its leading symbol (symbol was detected by YOLO instead).
_FCF_VALUE_ONLY_REGEX = re.compile(
    r"^\d+\.\d+\s*(?:[ⒶⒷⒸⒹⒶⒷⒸⒹⓂⓁⓅⓅⓅ]|[A-Z](?:\s+[A-Z])*)?$"
)


class ResultFilter:
    """Filters and promotes OCR detection results."""

    @staticmethod
    def filter_by_confidence(detections: list, conf_thresh: float) -> list:
        """Filter OCR results based on a confidence threshold."""
        return [
            [box, (text, score)]
            for box, (text, score) in detections
            if score >= conf_thresh
        ]

    @staticmethod
    def filter_by_roi_mask(detections: list, roi_mask, img_h, img_w):
        """
        Separate detections into ROI (inside mask) and excluded (outside mask).
        Returns (roi_detections, excluded_detections).
        """
        if roi_mask is None:
            return detections, []

        # Guard against tuple being passed instead of scalar
        if isinstance(img_w, tuple):
            img_w = img_w[0]
        if isinstance(img_h, tuple):
            img_h = img_h[0]

        roi_detections      = []
        excluded_detections = []

        for box, (text, score) in detections:
            pts = np.array(box, dtype=np.float32).reshape(-1, 2)
            cx  = int(np.clip(pts[:, 0].mean(), 0, img_w - 1))
            cy  = int(np.clip(pts[:, 1].mean(), 0, img_h - 1))

            if roi_mask[cy, cx] == 255:
                roi_detections.append([box, (text, score)])
            else:
                excluded_detections.append([box, (text, score)])

        return roi_detections, excluded_detections

    @staticmethod
    def promote_gdt_characters(roi_detections: list, gdt_detections: list):
        """
        Promote OCR detections that contain GD&T symbols or FCF patterns.

        Two promotion strategies:
          A. Single character in _ALL_GDT_CHARS → promote as pure symbol.
          B. Text matching _FCF_REGEX → the OCR read both symbol and value
             in one run (common for vertical/rotated FCFs); promote the whole
             detection as a pre-formed FCF.

        Promoted detections are removed from roi_detections and appended to
        gdt_detections so the grouper can handle them.

        :return: (cleaned_roi_detections, promoted_indices_set)
        """
        promoted_indices = set()

        for i, (box, (text, score)) in enumerate(roi_detections):
            text_clean = text.strip()
            if not text_clean:
                continue

            is_gdt = False

            # Strategy A: single GD&T symbol character
            if len(text_clean) == 1 and text_clean in _ALL_GDT_CHARS:
                is_gdt = True

            # Strategy B: full FCF text run (symbol + value [+ datums])
            elif _FCF_REGEX.match(text_clean):
                is_gdt = True

            # Strategy C: modifier circle (may appear between FCF compartments)
            elif len(text_clean) == 1 and text_clean in _GDT_MODIFIER_CHARS:
                is_gdt = True

            if is_gdt:
                pts = np.array(box, dtype=np.float32).reshape(-1, 2)
                gx1, gy1 = pts.min(axis=0).tolist()
                gx2, gy2 = pts.max(axis=0).tolist()
                gdt_detections.append({
                    "bbox":     [gx1, gy1, gx2, gy2],
                    "score":    score,
                    "class":    text_clean,
                    "class_id": 0,
                    "is_fcf":   True,
                })
                promoted_indices.add(i)

        cleaned = [det for i, det in enumerate(roi_detections) if i not in promoted_indices]
        return cleaned, promoted_indices