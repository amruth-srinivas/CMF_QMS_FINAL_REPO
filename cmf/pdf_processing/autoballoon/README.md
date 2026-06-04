# Autoballoon OCR / GD&T pipeline

This package was moved from `cmf/backend/app/qms/autoballoon` into the main CMF API.

## Models (required)

Place PaddleOCR and GD&T weights under `models/`:

- `PP-OCRv5_mobile_det/`
- `en_PP-OCRv5_mobile_rec/`
- `PP-LCNet_x1_0_textline_ori/`
- `gdt_model_2.pt`

If you still have `cmf/backend`, copy:

```text
cmf/backend/app/qms/autoballoon/models/  →  cmf/pdf_processing/autoballoon/models/
```

Then delete `cmf/backend`.

## Python dependencies

See `cmf/requirements.txt` (`paddleocr`, `paddlepaddle`, `opencv-python-headless`, `ultralytics`, `pymupdf`).

## Usage in CMF

- Region text: `pdf_processing/backend_ocr_extractor.py` (OCR first, PyMuPDF fallback via `region_text_extraction.py`)
- Full region dimensions: `services/autoballoon_service.py` → `/api/v1/pdf-annotation/process-dimensions`
