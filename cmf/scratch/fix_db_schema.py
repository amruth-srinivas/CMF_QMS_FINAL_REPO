import json
# pyrefly: ignore [missing-import]
from sqlalchemy import create_engine, text
from DB.database import DATABASE_URL

def fix_db():
    print(f"Connecting to {DATABASE_URL}...")
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        # Check columns
        res = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema = 'quality' AND table_name = 'stage_inspection'"))
        columns = [r[0] for r in res]
        print(f"Existing columns: {columns}")
        
        # Add measurements if missing
        if 'measurements' not in columns:
            print("Adding 'measurements' column to quality.stage_inspection...")
            conn.execute(text("ALTER TABLE quality.stage_inspection ADD COLUMN measurements JSONB NOT NULL DEFAULT '[]'"))
            print("Successfully added 'measurements' column.")
        
        # Make measured_mean nullable
        print("Ensuring 'measured_mean' is nullable...")
        conn.execute(text("ALTER TABLE quality.stage_inspection ALTER COLUMN measured_mean DROP NOT NULL"))
        
        # Make measured_1, measured_2, measured_3 nullable (they are not in the model but in the DB)
        for col in ['measured_1', 'measured_2', 'measured_3']:
            if col in columns:
                print(f"Ensuring '{col}' is nullable...")
                conn.execute(text(f"ALTER TABLE quality.stage_inspection ALTER COLUMN {col} DROP NOT NULL"))
        
        conn.commit()
        print("Database schema fix complete.")

if __name__ == "__main__":
    try:
        fix_db()
    except Exception as e:
        print(f"Error: {e}")
