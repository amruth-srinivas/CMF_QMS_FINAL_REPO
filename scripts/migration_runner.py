import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from DB.database import engine
from sqlalchemy import text

def run_migration():
    sql = """
    ALTER TABLE quality.ftp_status ADD COLUMN IF NOT EXISTS approved_by_username VARCHAR(255);
    ALTER TABLE quality.ftp_status ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE;
    """
    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
    print("Migration successful.")

if __name__ == "__main__":
    run_migration()
