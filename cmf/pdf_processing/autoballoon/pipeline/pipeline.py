"""
OCR Pipeline Orchestrator
==========================
Composes all pipeline stages into a single `run()` method.

Pipeline stages:
  1.  Image Loading
  2.  ROI Detection (innermost boundary)
  3.  Crop to ROI
  4.  GD&T Detection (full or tiled, two-pass)
  5.  Mask GD&T regions for OCR
  5b. OCR Inference + coordinate translation to global space
  6.  Stacked Tolerance Clustering (NEW)  ← merges +tol/-tol/limit stacks
  7.  Confidence & ROI mask filtering
  8.  GD&T character promotion
  9a. FCF Grouping
  9b. Diameter Grouping
  10. Zone & Region detection
  10b.Classification
  10c.Basic Dimension / Datum / Flag Note extraction
  11. Dimension Parsing

Bug fixes vs v1:
  - Vector PDF masking check now uses global GD&T coordinates directly
    (removed incorrect crop_offset subtraction on cx/cy).
  - raw_gdt_detections saved after global translation, before any splitting.
  - Stacked tolerance clustering inserted before confidence filtering so
    the grouper sees the raw OCR output.
  - OCR scale factor defaulted to 1.0 to prevent ZeroDivisionError on
    images already within max_ocr_dim.
"""

import re
import copy
import cv2
import numpy as np

from .dim_parser import DimParser
from .result_filter import ResultFilter
from .region_detector import RegionType


class OCRPipeline:
    """
    Orchestrates the full OCR pipeline for engineering drawings.
    """

    def __init__(
        self,
        image_loader,
        preprocessor,
        ocr_runner,
        gdt_detector,
        gdt_grouper,
        region_detector,
        conf_thresh: float = 0.85,
    ):
        self.image_loader    = image_loader
        self.preprocessor    = preprocessor
        self.ocr_runner      = ocr_runner
        self.gdt_detector    = gdt_detector
        self.gdt_grouper     = gdt_grouper
        self.region_detector = region_detector
        self.conf_thresh     = conf_thresh
        self._has_printed_static_info = False

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(
        self,
        image_input,
        page_index: int = 0,
        max_ocr_dim: int = 5120,
        use_tiled_gdt: bool = True,
        user_region: list = None,
        cached_roi_boundary: dict = None,
        cached_zone_info = None,
        cached_regions: list = None,
        verbose: bool = None,
    ) -> dict:
        """
        Run the full OCR pipeline.

        :param image_input:   File path (str) or numpy array.
        :param page_index:    PDF page index (0-based).
        :param max_ocr_dim:   Maximum dimension (px) for OCR input scaling.
        :param use_tiled_gdt: Use tiled two-pass GD&T detection.
        :param user_region:   Optional [x1, y1, x2, y2] region to process.
        :param cached_roi_boundary: Previously detected ROI boundary info.
        :param cached_zone_info: Previously detected zone grid info.
        :param cached_regions: Previously detected structural regions.
        :return: Result dict (see return statement for all keys).
        """

        # ── Stage 1: Load image ──────────────────────────────────────────
        original_img = self.image_loader.load(image_input, page_index)
        h, w = original_img.shape[:2]
        
        if verbose is None:
            verbose = not self._has_printed_static_info
            
        if verbose:
            print(f"Drawing size: {w}×{h}")

        # ── Stage 2: Global ROI detection (One-time activity) ────────────
        if cached_roi_boundary:
            roi_boundary = cached_roi_boundary
            roi_mask = roi_boundary['mask']
            roi_rect = roi_boundary['rect']
            if verbose: print("Using cached ROI boundary.")
        else:
            roi_mask, roi_rect = self.region_detector.find_innermost_boundary(original_img)
            roi_boundary = {"mask": roi_mask, "rect": roi_rect} if roi_rect is not None else None
            if verbose: print("Detected brand-new global ROI boundary.")

        # ── Stage 2.5: Determine Crop for this run ───────────────────────
        # Use user_region for cropping if provided, but filter results with it.
        # Note: Stage 7 uses 'roi_mask' for filtering. We override it locally
        # for filtering purposes if user_region is active.
        filter_mask = roi_mask
        if user_region is not None:
            ux1, uy1, ux2, uy2 = user_region
            ux1 = max(0, min(ux1, w-1)); ux2 = max(0, min(ux2, w-1))
            uy1 = max(0, min(uy1, h-1)); uy2 = max(0, min(uy2, h-1))
            if ux2 < ux1: ux1, ux2 = ux2, ux1
            if uy2 < uy1: uy1, uy2 = uy2, uy1

            crop_rect = [ux1, uy1, ux2 - ux1, uy2 - uy1]
            filter_mask = np.zeros((h, w), dtype=np.uint8)
            cv2.rectangle(filter_mask, (int(ux1), int(uy1)), (int(ux2), int(uy2)), 255, -1)
            print(f"Region mode: Cropping to user-defined box: {crop_rect}")
        else:
            crop_rect = roi_rect

        if crop_rect is not None:
            rx, ry, rw, rh = crop_rect
            pad = 50
            cx1 = max(0, rx - pad);  cy1 = max(0, ry - pad)
            cx2 = min(w, rx + rw + pad); cy2 = min(h, ry + rh + pad)
            crop_img    = original_img[cy1:cy2, cx1:cx2].copy()
            crop_offset = (cx1, cy1)
            print(f"Cropped for processing: {cx2-cx1}×{cy2-cy1}")
        else:
            crop_img    = original_img
            crop_offset = (0, 0)
            cx1, cy1, cx2, cy2 = 0, 0, w, h
            if verbose: print("No ROI/Region found — using full image.")

        # ── Stage 3: GD&T Detection ──────────────────────────────────────
        local_roi_rect = None
        local_roi_mask = None
        if roi_rect is not None and roi_mask is not None:
            rx, ry, rw, rh = roi_rect
            local_roi_rect = (rx - crop_offset[0], ry - crop_offset[1], rw, rh)
            local_roi_mask = roi_mask[cy1:cy2, cx1:cx2]

        if verbose: print("Running GD&T Detection...")
        if self.gdt_detector.available:
            if use_tiled_gdt:
                gdt_detections = self.gdt_detector.detect_tiled(
                    crop_img, local_roi_rect, local_roi_mask
                )
            else:
                gdt_detections = self.gdt_detector.detect_full(
                    crop_img, local_roi_rect, local_roi_mask
                )
        else:
            gdt_detections = []

        # ── INTERMEDIARY SAVE: GD&T Only ─────────────────────────────────
        if gdt_detections:
            try:
                import os
                out_dir = os.path.join(os.getcwd(), "output")
                os.makedirs(out_dir, exist_ok=True)
                out_path = os.path.join(out_dir, "intermediary_gdt.png")
                debug_img = crop_img.copy()
                for gdt in gdt_detections:
                    x1, y1, x2, y2 = map(int, gdt["bbox"])
                    cv2.rectangle(debug_img, (x1, y1), (x2, y2), (255, 0, 255), 2)
                    label = f"{gdt.get('class', '')} {gdt.get('score', 0):.2f}"
                    cv2.putText(debug_img, label, (x1, max(0, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 1)
                cv2.imwrite(out_path, debug_img)
                print(f"  [DEBUG] Saved intermediary GD&T image to {out_path}")
            except Exception as e:
                print(f"  [DEBUG] Failed to save intermediary GD&T image: {e}")

        # ── Stage 4: Mask GD&T regions for OCR ──────────────────────────
        masked_ocr_img = crop_img.copy()
        if gdt_detections:
            print(f"  Masking {len(gdt_detections)} GD&T symbols for OCR...")
            for gdt in gdt_detections:
                c_name = gdt.get("class", "").lower()
                # Keep FCF regions unmasked so OCR can read tolerance values
                if any(x in c_name for x in ["basic_dim", "datum_", "flag_note", "fcf"]):
                    continue
                x1, y1, x2, y2 = map(int, gdt["bbox"])
                cv2.rectangle(masked_ocr_img, (x1, y1), (x2, y2), (255, 255, 255), -1)

        # ── Stage 5: OCR / Vector text extraction ───────────────────────
        all_detections: list = []
        raw_result = None

        vector_extracted = False
        if isinstance(image_input, str) and image_input.lower().endswith(".pdf"):
            vector_extracted = self._extract_vector_pdf(
                image_input, page_index, gdt_detections, all_detections
            )

        if not vector_extracted:
            # Raster OCR path
            ch, cw = masked_ocr_img.shape[:2]
            ocr_scale = 1.0
            ocr_img   = masked_ocr_img

            if max(ch, cw) > max_ocr_dim:
                ocr_scale = max_ocr_dim / float(max(ch, cw))
                new_w = int(cw * ocr_scale)
                new_h = int(ch * ocr_scale)
                ocr_img = cv2.resize(
                    masked_ocr_img, (new_w, new_h), interpolation=cv2.INTER_AREA
                )
                print(f"  OCR: Down-scaling crop to {new_w}×{new_h} for performance.")

            preprocessed = self.preprocessor.preprocess(ocr_img)
            raw_result   = self.ocr_runner.run(preprocessed)

            local_dets = self.ocr_runner.parse_results(raw_result)
            inv_scale  = 1.0 / ocr_scale
            for det in local_dets:
                box, (text, score, *_) = det
                global_box = [
                    [pt[0] * inv_scale + crop_offset[0],
                     pt[1] * inv_scale + crop_offset[1]]
                    for pt in box
                ]
                all_detections.append([global_box, (text, score, *_)])

        # ── Translate GD&T to global space ───────────────────────────────
        for gdt in gdt_detections:
            gx1, gy1, gx2, gy2 = gdt["bbox"]
            gdt["bbox"] = [
                gx1 + crop_offset[0],
                gy1 + crop_offset[1],
                gx2 + crop_offset[0],
                gy2 + crop_offset[1],
            ]

        # Save a deep copy BEFORE any splitting/modification
        raw_gdt_detections = copy.deepcopy(gdt_detections)

        # ── Stage 6: Pre-parse clustering (runs on full OCR output) ─────
        # 6a: Merge diameter symbols with their nearby numbers (CLUSTERED FIRST)
        diameter_detections = [d for d in gdt_detections if "diameter" in d.get("class", "").lower()]
        gdt_detections = [d for d in gdt_detections if "diameter" not in d.get("class", "").lower()]
        
        if diameter_detections:
            print(f"  Clustering {len(diameter_detections)} diameter symbols first...")
            self.gdt_grouper.group_diameter_symbols_into_ocr(all_detections, diameter_detections)

        # 6b: Merge stacked tolerance lines with their nominals
        print("  Clustering stacked tolerances...")
        all_detections = self.gdt_grouper.group_stacked_tolerances(all_detections)

        # ── Stage 6c: View label filter ──────────────────────────────────
        # Remove view/section/scale labels from the detection pool before
        # confidence filtering.  They are informational annotations, not
        # inspectable characteristics, and must not receive balloons.
        view_label_detections = []
        clean_detections = []
        for det in all_detections:
            box, (text, score, *_) = det
            if self.gdt_grouper.is_view_label(text):
                view_label_detections.append(det)
            else:
                clean_detections.append(det)
        if view_label_detections:
            print(f"  Excluded {len(view_label_detections)} view/section labels.")
        all_detections = clean_detections

        # ── Stage 7: Confidence & ROI mask filtering ─────────────────────
        filtered_detections = ResultFilter.filter_by_confidence(
            all_detections, self.conf_thresh
        )
        # Use filter_mask (either global ROI or user selection)
        roi_detections, excluded_detections = ResultFilter.filter_by_roi_mask(
            filtered_detections, filter_mask, h, w
        )

        # ── Stage 8: GD&T character promotion ────────────────────────────
        roi_detections, _promoted = ResultFilter.promote_gdt_characters(
            roi_detections, gdt_detections
        )

        # ── Stage 9: Split diameter vs FCF detections ────────────────────
        # (Already split in Stage 6)

        # Track which OCR segments have been absorbed into higher-level structures
        # (FCFs, Diameters, Basic Dims, etc.) to prevent duplicate balloons.
        consumed_roi_indices: set = set()

        # ── Stage 9b: Diameter Grouping (Cleanup for unmerged) ─────────────
        # Any diameter symbol that wasn't merged in Stage 6 can be caught here,
        # but since they're already in all_detections as merged text, this usually finds 0.
        diam_ocr_indices, diam_dimensions = self.gdt_grouper.group_diameter_symbols(
            roi_detections, diameter_detections
        )
        if diam_ocr_indices:
            print(f"  Grouped {len(diam_ocr_indices)} supplementary OCR segments into Diameter dims.")
            consumed_roi_indices.update(diam_ocr_indices)

        # ── Stage 9a: FCF Grouping (SECOND) ───────────────────────────────────────
        # Pool for FCF: unconsumed OCR + ALL diameter symbols (potentially merged)
        combined_ocr = []
        combined_ocr_mapping = [] # Maps combined_ocr index -> (source_type, source_idx)
        
        for i, det in enumerate(roi_detections):
            if i not in consumed_roi_indices:
                combined_ocr.append(det)
                combined_ocr_mapping.append(("roi", i))
        
        for i, d in enumerate(diameter_detections):
            combined_ocr.append([d["bbox"], (d.get("class", "Ø"), d.get("score", 1.0))])
            combined_ocr_mapping.append(("diam", i))

        gdt_ocr_indices = self.gdt_grouper.group_feature_control_frames(
            combined_ocr, gdt_detections
        )
        
        consumed_diam_indices = set()
        if gdt_ocr_indices:
            print(f"  Grouped {len(gdt_ocr_indices)} segments into FCFs.")
            for idx in gdt_ocr_indices:
                src_type, src_idx = combined_ocr_mapping[idx]
                if src_type == "roi":
                    consumed_roi_indices.add(src_idx)
                else:
                    consumed_diam_indices.add(src_idx)

        # Filter diam_dimensions: remove those that were absorbed into FCFs
        filtered_diam_dimensions = []
        for i, dd in enumerate(diam_dimensions):
            # We can use bbox matching to link back if needed, but the index-based tracking
            # above for diameter_detections is more direct for the faux-OCR pool.
            # As a shortcut, just check if any diameter symbol consumed by GDT matches this dim.
            is_consumed = False
            for d_idx in consumed_diam_indices:
                cb = diameter_detections[d_idx]["bbox"]
                arr = np.array(cb).reshape(-1, 2)
                cx1, cy1 = arr.min(axis=0); cx2, cy2 = arr.max(axis=0)
                dx1, dy1, dx2, dy2 = dd["bbox"]
                if abs(cx1-dx1) < 2 and abs(cy1-dy1) < 2:
                    is_consumed = True
                    break
            if not is_consumed:
                filtered_diam_dimensions.append(dd)
        
        diam_dimensions = filtered_diam_dimensions

        # ── Stage 10: Zone & Region detection ────────────────────────────
        zone_info              = None
        regions: list          = []
        zone_marker_indices    = []

        if cached_zone_info and cached_regions:
            zone_info = cached_zone_info
            regions   = cached_regions
            print("Using cached zone and region information.")
        elif roi_rect is not None:
            print("Running global zone/region detection...")
            regions = self.region_detector.detect_regions(original_img)

            border_bbox = None
            for r in regions:
                if r.region_type == RegionType.BORDER:
                    border_bbox = r.bbox
                    break

            zone_info, zone_marker_indices = self.region_detector.detect_zones(
                original_img, all_detections, roi_rect, border_bbox, regions,
                verbose=verbose
            )

        # ── Stage 10b: Classification ─────────────────────────────────────
        classified_detections     = []
        title_block_detections    = []

        if roi_rect is not None and regions:
            classified_detections = self.region_detector.classify_detections(
                filtered_detections, regions, zone_info, zone_marker_indices, roi_rect
            )
            title_block_detections = [
                d for d in classified_detections
                if d["region_type"] == RegionType.TITLE_BLOCK
            ]

            if title_block_detections and verbose:
                print("\n" + "=" * 50)
                print("   DETECTED TITLE BLOCK INFORMATION")
                print("=" * 50)
                for d in title_block_detections:
                    print(f"  [{d['score']:.2f}] {d['text']}")
                print("=" * 50 + "\n")
            
        if verbose:
            self._has_printed_static_info = True

        # ── Stage 10c: Basic Dim / Datum / Flag Note extraction ───────────
        wrapping_symbols = [
            d for d in raw_gdt_detections
            if any(x in d.get("class", "").lower()
                   for x in ["basic_dim", "datum", "flag_note"])
        ]

        parsed_dimensions: list     = []
        # Note: consumed_roi_indices already tracking Stage 9 (FCF/Diameter)

        for w_sym in wrapping_symbols:
            wx1, wy1, wx2, wy2 = w_sym["bbox"]
            w_cx = (wx1 + wx2) / 2
            w_cy = (wy1 + wy2) / 2
            ctype = w_sym.get("class", "").lower()

            # Find OCR text with highest containment in this symbol's bounding box
            best_ocr_idx = -1
            best_iou     = 0.0
            for i, (obox, (otext, oscore)) in enumerate(roi_detections):
                if i in consumed_roi_indices:
                    continue
                opts = np.array(obox, dtype=np.float32).reshape(-1, 2)
                ox1, oy1 = opts.min(axis=0).tolist()
                ox2, oy2 = opts.max(axis=0).tolist()

                ix1 = max(wx1, ox1); iy1 = max(wy1, oy1)
                ix2 = min(wx2, ox2); iy2 = min(wy2, oy2)
                if ix2 > ix1 and iy2 > iy1:
                    inter      = (ix2-ix1) * (iy2-iy1)
                    obox_area  = max((ox2-ox1) * (oy2-oy1), 1e-6)
                    containment = inter / obox_area
                    if containment > best_iou:
                        best_iou     = containment
                        best_ocr_idx = i

            # For basic dims, find nearest FCF for linkage
            nearest_fcf = None
            if "basic_dim" in ctype:
                min_dist = float("inf")
                for fcf in raw_gdt_detections:
                    f_name = fcf.get("class", "").lower()
                    if fcf.get("is_fcf") or "fcf" in f_name:
                        fx1, fy1, fx2, fy2 = fcf["bbox"]
                        dist = (w_cx - (fx1+fx2)/2)**2 + (w_cy - (fy1+fy2)/2)**2
                        if dist < min_dist:
                            min_dist   = dist
                            nearest_fcf = fcf

            if best_ocr_idx >= 0 and best_iou > 0.30:
                obox, (otext, oscore) = roi_detections[best_ocr_idx]
                consumed_roi_indices.add(best_ocr_idx)

                assigned_type = (
                    "Datum"     if "datum"    in ctype else
                    "Flag Note" if "flag"     in ctype else
                    "Basic"
                )

                parsed = DimParser.parse(otext)
                if not parsed.get("is_dim"):
                    parsed = {
                        "type": assigned_type, "nominal": otext.strip(),
                        "min_tol": "", "max_tol": "",
                        "is_dim": True, "is_reference": False,
                        "multiplicity": 1, "has_depth": False,
                        "has_counterbore": False, "has_countersink": False,
                        "is_general_tolerance": False, "nts_flag": False,
                    }
                else:
                    parsed["type"] = assigned_type

                opts = np.array(obox, dtype=np.float32).reshape(-1, 2)
                px1, py1 = opts.min(axis=0).tolist()
                px2, py2 = opts.max(axis=0).tolist()

                # Zone lookup
                zone_label = None
                if zone_info is not None:
                    zone_label = zone_info.get_zone_label(w_cx, w_cy)

                parsed_dimensions.append({
                    "bbox": [float(px1), float(py1), float(px2), float(py2)],
                    "score": float((oscore + w_sym["score"]) / 2),
                    "text": otext.strip(),
                    "parsed": parsed,
                    "source": ctype,
                    "linked_fcf_bbox": nearest_fcf["bbox"] if nearest_fcf else None,
                    "zone": zone_label,
                })

        # ── Stage 11: Dimension Parsing ───────────────────────────────────
        for i, (box, (text, score)) in enumerate(roi_detections):
            if i in consumed_roi_indices:
                continue
            parsed = DimParser.parse(text)
            if parsed.get("is_dim"):
                pts = np.array(box, dtype=np.float32).reshape(-1, 2)
                x1, y1 = pts.min(axis=0).tolist()
                x2, y2 = pts.max(axis=0).tolist()
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                
                zone_label = None
                if zone_info is not None:
                    zone_label = zone_info.get_zone_label(cx, cy)

                parsed_dimensions.append({
                    "bbox": [float(x1), float(y1), float(x2), float(y2)],
                    "score": score,
                    "text": text.strip(),
                    "parsed": parsed,
                    "source": "ocr",
                    "zone": zone_label,
                })

        # Add diameter dimensions
        parsed_dimensions.extend(diam_dimensions)

        # ── Final Safety Sweep: Containment filtering ────────────────────
        # If any dimension is completely encompassed by another (e.g. FCF box), 
        # remove it to avoid duplicate balloons.
        final_dimensions = []
        # Combine with GDT detections that are ballooned (FCFs)
        balloon_bboxes = [d["bbox"] for d in gdt_detections if d.get("is_fcf")]

        for dim in parsed_dimensions:
            dx1, dy1, dx2, dy2 = dim["bbox"]
            is_redundant = False
            
            # Check against other (larger) balloons
            for b_bbox in balloon_bboxes:
                # b_bbox is [bx1, by1, bx2, by2] or points
                barr = np.array(b_bbox).reshape(-1, 2)
                bx1, by1 = barr.min(axis=0); bx2, by2 = barr.max(axis=0)
                
                # If dim bbox is significantly inside b_bbox
                if dx1 >= bx1 - 2 and dy1 >= by1 - 2 and dx2 <= bx2 + 2 and dy2 <= by2 + 2:
                    is_redundant = True
                    break
            
            if not is_redundant:
                final_dimensions.append(dim)
        
        parsed_dimensions = final_dimensions

        # ── Stage 12: FCF Promotion to Balloons ──────────────────────────
        # Any grouped FCF that wasn't already added (as Basic/Datum) needs a balloon.
        fcf_to_add = []
        for gdt in gdt_detections:
            if gdt.get("is_fcf"):
                c_name = gdt.get("class", "").lower()
                # Skip things already handled in Stage 10c (Basic Dims, Datums, etc.)
                if any(x in c_name for x in ["basic", "datum", "flag note"]):
                    continue
                
                # Extract the numeric tolerance value for the 'nominal' column
                # e.g. "Position ⌖ 0.05 Ⓜ A B C" -> "0.05"
                raw_text = gdt.get("class", "")
                val_match = re.search(r'(\d+\.?\d*)', raw_text)
                clean_nominal = val_match.group(1) if val_match else ""
                
                # Following user feedback: send the full class name (e.g. Perpendicularity)
                # instead of just the symbol.
                raw_full_class = gdt.get("class", "").split()
                class_name = raw_full_class[0].capitalize() if raw_full_class else "FCF"
                fcf_type = f"GDT-{class_name}"

                bx1, by1, bx2, by2 = gdt["bbox"]
                bcx, bcy = (bx1 + bx2) / 2, (by1 + by2) / 2
                zone_label = None
                if zone_info is not None:
                    zone_label = zone_info.get_zone_label(bcx, bcy)

                fcf_to_add.append({
                    "bbox": gdt["bbox"],
                    "score": gdt["score"],
                    "text": gdt["class"],
                    "source": "gdt_fcf",
                    "parsed": {
                        "type": fcf_type,
                        "nominal": clean_nominal,
                        "max_tol": "",
                        "min_tol": "",
                        "is_dim": True,
                    },
                    "zone": zone_label
                })
        
        parsed_dimensions.extend(fcf_to_add)

        return {
            "all_detections":          all_detections,
            "filtered_detections":     filtered_detections,
            "roi_detections":          roi_detections,
            "excluded_detections":     excluded_detections,
            "classified_detections":   classified_detections,
            "title_block_detections":  title_block_detections,
            "gdt_detections":          gdt_detections,
            "raw_gdt_detections":      raw_gdt_detections,
            "parsed_dimensions":       parsed_dimensions,
            "regions":                 regions,
            "zone_info":               zone_info,
            "roi_boundary":            roi_boundary,
            "original_image":          original_img,
            "raw_result":              raw_result,
        }

    # ------------------------------------------------------------------
    # Vector PDF helper
    # ------------------------------------------------------------------

    def _extract_vector_pdf(
        self,
        pdf_path: str,
        page_index: int,
        gdt_detections: list,
        out_detections: list,
    ) -> bool:
        """
        Extract text from a vector (non-rasterised) PDF page using PyMuPDF.

        Coordinates are returned in global image space (250 DPI equivalent).
        GD&T regions are excluded using GLOBAL coordinates (after Stage 3
        has translated GD&T bboxes to global space).

        :return: True if text was successfully extracted.
        """
        try:
            import fitz
            doc  = fitz.open(pdf_path)
            page = doc[page_index]
            text_dict = page.get_text("dict")
            doc.close()

            if not text_dict or "blocks" not in text_dict:
                return False

            # fitz uses 72 DPI; image_loader uses dpi=250
            scale = 250.0 / 72.0

            # Build a set of GD&T regions in global image space for fast lookup.
            # At this point gdt_detections still hold crop-relative coords
            # (global translation hasn't happened yet when this is called from run()).
            # However, _extract_vector_pdf is called BEFORE Stage "Translate GD&T",
            # so we must NOT use gdt_detections for masking here — they're crop-relative.
            # We simply skip masking and let the grouper handle it.
            # (This is safe: vector PDFs have exact coords so GD&T won't be
            #  duplicated — the grouper will absorb the compartment text.)

            count = 0
            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    text = "".join(
                        span["text"] for span in line.get("spans", [])
                    ).strip()
                    if not text:
                        continue

                    lx0, ly0, lx1, ly1 = line["bbox"]
                    x0, y0 = lx0 * scale, ly0 * scale
                    x1, y1 = lx1 * scale, ly1 * scale

                    # Extract orientation from PyMuPDF 'dir' (cos, sin)
                    # Coordinates in PDF: (1, 0) is horizontal, (0, -1) is vertical up
                    ldir = line.get("dir", (1, 0))
                    angle = 0
                    if abs(ldir[0]) > 0.9:
                        angle = 0 if ldir[0] > 0 else 180
                    elif abs(ldir[1]) > 0.9:
                        angle = 90 if ldir[1] < 0 else 270 # 90 is up (negative y)

                    box = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
                    out_detections.append([box, (text, 1.0, angle)])
                    count += 1

            print(f"  Vector PDF: extracted {count} text lines (bypassed OCR).")
            return count > 0

        except Exception as e:
            print(f"  Warning: vector PDF extraction failed: {e}")
            return False