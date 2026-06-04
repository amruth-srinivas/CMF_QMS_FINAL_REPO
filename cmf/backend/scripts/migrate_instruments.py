
from sqlalchemy import create_engine, text
from app.core.config import settings

def migrate():
    engine = create_engine(settings.DATABASE_URL)
    with engine.connect() as conn:
        print("Checking for missing columns in library_instruments...")
        
        # List of columns to add
        cols = [
            ("instrument_name", "VARCHAR(255)"),
            ("manufacturer", "VARCHAR(120)"),
            ("model_number", "VARCHAR(120)"),
            ("serial_number", "VARCHAR(255)"),
            ("range", "VARCHAR(120)"),
            ("resolution", "VARCHAR(120)"),
            ("accuracy", "VARCHAR(120)"),
            ("last_calibration_date", "VARCHAR(64)"),
            ("calibration_interval", "INTEGER"),
            ("status", "VARCHAR(64)"),
            ("location", "VARCHAR(255)")
        ]
        
        for col_name, col_type in cols:
            try:
                # Check if column exists
                res = conn.execute(text(f"SELECT column_name FROM information_schema.columns WHERE table_name='library_instruments' AND column_name='{col_name}'"))
                if not res.fetchone():
                    print(f"Adding column {col_name}...")
                    conn.execute(text(f"ALTER TABLE library_instruments ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
            except Exception as e:
                print(f"Error adding {col_name}: {e}")
        
        print("Migration complete.")

if __name__ == "__main__":
    migrate()
