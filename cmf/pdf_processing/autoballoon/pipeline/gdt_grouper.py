"""
GD&T Grouper - Simplified Implementation
========================================
Simplified grouping logic based on geometric clustering.
Acheives grouping of symbols with OCR text for FCFs and Dimension clustering.
"""

import re
import numpy as np
from typing import List, Tuple, Optional, Set
from .dim_parser import DimParser

class GDTGrouper:
    def __init__(self):
        self.dim_parser = DimParser()
        # Pre-defined thresholds for clustering
        self.CLUSTER_X = 30
        self.CLUSTER_Y_HORIZONTAL = 20
        self.CLUSTER_Y_VERTICAL = 40
        self.OVERLAP_THRESHOLD = 0.3
        
        # Regex for view labels
        self._VIEW_LABEL_RE = re.compile(
            r'^\s*(?:FRONT|REAR|BACK|LEFT|RIGHT|TOP|BOTTOM|ISO|SECTION|DETAIL|VIEW|SCALE|INDEX)\b',
            re.IGNORECASE
        )

    # ==================================================================
    # External Interface Methods (called by pipeline.py)
    # ==================================================================

    @staticmethod
    def is_view_label(text: str) -> bool:
        """Determines if a string is a standard view or section label."""
        if not text: return False
        # Simplified regex for view labels
        pattern = re.compile(
            r'^\s*(?:FRONT|REAR|BACK|LEFT|RIGHT|TOP|BOTTOM|ISO|SECTION|DETAIL|VIEW|SCALE|SEC|DET)\b',
            re.IGNORECASE
        )
        return bool(pattern.match(text.strip()))

    def group_multiline_notes(self, ocr_detections: list) -> list:
        """
        Merge consecutive text lines that belong to the same note block.
        Simplified version of multi-line merging.
        """
        if not ocr_detections:
            return ocr_detections

        # Convert to working format
        infos = []
        for i, det in enumerate(ocr_detections):
            box, (text, score, *_) = det
            pts = np.array(box, dtype=np.float32).reshape(-1, 2)
            x1, y1 = pts.min(axis=0).tolist()
            x2, y2 = pts.max(axis=0).tolist()
            infos.append({
                'i': i, 'text': text.strip(), 'score': score, 'box': box,
                'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                'h': y2 - y1, 'w': x2 - x1, 'cx': (x1+x2)/2, 'cy': (y1+y2)/2
            })

        # Sort by y-coordinate
        infos.sort(key=lambda n: n['y1'])
        
        consumed = set()
        merged_results = []
        
        for i, seed in enumerate(infos):
            if seed['i'] in consumed: continue
            
            # Feature check: Only merge if the seed looks like a note line (NOT a number/FCF)
            if not self._is_note_line(seed['text']):
                continue

            # Start a group
            group = [seed]
            consumed.add(seed['i'])
            
            curr_y2 = seed['y2']
            curr_x1, curr_x2 = seed['x1'], seed['x2']
            
            # Simple greedy search for the next line
            while True:
                found_next = False
                for j in range(i + 1, len(infos)):
                    cand = infos[j]
                    if cand['i'] in consumed: continue
                    
                    # Only merge if candidate also looks like a note line
                    if not self._is_note_line(cand['text']):
                        continue

                    # Vertical proximity: gap <= 1.2x height
                    v_gap = cand['y1'] - curr_y2
                    if 0 <= v_gap <= seed['h'] * 1.2:
                        # Horizontal overlap check (at least 50% overlap)
                        overlap_x = min(curr_x2, cand['x2']) - max(curr_x1, cand['x1'])
                        if overlap_x > min(seed['w'], cand['w']) * 0.5:
                            group.append(cand)
                            consumed.add(cand['i'])
                            curr_y2 = cand['y2']
                            curr_x1 = min(curr_x1, cand['x1'])
                            curr_x2 = max(curr_x2, cand['x2'])
                            found_next = True
                            break
                if not found_next:
                    break
            
            if len(group) == 1:
                merged_results.append(ocr_detections[seed['i']])
            else:
                # Create merged detection
                all_text = " | ".join(g['text'] for g in group)
                avg_score = sum(g['score'] for g in group) / len(group)
                
                # Bounding box of the group
                all_pts = [pt for g in group for pt in g['box']]
                arr = np.array(all_pts, dtype=np.float32).reshape(-1, 2)
                min_pt = arr.min(axis=0)
                max_pt = arr.max(axis=0)
                merged_box = [
                    [min_pt[0], min_pt[1]], [max_pt[0], min_pt[1]],
                    [max_pt[0], max_pt[1]], [min_pt[0], max_pt[1]]
                ]
                merged_results.append([merged_box, (all_text, avg_score)])
                
        # Append anything not consumed
        merged_ids = {g['i'] for res in merged_results for g in (res[0] if isinstance(res[0], list) else []) if False} # dummy
        # Clean way:
        merged_results += [ocr_detections[info['i']] for info in infos if info['i'] not in consumed]
        
        return merged_results

    def group_stacked_tolerances(self, ocr_detections: list) -> list:
        """
        Groups dimensions and tolerances that are aligned.
        New implementation:
        1. Identifies vertical stacks of tolerances based on bottom-left / top-left overlap.
        2. Requires at least one stack member to have a +/-/± prefix.
        3. Merges with a nominal value found to the left.
        """
        if not ocr_detections:
            return ocr_detections

        print(f"\n--- [DEBUG] Stacked Tolerance Grouping Start ({len(ocr_detections)} blocks) ---")

        # Convert to working format with coordinate shortcuts
        infos = []
        for i, det in enumerate(ocr_detections):
            box, text_info = det
            text, score = text_info[0], text_info[1]
            pts = np.array(box, dtype=np.float32).reshape(-1, 2)
            px1, py1 = pts.min(axis=0).tolist()
            px2, py2 = pts.max(axis=0).tolist()
            bw, bh = px2 - px1, py2 - py1
            
            # Simple orientation detector
            angle = 0 if bw >= bh else 90
            if len(text.strip()) == 1:
                angle = 0 if bh >= bw else 90

            info = {
                'i': i, 'text': text.strip(), 'score': score, 'box': box,
                'x1': px1, 'y1': py1, 'x2': px2, 'y2': py2, 'w': bw, 'h': bh,
                'angle': angle
            }
            print(f"  Input Block: '{info['text']}' @ [{int(px1)}, {int(py1)}, {int(px2)}, {int(py2)}]")
            infos.append(info)

        def is_tol(t):
            t = t.strip()
            # Check for standard tolerance prefixes
            return any(t.startswith(s) for s in ['+', '-', '±'])

        processed_indices = set()
        clustered_results = []

        # Sort top-to-bottom for predictable pair finding
        sorted_infos = sorted(infos, key=lambda x: x['y1'])

        for i, det1 in enumerate(sorted_infos):
            if det1['i'] in processed_indices: continue
            
            # Find stacked partner below
            partner = None
            merged_nominal_found = None
            for j in range(i + 1, len(sorted_infos)):
                det2 = sorted_infos[j]
                if det2['i'] in processed_indices: continue
                
                # Check alignment and overlap (User's coordinate-based suggestion)
                dx = abs(det1['x1'] - det2['x1'])
                dr = abs(det1['x2'] - det2['x2'])
                # Difference: bottom top-left y - top bottom-left y (negative means overlap)
                dy = det2['y1'] - det1['y2'] 
                
                # Case 1: Standard vertical stack (left-aligned)
                if dx < 15 and dy < 15:
                    if is_tol(det1['text']) or is_tol(det2['text']):
                        partner = det2
                        break
                
                # Case 2: Merged Nominal + Tolerance (e.g. "71 0.0" below "+0.8")
                # det2 starts further left but ends at the same horizontal position as det1.
                elif dr < 15 and det2['x1'] < det1['x1'] - 10 and dy < 15:
                    if is_tol(det1['text']):
                        # Check if text contains a space or looks like "Nominal Numeric"
                        parts = det2['text'].split()
                        if len(parts) >= 2:
                            merged_nominal_found = parts[0]
                            # Update det2 text to just the tolerance part for stacking
                            det2['text'] = " ".join(parts[1:])
                            partner = det2
                            break
            
            if partner:
                print(f"  [MATCH] Found Stack: '{det1['text']}' and '{partner['text']}' (dx={dx:.1f}, dy={dy:.1f})")
                processed_indices.add(det1['i'])
                processed_indices.add(partner['i'])
                
                # Search LEFT for a nominal value (unless already extracted from merged block)
                nominal = None
                if merged_nominal_found:
                    # Create a temporary nominal info object
                    nominal = {
                        'text': merged_nominal_found,
                        'box': partner['box'], # The box already covers the nominal
                        'score': partner['score'],
                        'i': -99 # dummy index
                    }
                    print(f"  [MATCH] Extracted merged nominal: '{merged_nominal_found}'")
                else:
                    mid_y = (det1['y1'] + partner['y2']) / 2
                    best_nom = None
                    min_dist = float('inf')
                    
                    for cand in infos:
                        if cand['i'] in [det1['i'], partner['i']]: continue
                        # Left check: stack.x1 - cand.x2
                        x_dist = det1['x1'] - cand['x2']
                        y_dist = abs((cand['y1'] + cand['y2'])/2 - mid_y)
                        
                        # Look for nominal to the left within 60px
                        if 0 <= x_dist < 60 and y_dist < 20:
                            if x_dist < min_dist:
                                min_dist = x_dist
                                best_nom = cand
                    nominal = best_nom
                
                if nominal:
                    if nominal['i'] != -99:
                        print(f"  [MATCH] Found Nominal for stack: '{nominal['text']}' (x_dist={min_dist:.1f})")
                        processed_indices.add(nominal['i'])
                    
                    # Remove the nominal from results if it was already added as standalone
                    clustered_results = [r for r in clustered_results if not (r[1][0] == nominal['text'] and r[0] == nominal['box'])]
                    
                    utxt, ltxt = det1['text'], partner['text']
                    # Standardize signs if missing
                    if not any(s in utxt for s in '+-±'): utxt = "+ " + utxt
                    if not any(s in ltxt for s in '+-±'): ltxt = "- " + ltxt
                    
                    combined_text = f"{nominal['text']} {utxt} {ltxt}"
                    avg_score = (det1['score'] + partner['score'] + nominal['score']) / 3
                    
                    # Combined Bounding Box
                    arr = np.array([p for p in det1['box']] + [p for p in partner['box']] + [p for p in nominal['box']])
                    arr = arr.reshape(-1, 2)
                    nx1, ny1 = arr.min(axis=0); nx2, ny2 = arr.max(axis=0)
                    combined_box = [[nx1, ny1], [nx2, ny1], [nx2, ny2], [nx1, ny2]]
                    
                    clustered_results.append([combined_box, (combined_text, avg_score)])
                else:
                    # Stack without nominal - merge the tolerances together anyway for parsing
                    combined_text = f"{det1['text']} {partner['text']}"
                    avg_score = (det1['score'] + partner['score']) / 2
                    arr = np.array([p for p in det1['box']] + [p for p in partner['box']])
                    arr = arr.reshape(-1, 2)
                    nx1, ny1 = arr.min(axis=0); nx2, ny2 = arr.max(axis=0)
                    combined_box = [[nx1, ny1], [nx2, ny1], [nx2, ny2], [nx1, ny2]]
                    clustered_results.append([combined_box, (combined_text, avg_score)])
            else:
                # No stack found for this element; will be added to results in the final sweep
                pass

        # Cleanup: Add anything not consumed by a stack
        for det in infos:
            if det['i'] not in processed_indices:
                clustered_results.append([det['box'], (det['text'], det['score'])])

        # print(f"--- [DEBUG] Stacked Tolerance Grouping Finish ({len(clustered_results)} results) ---")
        # for res in clustered_results:
        #     c_box = res[0]
        #     arr = np.array(c_box).reshape(-1, 2)
        #     bx1, by1 = arr.min(axis=0); bx2, by2 = arr.max(axis=0)
        #     print(f"  Result: '{res[1][0]}' @ [{int(bx1)}, {int(by1)}, {int(bx2)}, {int(by2)}]")
        # print("-" * 50 + "\n")

        return clustered_results

    @staticmethod
    def check_yolo_association(pdf_box, yolo_box, angle=0):
        """
        Determines if an OCR text box is geometrically associated with a YOLO GD&T symbol box.
        Supports both horizontal and 90-degree rotated (vertical) orientations.
        yolo_box takes a [x1, y1, x2, y2] bounding box.
        pdf_box takes a [[x1, y1], [x2, y1], [x2, y2], [x1, y2]] polygon array.
        """
        p_pts = np.array(pdf_box, dtype=np.float32).reshape(-1, 2)
        ox1, oy1 = p_pts.min(axis=0).tolist()
        ox2, oy2 = p_pts.max(axis=0).tolist()
        o_cx, o_cy = (ox1 + ox2) / 2, (oy1 + oy2) / 2

        fx1, fy1, fx2, fy2 = yolo_box
        f_cx, f_cy = (fx1 + fx2) / 2, (fy1 + fy2) / 2
        f_h = fy2 - fy1
        f_w = fx2 - fx1

        # Check association based on orientation
        if angle in [0, 180, "0", "180"]:
            # Horizontal configuration
            # Text is typically to the right of the symbol. 
            # We allow up to 45px rightwards to jump over gaps.
            dx = ox1 - fx2
            dy = abs(o_cy - f_cy)
            if -10 <= dx <= 45 and dy <= max(15, f_h * 0.8):
                return True, "horizontal"
                
        elif angle in [90, 270, "90", "270"]:
            # Vertical/rotated configuration
            dx = abs(o_cx - f_cx)
            
            # Above: text bottom edge vs symbol top edge
            dy_above = fy1 - oy2  # positive when text bottom is above symbol top
            if -10 <= dy_above <= 35 and dx <= max(15, f_w * 0.8):
                return True, "vertical"
                
        return False, None

    def group_feature_control_frames(self, ocr_detections: list, gdt_detections: list, max_dist_ratio: float = 5.0) -> Set[int]:
        """
        Groups GD&T symbols with OCR values using the check_yolo_association logic.
        Now correctly processes both horizontal and vertically-oriented dimensions.
        """
        if not gdt_detections or not ocr_detections:
            return set()

        merged_indices = set()
        
        # Prepare normalized GD&T tracking
        normalized_yolo = []
        for i, gdt in enumerate(gdt_detections):
            normalized_yolo.append({
                'orig_index': i,
                'class_name': gdt.get("class", ""),
                'merged_box': list(gdt["bbox"]), # This bounding box will expand horizontally/vertically as text is attached
                'original': gdt,
                'associated_text': []
            })
            
        # Helper sequence counter to ensure OCR insertion order stability
        for seq, det in enumerate(ocr_detections):
            box, text_info = det
            text_val = text_info[0]

            angle = text_info[2] if len(text_info) > 2 else 0

            if angle == 0:
                pts = np.array(box, dtype=np.float32).reshape(-1, 2)
                bw = pts[:, 0].max() - pts[:, 0].min()
                bh = pts[:, 1].max() - pts[:, 1].min()
                if bh > bw * 1.5:
                    angle = 90

            # Note Rejection: don't absorb descriptive drawings notes
            if self._is_note_line(text_val):
                continue
            
            # Find associated YOLO detection by proximity
            associated_yolo = None
            association_type = None

            # Sort YOLO candidates by proximity to text so we group with the closest matching FCF boundary
            pdf_pts = np.array(box, dtype=np.float32).reshape(-1, 2)
            ox1, oy1 = pdf_pts.min(axis=0).tolist()
            ox2, oy2 = pdf_pts.max(axis=0).tolist()
            o_cx = (ox1 + ox2) / 2

            def dist_to_yolo(yolo_det):
                fx1, fy1, fx2, fy2 = yolo_det['merged_box']
                if angle in [90, 270, "90", "270"]:
                    f_cx = (fx1 + fx2) / 2
                    return (o_cx - f_cx)**2 + (fy1 - oy2)**2   # top edge proximity
                else:
                    return (ox1 - fx2)**2 + (oy1 - fy1)**2      # right edge proximity

            sorted_yolo = sorted(normalized_yolo, key=dist_to_yolo)

            for yolo_det in sorted_yolo:
                is_assoc, assoc_type = self.check_yolo_association(
                    box, 
                    yolo_det['merged_box'],
                    angle
                )
                if is_assoc:
                    associated_yolo = yolo_det
                    association_type = assoc_type
                    break

            if associated_yolo:
                merged_indices.add(seq)
                associated_yolo['associated_text'].append({
                    'text': text_val,
                    'box': box,
                    'angle': angle
                })
                
                # Expand YOLO boundary to swallow this text
                # We need box as [ox1, oy1, ox2, oy2] array for _create_merged_box
                ox2, oy2 = pdf_pts.max(axis=0).tolist()
                b1 = [ox1, oy1, ox2, oy2]
                associated_yolo['merged_box'] = self._create_merged_box(b1, associated_yolo['merged_box'])
                # Flatten back to 1D since _create_merged_box returns a polygon points array
                pts_m = np.array(associated_yolo['merged_box'], dtype=np.float32).reshape(-1, 2)
                mx1, my1 = pts_m.min(axis=0).tolist()
                mx2, my2 = pts_m.max(axis=0).tolist()
                associated_yolo['merged_box'] = [mx1, my1, mx2, my2]

        # Finalize the grouped FCFs
        for yolo_det in normalized_yolo:
            gdt_obj = yolo_det['original']
            assoc_texts = yolo_det['associated_text']
            
            if assoc_texts:
                # Sort text blocks spatially based on their overall orientation
                angles = [t['angle'] for t in assoc_texts]
                common_angle = max(set(angles), key=angles.count) if angles else 0
                
                if common_angle in [0, 180, "0", "180"]:
                    # Sort left-to-right
                    assoc_texts.sort(key=lambda t: np.array(t['box'], dtype=np.float32).reshape(-1, 2).min(axis=0)[0])
                else:
                    # Sort top-to-bottom
                    assoc_texts.sort(key=lambda t: np.array(t['box'], dtype=np.float32).reshape(-1, 2).min(axis=0)[1])
            
                # Extract numerical value and important symbols (diameter, modifiers)
                raw_ocr_text = " ".join(t['text'] for t in assoc_texts)
                combined_text = yolo_det['class_name'] + " " + raw_ocr_text
                
                diam_prefix = "Ø " if any(s in raw_ocr_text for s in ("Ø", "ø", "⌀", "Ð")) else ""
                
                # Capture material condition modifiers (Ⓜ, Ⓛ, etc.)
                modifiers = "".join(s for s in raw_ocr_text if s in ("Ⓜ", "Ⓛ", "Ⓟ", "Ⓕ", "Ⓣ", "Ⓢ", "Ⓤ", "Ⓓ", "Ⓔ", "Ⓘ", "Ⓝ"))
                if not modifiers:
                    # Fallback for plain text modifiers like (M), (L) or just M, L
                    mod_match = re.search(r'\b([MLS])\b', raw_ocr_text)
                    if mod_match: modifiers = mod_match.group(1)
                
                val_match = re.search(r'(\d+\.?\d*)', raw_ocr_text)
                value = val_match.group(1) if val_match else ""
                gdt_obj["nominal_value"] = f"{diam_prefix}{value} {modifiers}".strip()
            else:
                combined_text = yolo_det['class_name']
                gdt_obj["nominal_value"] = ""
                
            gdt_obj["class"] = combined_text.strip()
            
            # Robust case-insensitive symbol mapping
            symbol_map = {
                "position": "⌖", "symmetry": "⌰", "perpendicularity": "⏊",
                "parallelism": "⫽", "circular runnot": "↗", "circularity": "○",
                "roundness": "○", "cylindricity": "⌭", "flatness": "⏥", 
                "straightness": "⏤", "surface profile": "⌓", "line profile": "⌢", 
                "angularity": "∠", "concentricity": "◎", "total runout": "⌰",
                "circular": "↗"
            }
            # print(yolo_det["class_name"])
            cls_lookup = yolo_det['class_name'].strip().lower()
            gdt_obj["symbol"] = symbol_map.get(cls_lookup, "")
            # print(gdt_obj["symbol"], "\n\n")
            
            fb = yolo_det['merged_box']
            gdt_obj["bbox"] = [fb[0]-5, fb[1]-2, fb[2]+5, fb[3]+2]
            gdt_obj["is_fcf"] = True

        return merged_indices

    def group_diameter_symbols_into_ocr(self, ocr_detections: list, diameter_detections: list) -> Set[int]:
        """
        Groups diameter symbol detections with nearby OCR text by updating ocr_detections in-place.
        Returns the set of indices of diameter_detections that were successfully merged.
        """
        if not diameter_detections or not ocr_detections:
            return set()

        merged_diam_indices = set()

        for d_idx, diam in enumerate(diameter_detections):
            d_x1, d_y1, d_x2, d_y2 = diam["bbox"]
            d_cx, d_cy = (d_x1 + d_x2) / 2, (d_y1 + d_y2) / 2
            
            best_ocr_idx = -1
            min_dist = float('inf')
            
            for i, det in enumerate(ocr_detections):
                box, text_info = det
                text, score = text_info[0], text_info[1]
                angle = text_info[2] if len(text_info) > 2 else 0

                # Skip if already merged or has symbol
                if text.startswith('Ø') or text.startswith('ø'): continue
                
                pts = np.array(box).reshape(-1, 2)
                ox1, oy1 = pts.min(axis=0); ox2, oy2 = pts.max(axis=0)
                o_cx, o_cy = (ox1 + ox2) / 2, (oy1 + oy2) / 2

                if angle == 0:
                    bw, bh = ox2 - ox1, oy2 - oy1
                    if bh > bw * 1.5:
                        angle = 90

                if angle in [0, 180, "0", "180"]:
                    # Text is on right
                    if ox1 > d_x1 - 15: # allow slight overlap
                        x_dist = max(0, ox1 - d_x2)
                        y_dist = abs(o_cy - d_cy)
                        if x_dist <= 40 and y_dist <= 25:
                            if x_dist < min_dist:
                                min_dist = x_dist
                                best_ocr_idx = i
                elif angle in [90, 270, "90", "270"]:
                    # Text is above
                    dy_above = d_y1 - oy2
                    dx = abs(o_cx - d_cx)
                    if -10 <= dy_above <= 35 and dx <= 25:
                        if dy_above < min_dist:
                            min_dist = dy_above
                            best_ocr_idx = i

            if best_ocr_idx >= 0:
                merged_diam_indices.add(d_idx)
                box, (text, score, *extras) = ocr_detections[best_ocr_idx]
                
                # Combine text
                full_text = "Ø " + text
                
                # Merge boxes
                pts = np.array(box).reshape(-1, 2)
                ox1, oy1 = pts.min(axis=0); ox2, oy2 = pts.max(axis=0)
                nx1 = min(d_x1, ox1); ny1 = min(d_y1, oy1)
                nx2 = max(d_x2, ox2); ny2 = max(d_y2, oy2)
                merged_box = [[nx1, ny1], [nx2, ny1], [nx2, ny2], [nx1, ny2]]
                
                ocr_detections[best_ocr_idx] = [merged_box, (full_text, score, *extras)]

        return merged_diam_indices

    def group_diameter_symbols(self, ocr_detections: list, diameter_detections: list, max_dist_ratio: float = 5.0) -> Tuple[Set[int], List[dict]]:
        """
        Groups diameter symbol detections with nearby OCR text.
        Based on check_yolo_association horizontal logic.
        """
        if not diameter_detections or not ocr_detections:
            return set(), []

        merged_indices = set()
        parsed_dims = []

        for diam in diameter_detections:
            d_x1, d_y1, d_x2, d_y2 = diam["bbox"]
            d_cx, d_cy = (d_x1 + d_x2) / 2, (d_y1 + d_y2) / 2
            
            best_candidate = None
            min_dist = float('inf')
            
            for i, det in enumerate(ocr_detections):
                if i in merged_indices: continue
                box, text_info = det
                text, score = text_info[0], text_info[1]
                angle = text_info[2] if len(text_info) > 2 else 0

                pts = np.array(box, dtype=np.float32).reshape(-1, 2)
                ox1, oy1 = pts.min(axis=0).tolist()
                ox2, oy2 = pts.max(axis=0).tolist()
                o_cx, o_cy = (ox1 + ox2) / 2, (oy1 + oy2) / 2

                if angle == 0:
                    bw, bh = ox2 - ox1, oy2 - oy1
                    if bh > bw * 1.5:
                        angle = 90

                if angle in [0, 180, "0", "180"]:
                    # Text is on right
                    if ox1 > d_x1 - 10: # allow slight overlap
                        x_dist = max(0, ox1 - d_x2)
                        y_dist = abs(o_cy - d_cy)
                        if x_dist <= 30 and y_dist <= self.CLUSTER_Y_HORIZONTAL:
                            if x_dist < min_dist:
                                min_dist = x_dist
                                best_candidate = {
                                    'index': i, 'text': text, 'score': score, 
                                    'box': box, 'bbox': [ox1, oy1, ox2, oy2]
                                }
                elif angle in [90, 270, "90", "270"]:
                    # Text is above
                    dy_above = d_y1 - oy2
                    dx = abs(o_cx - d_cx)
                    if -10 <= dy_above <= 35 and dx <= 25:
                        if dy_above < min_dist:
                            min_dist = dy_above
                            best_candidate = {
                                'index': i, 'text': text, 'score': score, 
                                'box': box, 'bbox': [ox1, oy1, ox2, oy2]
                            }

            if best_candidate:
                merged_indices.add(best_candidate['index'])
                
                # Combine text
                full_text = "Ø " + best_candidate['text']
                merged_box = self._create_merged_box(best_candidate['bbox'], diam["bbox"])
                
                # Prepare parsed result using the correct DimParser.parse method
                p_res = self.dim_parser.parse(best_candidate['text'])
                if p_res.get("is_dim"):
                    nominal   = p_res.get("nominal", "")
                    upper_tol = p_res.get("max_tol", "")
                    lower_tol = p_res.get("min_tol", "")
                    dim_type  = "Diameter"  # Force Diameter as requested
                    
                    # Flatten bbox for consistent downstream handling
                    arr = np.array(merged_box, dtype=np.float32).reshape(-1, 2)
                    bx1, by1 = arr.min(axis=0).tolist()
                    bx2, by2 = arr.max(axis=0).tolist()
                    flattened_bbox = [bx1, by1, bx2, by2]
                    
                    parsed_dims.append({
                        "bbox": flattened_bbox,
                        "score": float(best_candidate['score']),
                        "text": full_text,
                        "source": "diameter",
                        "parsed": {
                            "type": dim_type,
                            "nominal": nominal,
                            "max_tol": upper_tol,
                            "min_tol": lower_tol,
                            "is_dim": True,
                            "is_reference": False,
                            "multiplicity": 1,
                            "has_depth": False,
                            "has_counterbore": False,
                            "has_countersink": False,
                            "is_general_tolerance": False,
                            "nts_flag": False
                        }
                    })
                
                # Update the diameter detection itself to show it's grouped
                diam["class"] = full_text
                diam["bbox"] = merged_box

        return merged_indices, parsed_dims

    def _create_merged_box(self, box1_coords, box2_coords):
        """Helper to merge two [x1, y1, x2, y2] bounding boxes."""
        x1 = min(box1_coords[0], box2_coords[0])
        y1 = min(box1_coords[1], box2_coords[1])
        x2 = max(box1_coords[2], box2_coords[2])
        y2 = max(box1_coords[3], box2_coords[3])
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    @staticmethod
    def _is_note_line(text: str) -> bool:
        """Heuristic to identify if a line is part of a general note."""
        t = text.strip()
        if not t: return False
        
        # Pure numbers or simple dimensions are NOT notes
        if re.match(r'^[ØøÐ⌀Rr]?\s*\d+\.?\d*[A-Z]*\s*°?$', t):
            return False
            
        # If it has many letters, it's likely a note
        letters = sum(c.isalpha() for c in t)
        if letters > 3:
            # But exclude if it contains GD&T symbols which suggest FCF/GDT
            gdt_syms = ['⌖','⌰','⏊','⫽','↗','⌢','⏤','⏥','⌭','◎','⌿','∠','○','⌓']
            if not any(sym in t for sym in gdt_syms):
                return True
        return False