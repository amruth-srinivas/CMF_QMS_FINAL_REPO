#!/usr/bin/env python
"""
Startup script for the QMS backend with Windows-friendly reload configuration.
This script addresses Windows socket resource exhaustion issues.
"""
import uvicorn
import sys
import os
from pathlib import Path

# Disable PaddleX model source check to bypass connectivity check
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

if __name__ == "__main__":
    # Backend root (directory containing app/)
    backend_dir = Path(__file__).parent
    
    print("Starting QMS backend...")
    print("=" * 50)
    
    # Windows-friendly reload configuration
    # Use reload-dir to limit file watching and prevent socket exhaustion
    reload_dirs = [
        str(backend_dir / "app"),
    ]
    
    # Exclude common directories that don't need watching
    reload_excludes = [
        "*.pyc",
        "__pycache__",
        "*.log",
        "*.pt",  # YOLO model files
        "*.pdf",
        "*.step",
        "blob_data",
        "venv",
        ".git",
        "migrations",
    ]
    
    try:
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            log_level="info",
            reload=True,
            reload_dirs=reload_dirs,
            reload_excludes=reload_excludes,
            # Use poll-based reloader on Windows to avoid socket issues
            reload_delay=0.5,  # Small delay to batch file changes
        )
    except KeyboardInterrupt:
        print("\nShutting down server...")
        sys.exit(0)
    except Exception as e:
        print(f"Error starting server: {e}")
        sys.exit(1)
