from sqlalchemy import create_url, create_engine, text
from pathlib import Path
import os

# Database URL from common patterns in QMS projects
DB_URL = "postgresql://postgres:postgres@localhost:5432/prometrix"

engine = create_engine(DB_URL)

try:
    with engine.connect() as conn:
        # Find document 36's current version blob_path
        query = text("""
            SELECT dv.blob_path 
            FROM document_versions dv
            JOIN documents d ON d.id = dv.document_id
            WHERE d.id = 36 AND dv.is_current = True
        """)
        res = conn.execute(query).fetchone()
        if res:
            blob_path = res[0]
            print(f"Document 36 blob_path: {blob_path}")
            
            # Check if it exists
            # Looking at main.py: settings.BLOB_STORAGE_PATH
            # I'll guess it's 'blob_data' or similar
            for candidate in ['blob_data', 'storage', 'data', 'app/storage']:
                full_path = Path(candidate) / blob_path
                if full_path.exists():
                    print(f"File found at: {full_path}")
                    break
            else:
                print("Could not find file on filesystem.")
        else:
            print("Document 36 not found or has no current version.")
except Exception as e:
    print(f"DB check failed: {e}")
