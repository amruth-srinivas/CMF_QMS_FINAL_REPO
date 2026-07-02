"""Apply quality_schema_three_tables.sql using SQLAlchemy (no psql required)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from sqlalchemy import create_engine, text
from DB.database import DATABASE_URL

def main():
    sql_path = os.path.join(os.path.dirname(__file__), "quality_schema_three_tables.sql")
    with open(sql_path, encoding="utf-8") as f:
        sql = f.read()
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
    print("OK: quality_schema_three_tables.sql applied")

if __name__ == "__main__":
    main()
