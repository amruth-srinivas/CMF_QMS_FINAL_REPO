# """
# Dimension parsing module to extract nominal values, tolerances, and dimension types.
# This module implements dimension parsing logic similar to the PyQt5 application.
# """
# import re
# import logging
# from typing import Tuple, Optional

# logger = logging.getLogger(__name__)


# class DimensionParser:
#     """Parse dimension text to extract nominal values, tolerances, and dimension types."""
    
#     @staticmethod
#     def is_dimensional_value(text: str) -> bool:
#         """Check if text likely represents a dimensional value"""
#         text_original = text.strip()
#         text = text_original.lower()

#         # Skip single + or - characters
#         if text in ['+', '-']:
#             return False

#         # Check for chamfer text (CHAMFER keyword or pattern with X and degrees)
#         if 'chamfer' in text or (re.search(r'\d+.*x.*\d+.*°', text_original, re.IGNORECASE)):
#             return True

#         # Check if it's a tolerance value starting with + or -
#         if text.startswith('+') or text.startswith('-'):
#             try:
#                 float(text.replace(',', '.'))
#                 return True
#             except ValueError:
#                 return False

#         # Remove common prefixes for dimension check (but keep original for later checks)
#         text_without_prefix = text
#         for prefix in ['ø', '∅']:
#             text_without_prefix = text_without_prefix.replace(prefix, '')
        
#         # Check for radius/thread with prefix (R10, M8, etc.)
#         if text_original.startswith('R') or text_original.startswith('r'):
#             # Check if followed by a number
#             if re.search(r'^[Rr]\s*\d+\.?\d*', text_original):
#                 return True
#         if re.search(r'^M\d{1,2}', text_original, re.IGNORECASE):
#             return True

#         if '°' in text:
#             # Check for angular dimensions with tolerances like "120° ±0.02°TYP" or "120°±0.02°TYP"
#             # Pattern allows optional spaces around ±
#             angular_with_tol_pattern = r'\d+\.?\d*\s*°\s*±\s*\d+\.?\d*\s*°'
#             if re.search(angular_with_tol_pattern, text_original, re.IGNORECASE):
#                 return True
#             # Check for simple angular dimension like "120°"
#             text_no_deg = text.replace('°', '')
#             try:
#                 float(text_no_deg)
#                 return True
#             except ValueError:
#                 # Check if it contains X pattern (like chamfer)
#                 if 'x' in text.lower():
#                     return True
#                 # Check if it's a number followed by degree symbol and optional text
#                 if re.match(r'^\d+\.?\d*\s*°', text_original):
#                     return True
#                 return False

#         # More lenient pattern - check if text contains a number (with optional decimal)
#         # This handles cases where text might have extra whitespace or characters
#         dimensional_pattern = r'^-?\d*\.?\d+$|^-?\d+,\d+$'
#         tolerance_pattern = r'±?\d*\.?\d+|\+\d*\.?\d+/-\d*\.?\d+'
        
#         # Clean text for matching
#         text_clean = text_without_prefix.replace(',', '.').strip()
        
#         # Check for pure numeric patterns (exact match)
#         if re.match(dimensional_pattern, text_clean) or re.match(tolerance_pattern, text_clean):
#             return True
        
#         # Simple number check - if it's just a number (with optional decimal and whitespace), it's likely a dimension
#         simple_number_pattern = r'^[\s]*[+-]?\d+\.?\d*[\s]*$'
#         if re.match(simple_number_pattern, text_clean):
#             return True
        
#         # More lenient: check if text contains a number pattern (for cases with extra chars)
#         # Look for patterns like: number, number with decimal, number with tolerance
#         number_pattern = r'\d+\.?\d*'  # Matches numbers like 10, 10.5, .5
#         has_number = bool(re.search(number_pattern, text_original))
        
#         # If it has a number and is relatively short (likely a dimension, not a sentence)
#         if has_number and len(text_original.strip()) < 50:
#             # Additional check: does it look like a dimension?
#             # Check for common dimension indicators
#             dimension_indicators = ['±', '+', '-', '°', 'ø', 'r', 'm', 'x', '×', 'typ', 'ref', 'thru']
#             has_indicator = any(ind in text_original.lower() for ind in dimension_indicators)
            
#             # If it has a number and either has an indicator or is just a number/tolerance
#             if has_indicator or re.match(r'^[\s]*[+-]?\d+\.?\d*[\s]*$', text_clean):
#                 return True
        
#         return False

#     @staticmethod
#     def determine_dimension_type(text: str, nominal_value: str) -> str:
#         """Determine the dimension type based on the text and nominal value"""
#         text_lower = text.lower()
        
#         # Check for Chamfer first (most specific)
#         if 'chamfer' in text_lower:
#             return "Chamfer"
        
#         # Check for chamfer pattern: number X number followed by degree symbol
#         # Pattern like "0.5 X 45°" or "0.5X45°"
#         if re.search(r'\d+\.?\d*\s*[xX×]\s*\d+\.?\d*\s*°', text, re.IGNORECASE):
#             return "Chamfer"
        
#         # Check for X pattern with degrees (common chamfer notation)
#         if 'x' in text_lower and '°' in text:
#             return "Chamfer"

#         # Check for Radius
#         if text.startswith('R') or text.startswith('r'):
#             return "Radius"

#         # Check for Reference dimensions (in parentheses)
#         if text.startswith("(") and text.endswith(")"):
#             inner_text = text[1:-1].strip()
#             if inner_text.startswith('R') or inner_text.startswith('r'):
#                 return "Radius-Reference"
#             elif '°' in inner_text:
#                 return "Angular-Reference"
#             else:
#                 return "Length-Reference"

#         # Check for Angular dimensions (with or without tolerances)
#         if '°' in text:
#             # Check if it's a chamfer pattern first (number X number °)
#             if not re.search(r'\d+\.?\d*\s*[xX×]\s*\d+\.?\d*\s*°', text, re.IGNORECASE):
#                 return "Angular"

#         # Check for Thread dimensions
#         match = re.search(r'M(\d{1,2})', text)
#         if match:
#             return "Thread"

#         # Default to Length
#         return "Length"

#     @staticmethod
#     def parse_dimension(text: str) -> Tuple[str, str, str, str]:
#         """
#         Parse dimension text to extract nominal value, tolerances, and type.
        
#         Args:
#             text: The dimension text to parse
            
#         Returns:
#             Tuple of (dim_type, upper_tol, lower_tol, nominal_value)
#         """
#         try:
#             text_original = text.strip()
#             text = text_original
#             nominal_value = ""
#             upper_tol = ""
#             lower_tol = ""
#             dim_type = "Length"  # default type

#             # Check for chamfer first
#             if 'chamfer' in text.lower() or re.search(r'\d+\.?\d*\s*[xX×]\s*\d+\.?\d*\s*°', text, re.IGNORECASE):
#                 # Extract chamfer pattern like "0.5 X 45°" or "0.5X45°" or "0.5 X 45° TYP."
#                 chamfer_match = re.search(r'(\d+\.?\d*)\s*[xX×]\s*(\d+\.?\d*)\s*°', text, re.IGNORECASE)
#                 if chamfer_match:
#                     length_part = chamfer_match.group(1)
#                     angle_part = chamfer_match.group(2)
#                     # Check if there's additional text after the chamfer pattern (like TYP.)
#                     after_match = chamfer_match.end()
#                     suffix = text[after_match:].strip() if after_match < len(text) else ""
#                     if suffix:
#                         nominal_value = f"{length_part} X {angle_part}° {suffix}"
#                     else:
#                         nominal_value = f"{length_part} X {angle_part}°"
#                     dim_type = "Chamfer"
#                     return dim_type, "0", "0", nominal_value
#                 # If no match but has chamfer keyword, keep the text
#                 if 'chamfer' in text.lower():
#                     nominal_value = text_original
#                     dim_type = "Chamfer"
#                     return dim_type, "0", "0", nominal_value

#             # Remove spaces for other parsing
#             text_no_spaces = ''.join(text.split())

#             # Handle pure tolerance values
#             if text_no_spaces.startswith('+'):
#                 nominal_value = ""
#                 upper_tol = text_original  # Keep the entire text including +
#                 lower_tol = "0"
#                 dim_type = "Tolerance"
#                 return dim_type, upper_tol, lower_tol, nominal_value

#             # Handle THRU dimensions
#             if "THRU" in text.upper():
#                 numeric_part = text.upper().split("THRU")[0].strip()
#                 return "THRU", "0", "0", numeric_part

#             if '±' in text:
#                 parts = text.split('±')
#                 nominal_value = parts[0].strip()
#                 if len(parts) > 1:
#                     # Extract tolerance value (may include degree symbol and TYP suffix)
#                     tol_part = parts[1].strip()
#                     # Match tolerance pattern: number followed optionally by degree symbol
#                     # Pattern: optional number, then optional degree symbol, then optional text like TYP
#                     tol_match = re.search(r'(\d+\.?\d*)\s*(°)?', tol_part)
#                     if tol_match:
#                         tol_value = tol_match.group(1)
#                         tol_degree = tol_match.group(2) if tol_match.group(2) else ''
#                         # Check if tolerance should have degree symbol (if nominal has it)
#                         if '°' in nominal_value or tol_degree:
#                             upper_tol = f"+{tol_value}°"
#                             lower_tol = f"-{tol_value}°"
#                         else:
#                             upper_tol = f"+{tol_value}"
#                             lower_tol = f"-{tol_value}"
#                     else:
#                         # Fallback: use first word/part
#                         tol = tol_part.split()[0] if tol_part.split() else tol_part
#                         upper_tol = f"+{tol}"
#                         lower_tol = f"-{tol}"

#             elif '+' in text:
#                 plus_index = text.find('+')
#                 nominal_value = text[:plus_index].strip()
#                 tolerance = text[plus_index+1:].strip()
#                 upper_tol = f"+{tolerance}"
#                 lower_tol = f"-{tolerance}"

#             else:
#                 nominal_value = text_original
#                 upper_tol = "0"
#                 lower_tol = "0"

#             # Special handling for reference dimensions
#             if text_original.startswith("(") and text_original.endswith(")"):
#                 nominal_value = text_original  # Keep the full text including parentheses
#                 upper_tol = ""
#                 lower_tol = ""

#             # Determine dimension type (use original text for better pattern matching)
#             dim_type = DimensionParser.determine_dimension_type(text_original, nominal_value)

#             return dim_type, upper_tol, lower_tol, nominal_value

#         except Exception as e:
#             logger.error(f"Error parsing dimension: {str(e)}")
#             return "Length", "0", "0", text


"""
Dimension parsing module to extract nominal values, tolerances, and dimension types.
This module implements dimension parsing logic similar to the PyQt5 application.
"""
import re
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class DimensionParser:
    """Parse dimension text to extract nominal values, tolerances, and dimension types."""
    
    @staticmethod
    def is_dimensional_value(text: str) -> bool:
        """Check if text likely represents a dimensional value"""
        text_original = text.strip()
        text = text_original.lower()

        # Skip single + or - characters
        if text in ['+', '-']:
            return False

        # Check for chamfer text (numeric chamfer pattern with X and degrees).
        # We deliberately avoid treating a standalone 'CHAMFER' word (with no
        # numbers) as a dimensional value; only patterns that actually contain
        # numeric chamfer data should be recognized here.
        chamfer_pattern = re.search(r'\d+.*x.*\d+.*°', text_original, re.IGNORECASE)
        if chamfer_pattern:
            return True

        # Check if it's a tolerance value starting with + or -
        if text.startswith('+') or text.startswith('-'):
            try:
                float(text.replace(',', '.'))
                return True
            except ValueError:
                return False

        # Remove common prefixes for dimension check (but keep original for later checks)
        text_without_prefix = text
        for prefix in ['ø', 'Ø', '∅', '⌀']:
            text_without_prefix = text_without_prefix.replace(prefix, '')
        
        # Check for radius/thread with prefix (R10, M8, etc.)
        if text_original.startswith('R') or text_original.startswith('r'):
            # Check if followed by a number
            if re.search(r'^[Rr]\s*\d+\.?\d*', text_original):
                return True
        if re.search(r'^M\d{1,2}', text_original, re.IGNORECASE):
            return True

        if '°' in text:
            # Check for angular dimensions with tolerances like "120° ±0.02°TYP" or "120°±0.02°TYP"
            # Pattern allows optional spaces around ±
            angular_with_tol_pattern = r'\d+\.?\d*\s*°\s*±\s*\d+\.?\d*\s*°'
            if re.search(angular_with_tol_pattern, text_original, re.IGNORECASE):
                return True
            # Check for simple angular dimension like "120°"
            text_no_deg = text.replace('°', '')
            try:
                float(text_no_deg)
                return True
            except ValueError:
                # Check if it contains X pattern (like chamfer)
                if 'x' in text.lower():
                    return True
                # Check if it's a number followed by degree symbol and optional text
                if re.match(r'^\d+\.?\d*\s*°', text_original):
                    return True
                return False

        # More lenient pattern - check if text contains a number (with optional decimal)
        # This handles cases where text might have extra whitespace or characters
        dimensional_pattern = r'^-?\d*\.?\d+$|^-?\d+,\d+$'
        tolerance_pattern = r'±?\d*\.?\d+|\+\d*\.?\d+/-\d*\.?\d+'
        
        # Clean text for matching
        text_clean = text_without_prefix.replace(',', '.').strip()
        
        # Check for pure numeric patterns (exact match)
        if re.match(dimensional_pattern, text_clean) or re.match(tolerance_pattern, text_clean):
            return True
        
        # Simple number check - if it's just a number (with optional decimal and whitespace), it's likely a dimension
        simple_number_pattern = r'^[\s]*[+-]?\d+\.?\d*[\s]*$'
        if re.match(simple_number_pattern, text_clean):
            return True
        
        # More lenient: check if text contains a number pattern (for cases with extra chars)
        # Look for patterns like: number, number with decimal, number with tolerance
        number_pattern = r'\d+\.?\d*'  # Matches numbers like 10, 10.5, .5
        has_number = bool(re.search(number_pattern, text_original))
        
        # If it has a number and is relatively short (likely a dimension, not a sentence)
        if has_number and len(text_original.strip()) < 50:
            # Additional check: does it look like a dimension?
            # Check for common dimension indicators (incl. 'dia' for diameter callouts)
            dimension_indicators = ['±', '+', '-', '°', 'ø', 'r', 'm', 'x', '×', 'typ', 'ref', 'thru', 'dia']
            has_indicator = any(ind in text_original.lower() for ind in dimension_indicators)
            
            # If it has a number and either has an indicator or is just a number/tolerance
            if has_indicator or re.match(r'^[\s]*[+-]?\d+\.?\d*[\s]*$', text_clean):
                return True
        
        return False

    @staticmethod
    def determine_dimension_type(text: str, nominal_value: str) -> str:
        """Determine the dimension type based on the text and nominal value"""
        text_lower = text.lower()
        
        # Check for Chamfer first (most specific)
        if 'chamfer' in text_lower:
            return "Chamfer"
        
        # Check for chamfer pattern: number X number followed by degree symbol
        # Pattern like "0.5 X 45°" or "0.5X45°"
        if re.search(r'\d+\.?\d*\s*[xX×]\s*\d+\.?\d*\s*°', text, re.IGNORECASE):
            return "Chamfer"
        
        # Check for X pattern with degrees (common chamfer notation)
        if 'x' in text_lower and '°' in text:
            return "Chamfer"

        # Check for Diameter (symbols: ø, Ø, ∅, ⌀ - at start or anywhere; or "DIA"/"diameter" in text)
        text_stripped = text.strip()
        diameter_symbols_start = ('ø', 'Ø', '∅', '⌀')
        diameter_symbols_any = ('ø', 'Ø', '∅', '⌀')
        if any(text_stripped.startswith(s) for s in diameter_symbols_start):
            return "Diameter"
        if any(s in text for s in diameter_symbols_any):
            return "Diameter"
        # Spelled-out diameter: "83 DIA ±0.15", "DIA 10", "10 diameter"
        if re.search(r'\bdia\.?\b', text_lower) or 'diameter' in text_lower:
            return "Diameter"

        # Check for Radius
        if text.startswith('R') or text.startswith('r'):
            return "Radius"

        # Check for Reference dimensions (in parentheses)
        if text.startswith("(") and text.endswith(")"):
            inner_text = text[1:-1].strip()
            if any(inner_text.startswith(s) for s in ('ø', 'Ø', '∅', '⌀')):
                return "Diameter-Reference"
            if inner_text.startswith('R') or inner_text.startswith('r'):
                return "Radius-Reference"
            elif '°' in inner_text:
                return "Angular-Reference"
            else:
                return "Length-Reference"

        # Check for Angular dimensions (with or without tolerances)
        if '°' in text:
            # Check if it's a chamfer pattern first (number X number °)
            if not re.search(r'\d+\.?\d*\s*[xX×]\s*\d+\.?\d*\s*°', text, re.IGNORECASE):
                return "Angular"

        # Check for Thread dimensions
        match = re.search(r'M(\d{1,2})', text)
        if match:
            return "Thread"

        # Default to Length
        return "Length"

    @staticmethod
    def parse_dimension(text: str) -> Tuple[str, str, str, str]:
        """
        Parse dimension text to extract nominal value, tolerances, and type.
        
        Args:
            text: The dimension text to parse
            
        Returns:
            Tuple of (dim_type, upper_tol, lower_tol, nominal_value)
        """
        try:
            text_original = text.strip()
            text = text_original
            nominal_value = ""
            upper_tol = ""
            lower_tol = ""
            dim_type = "Length"  # default type

            # Check for chamfer first. We only treat it as a chamfer
            # dimension if there is either an explicit numeric chamfer
            # pattern (e.g. "0.5 X 45°") or the word CHAMFER appears
            # together with at least one digit. This avoids creating a
            # separate dimension row for a standalone "CHAMFER" label.
            chamfer_numeric_pattern = re.search(r'\d+\.?\d*\s*[xX×]\s*\d+\.?\d*\s*°', text, re.IGNORECASE)
            has_chamfer_word_with_number = 'chamfer' in text.lower() and re.search(r'\d', text)
            if chamfer_numeric_pattern or has_chamfer_word_with_number:
                # Extract chamfer pattern like "0.5 X 45°" or "0.5X45°" or "0.5 X 45° TYP."
                chamfer_match = re.search(r'(\d+\.?\d*)\s*[xX×]\s*(\d+\.?\d*)\s*°', text, re.IGNORECASE)
                if chamfer_match:
                    length_part = chamfer_match.group(1)
                    angle_part = chamfer_match.group(2)
                    # Check if there's additional text after the chamfer pattern (like TYP.)
                    after_match = chamfer_match.end()
                    suffix = text[after_match:].strip() if after_match < len(text) else ""
                    if suffix:
                        nominal_value = f"{length_part} X {angle_part}° {suffix}"
                    else:
                        nominal_value = f"{length_part} X {angle_part}°"
                    dim_type = "Chamfer"
                    return dim_type, "0", "0", nominal_value
                # If no match but has chamfer keyword, keep the text
                if 'chamfer' in text.lower():
                    nominal_value = text_original
                    dim_type = "Chamfer"
                    return dim_type, "0", "0", nominal_value

            # Special case: combined nominal + two separate +tolerances, e.g.:
            #   "+0.5 40 +0.2"  or  "40 +0.2 +0.5"
            # In these cases we want:
            #   nominal = 40
            #   upper_tol = +0.2  (value next to nominal)
            #   lower_tol = +0.5  (value on separate line / other +value)
            # This must run before the more generic '+' handling so we do not
            # misinterpret the pattern as a symmetric tolerance.
            plus_count = text.count('+')
            if plus_count >= 2 and '±' not in text and '-' not in text:
                # Normalise whitespace for matching but keep original numbers
                normalized = ' '.join(text.split())

                # Pattern 1: +lower nominal +upper  (e.g. "+0.5 40 +0.2")
                m1 = re.match(r'^\+(?P<lower>\d+\.?\d*)\s+(?P<nom>\d+\.?\d*)\s*\+(?P<upper>\d+\.?\d*)$', normalized)
                # Pattern 2: nominal +upper +lower (e.g. "40 +0.2 +0.5")
                m2 = re.match(r'^(?P<nom>\d+\.?\d*)\s*\+(?P<upper>\d+\.?\d*)\s*\+(?P<lower>\d+\.?\d*)$', normalized)

                match = m1 or m2
                if match:
                    nom = match.group('nom')
                    upper = match.group('upper')
                    lower = match.group('lower')

                    nominal_value = nom
                    upper_tol = f"+{upper}"
                    lower_tol = f"+{lower}"

                    dim_type = DimensionParser.determine_dimension_type(text_original, nominal_value)
                    return dim_type, upper_tol, lower_tol, nominal_value

            # Remove spaces for other parsing
            text_no_spaces = ''.join(text.split())

            # Handle pure tolerance values
            if text_no_spaces.startswith('+'):
                nominal_value = ""
                upper_tol = text_original  # Keep the entire text including +
                lower_tol = "0"
                dim_type = "Tolerance"
                return dim_type, upper_tol, lower_tol, nominal_value

            # Handle THRU dimensions
            if "THRU" in text.upper():
                numeric_part = text.upper().split("THRU")[0].strip()
                return "THRU", "0", "0", numeric_part

            if '±' in text:
                parts = text.split('±')
                nominal_value = parts[0].strip()
                if len(parts) > 1:
                    # Extract tolerance value (may include degree symbol and TYP suffix)
                    tol_part = parts[1].strip()
                    # Match tolerance pattern: number followed optionally by degree symbol
                    # Pattern: optional number, then optional degree symbol, then optional text like TYP
                    tol_match = re.search(r'(\d+\.?\d*)\s*(°)?', tol_part)
                    if tol_match:
                        tol_value = tol_match.group(1)
                        tol_degree = tol_match.group(2) if tol_match.group(2) else ''
                        # Check if tolerance should have degree symbol (if nominal has it)
                        if '°' in nominal_value or tol_degree:
                            upper_tol = f"+{tol_value}°"
                            lower_tol = f"-{tol_value}°"
                        else:
                            upper_tol = f"+{tol_value}"
                            lower_tol = f"-{tol_value}"
                    else:
                        # Fallback: use first word/part
                        tol = tol_part.split()[0] if tol_part.split() else tol_part
                        upper_tol = f"+{tol}"
                        lower_tol = f"-{tol}"

            elif '+' in text:
                plus_index = text.find('+')
                nominal_value = text[:plus_index].strip()
                tolerance = text[plus_index+1:].strip()
                upper_tol = f"+{tolerance}"
                lower_tol = f"-{tolerance}"

            else:
                nominal_value = text_original
                upper_tol = "0"
                lower_tol = "0"

            # Special handling for reference dimensions
            if text_original.startswith("(") and text_original.endswith(")"):
                nominal_value = text_original  # Keep the full text including parentheses
                upper_tol = ""
                lower_tol = ""

            # Determine dimension type (use original text for better pattern matching)
            dim_type = DimensionParser.determine_dimension_type(text_original, nominal_value)

            return dim_type, upper_tol, lower_tol, nominal_value

        except Exception as e:
            logger.error(f"Error parsing dimension: {str(e)}")
            return "Length", "0", "0", text
    
    @staticmethod
    def parse_dimensions_from_region(
        pdf_path: str,
        page_number: int,
        region: dict,
        scale_factor: float = 1.0
    ) -> list:
        """
        Extract text from a PDF region and parse dimensions from it.
        
        Args:
            pdf_path: Path to the PDF file
            page_number: Page number (0-indexed)
            region: Dictionary with keys 'x', 'y', 'width', 'height'
            scale_factor: Factor to scale coordinates (default 1.0)
        
        Returns:
            List of dictionaries with parsed dimension data:
            {
                'text': str,
                'nominal_value': str,
                'upper_tolerance': str,
                'lower_tolerance': str,
                'dimension_type': str,
                'bbox': list
            }
        """
        try:
            # Import TextExtractor here to avoid circular imports
            from text_extractor import TextExtractor
            
            # Extract text from the region
            text_results = TextExtractor.extract_text_from_region(
                pdf_path=pdf_path,
                page_number=page_number,
                region=region,
                scale_factor=scale_factor
            )
            
            if not text_results:
                logger.warning(f"No text extracted from region: {region}")
                return []
            
            # Parse dimensions from extracted text
            dimension_results = []
            processed_texts = set()
            
            for text_item in text_results:
                text_content = text_item.get('text', '').strip()
                if not text_content:
                    continue
                
                # Skip if already processed
                if text_content in processed_texts:
                    continue
                
                logger.debug(f"Checking text for dimension: '{text_content}'")
                
                # Check if this text is a dimensional value
                is_dim = DimensionParser.is_dimensional_value(text_content)
                
                if is_dim:
                    try:
                        dim_type, upper_tol, lower_tol, nominal_value = DimensionParser.parse_dimension(text_content)
                        logger.info(f"✓ Parsed dimension: '{text_content}' -> type={dim_type}, nominal={nominal_value}, utol={upper_tol}, ltol={lower_tol}")
                        dimension_results.append({
                            'text': text_content,
                            'nominal_value': nominal_value,
                            'upper_tolerance': upper_tol,
                            'lower_tolerance': lower_tol,
                            'dimension_type': dim_type,
                            'bbox': text_item.get('box', [])
                        })
                        processed_texts.add(text_content)
                    except Exception as e:
                        logger.error(f"Error parsing dimension '{text_content}': {str(e)}")
            
            logger.info(f"Parsed {len(dimension_results)} dimensions from region")
            return dimension_results
            
        except ImportError as e:
            logger.error(f"Failed to import TextExtractor: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Error parsing dimensions from region: {str(e)}", exc_info=True)
            return []
