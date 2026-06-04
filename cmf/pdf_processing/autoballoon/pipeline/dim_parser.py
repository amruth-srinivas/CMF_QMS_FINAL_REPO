"""
Dimension Parser  v4
====================
Parses OCR text into structured dimension components (nominal, tolerances, type).

v4 additions:
  - Standalone "±VALUE" (bilateral token without preceding nominal) → is_dim=False.
    Previously such tokens were parsed as {nominal: "value"} creating spurious balloons
    whenever OCR split "49 ±0.1" into two separate text lines.
  - Same-sign bilateral format "60 +0.021/+0.015" (both positive or both negative).
  - ISO 286 fit codes: H7, g6, H7/g6.
  - Thread tolerance class suffix: M8×1.25-6H.
  - Limit dimensions: 25.10/24.90.
  - Leading-decimal tolerances: +.05, -.03.
  - NTS flag.
"""

import re

_NUM = r'\d+\.?\d*'


class DimParser:

    @staticmethod
    def parse(text: str, force_type: str = None) -> dict:
        raw_t = text.strip()
        is_reference = False
        multiplicity = 1
        nts_flag = False

        # ── 0. NTS flag ──────────────────────────────────────────────────
        if re.search(r'\bNTS\b', raw_t, re.IGNORECASE):
            nts_flag = True
            raw_t = re.sub(r'\bNTS\b', '', raw_t, flags=re.IGNORECASE).strip()

        # ── 1. Reference Dimension  "( 25.00 )" ─────────────────────────
        ref_match = re.match(r"^\(\s*(.*?)\s*\)$", raw_t)
        if ref_match:
            is_reference = True
            raw_t = ref_match.group(1).strip()

        # ── 2. Multiplicity  "4X 25.00", "4×R10" ────────────────────────
        mult = re.match(r"^(\d+)\s*[xX×]\s+(.*)", raw_t) or \
               re.match(r"^(\d+)[xX×](.*)",       raw_t)
        if mult:
            multiplicity = int(mult.group(1))
            raw_t = mult.group(2).strip()

        # ── 3. Dimension type ────────────────────────────────────────────
        is_thru = bool(re.search(r'\bTHRU\b', raw_t, re.IGNORECASE))
        if is_thru:
            raw_t = re.sub(r'\bTHRU\b', '', raw_t, flags=re.IGNORECASE).strip()

        dim_type = force_type or "Linear"
        if not force_type:
            if re.search(r'M\d+\.?\d*\s*[xX×]\s*\d+\.?\d*', raw_t, re.IGNORECASE) or \
               re.search(r'\d+/\d+-\d+\s*(?:UNC|UNF|UNEF)', raw_t, re.IGNORECASE) or \
               re.search(r'\b[GR]\s+\d+/\d+', raw_t):
                dim_type = "Thread"
            elif any(s in raw_t for s in ("Ø", "ø", "⌀")) or \
                 re.search(r'\bDIA\b|\bDIAMETER\b', raw_t, re.IGNORECASE):
                dim_type = "Diameter"
            elif re.search(r'\bR\s*\d', raw_t) and \
                 not any(s in raw_t for s in ("Ø", "ø", "⌀")):
                dim_type = "Radius"
            elif re.search(r"\d\s*°|\d\s*[Dd][Ee][Gg]", raw_t):
                dim_type = "Angular"
        
        # Suffix for reference/thru
        type_suffix = ""
        if is_reference: type_suffix += " (Reference)"
        if is_thru:      type_suffix += " THRU"
        
        final_type = f"{dim_type}{type_suffix}"

        has_depth       = bool(re.search(r'[↧⬇]|DP\b|DEPTH', raw_t, re.IGNORECASE))
        has_counterbore = bool(re.search(r'[⌴]|CBORE|C/B',    raw_t, re.IGNORECASE))
        has_countersink = bool(re.search(r'[⌵]|CSINK|C/S',    raw_t, re.IGNORECASE))

        t = re.sub(r"\s+", "", raw_t)

        def _result(nominal, min_tol="", max_tol="", extra=None):
            is_gt = (min_tol == "" and max_tol == ""
                     and dim_type not in ("Basic", "Reference", "Datum", "Flag Note", "Thread")
                     and not is_reference)
            base = {
                "type": final_type, "nominal": nominal,
                "min_tol": min_tol, "max_tol": max_tol,
                "is_dim": True, "is_reference": is_reference,
                "multiplicity": multiplicity,
                "has_depth": has_depth, "has_counterbore": has_counterbore,
                "has_countersink": has_countersink,
                "is_general_tolerance": is_gt, "nts_flag": nts_flag,
            }
            if extra:
                base.update(extra)
            return base

        # ── Thread ───────────────────────────────────────────────────────
        if dim_type == "Thread":
            m = (re.search(r'(M\d+\.?\d*[xX×]\d+\.?\d*(?:-\d+[A-Za-z]+)?)',
                           raw_t, re.IGNORECASE) or
                 re.search(r'(\d+/\d+-\d+(?:UNC|UNF|UNEF|UNS)(?:-\d+[AB])?)',
                           raw_t, re.IGNORECASE) or
                 re.search(r'([GR]\s*\d+/\d+)', raw_t))
            return _result(m.group(1).strip()) if m else {"is_dim": False}

        # ── Reject standalone bilateral token "±0.1" (no nominal) ───────
        # This happens when OCR splits "49 ±0.1" into two separate lines.
        # The nominal will be merged separately by group_stacked_tolerances;
        # here we just prevent the bare "±0.1" from becoming a spurious dim.
        if re.match(r'^[±]\s*\d*\.?\d+$', raw_t):
            return {"is_dim": False}

        # Quick reject: no digits at all
        if not any(c.isdigit() for c in t):
            return {"is_dim": False}

        # ── ISO 286 fit code  "25H7/g6", "Ø25H7" ────────────────────────
        iso_fit = re.search(r'(\d*\.?\d+)\s*([A-Z][0-9]{1,2})(?:\s*/\s*([a-z][0-9]{1,2}))?', t)
        if iso_fit:
            nom   = iso_fit.group(1)
            hole  = iso_fit.group(2)
            shaft = iso_fit.group(3) if iso_fit.lastindex and iso_fit.lastindex >= 3 else None
            return _result(nom, extra={"iso_fit_code": f"{hole}/{shaft}" if shaft else hole,
                                       "is_general_tolerance": False})

        # ── Limit dimensions  "25.10/24.90" ─────────────────────────────
        limit = re.match(r'^(' + _NUM + r')/(' + _NUM + r')$', t)
        if limit:
            try:
                upper, lower = float(limit.group(1)), float(limit.group(2))
                if upper > lower:
                    nominal = str(round((upper + lower) / 2, 6))
                    half    = round((upper - lower) / 2, 6)
                    return _result(nominal, f"-{half}", f"+{half}",
                                   extra={"is_limit_dim": True,
                                          "upper_limit": str(upper),
                                          "lower_limit": str(lower)})
            except ValueError:
                pass

        # ── Bilateral symmetric  "25±0.05", "10 +/- 0.1" ────────────────
        pm = re.search(r'(' + _NUM + r')(?:[±]|\+/-)(' + _NUM + r')', t)
        if pm:
            return _result(pm.group(1), "-" + pm.group(2), "+" + pm.group(2))

        # ── Same-sign bilateral "/" separator  "60 +0.021/+0.015" ───────
        # (emitted by group_stacked_tolerances Pass-3 / Pattern-D)
        ss = re.search(r'(' + _NUM + r')\s*([+\-]\d*\.?\d+)/([+\-]\d*\.?\d+)', t)
        if ss:
            v1, v2 = ss.group(2), ss.group(3)
            if v1 and v2 and v1[0] == v2[0]:   # same sign
                try:
                    f1, f2 = float(v1), float(v2)
                    max_t = v1 if f1 >= f2 else v2
                    min_t = v2 if f1 >= f2 else v1
                    return _result(ss.group(1), min_t, max_t,
                                   extra={"is_same_sign_bilateral": True})
                except ValueError:
                    pass
            else:
                plus  = next((v for v in (v1, v2) if v.startswith("+")), "")
                minus = next((v for v in (v1, v2) if v.startswith("-")), "")
                return _result(ss.group(1), minus, plus)

        # ── Bilateral asymmetric (concatenated)  "10+0.1-0.05" ───────────
        sep = re.search(r'(' + _NUM + r')([+\-]\d*\.?\d+)([+\-]\d*\.?\d+)', t)
        if sep:
            v1, v2 = sep.group(2), sep.group(3)
            if v1[0] == v2[0]:   # same sign inline
                try:
                    f1, f2 = float(v1), float(v2)
                    max_t = v1 if f1 >= f2 else v2
                    min_t = v2 if f1 >= f2 else v1
                    return _result(sep.group(1), min_t, max_t,
                                   extra={"is_same_sign_bilateral": True})
                except ValueError:
                    pass
            plus  = next((v for v in (v1, v2) if v.startswith("+")), "")
            minus = next((v for v in (v1, v2) if v.startswith("-")), "")
            return _result(sep.group(1), minus, plus)

        # ── Single-sided tolerance  "10+0.05" / "10-0.02" ────────────────
        single = re.search(r'(' + _NUM + r')([+\-]\d*\.?\d+)', t)
        if single:
            tol = single.group(2)
            return _result(single.group(1),
                           tol if tol.startswith("-") else "",
                           tol if tol.startswith("+") else "")

        # ── Simple nominal  "25", "Ø25", "R10", "90°" ────────────────────
        # ── Note Rejection ───────────────────────────────────────────────
        # 1. Reject if line starts with obvious note-only keywords
        if re.match(r'^(?:ALL EDGES|UNLESS OTHERWISE|DO NOT SCALE|NOTES?|SHEET|MATERIAL|FINISH|TOLERANCE)\b', raw_t, re.IGNORECASE):
            return {"is_dim": False}

        # 2. Reject if too many words (typically indicates a descriptive note)
        # Dimensions are usually 1-4 words (e.g. "4X Ø 25.00 TYP")
        words = raw_t.split()
        if len(words) > 5:
            return {"is_dim": False}

        # 3. Reject if too much non-dimension text (heuristics for notes)
        # Standard dimension letters: D,R,I,A,M,E,T,E,R (DIAMETER), X (mult),
        # TYP, MAX, MIN, UNC, UNF, UNEF, H, G, DEG, REF, NTS, CZ.
        safe_letters = "DROØDIAMETER⌀øXTYPMAXMINUNCFHBSGEQ"
        alpha_count = sum(1 for c in raw_t if c.isalpha() and c.upper() not in safe_letters)
        
        digit_count = sum(c.isdigit() for c in t)
        
        # Hard alpha limit for "unsafe" letters
        if alpha_count > 3:
            return {"is_dim": False}
        
        # Alpha-to-digit ratio (detects text-heavy descriptions)
        all_alphas = sum(c.isalpha() for c in t)
        if all_alphas > 12 and all_alphas > digit_count * 3:
            return {"is_dim": False}

        num = re.search(r'(\d+\.?\d*)', t)
        if num:
            return _result(num.group(1))

        return {"is_dim": False}