# Others

Scripts and modules that are **not** imported by the FastAPI app. Kept for reference or future use.

| File | Notes |
|------|--------|
| `bluetooth_service.py` | Linux `bluetoothctl`-based helper; the API uses `bleak` in `app/routers/bluetooth.py` instead. |
| `view.py` | Legacy / commented-out view extraction; active code is `app/services/view_extractor.py`. |
