import sqlite3
import os

db_path = r'C:\Cmti\cmf qms\CMF_QMS_FINAL_REPO\cmf\cmf_qms.db'
if not os.path.exists(db_path):
    print(f"DB not found at {db_path}")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, part_number, qty FROM oms_parts WHERE id = 1472;")
    print(cursor.fetchone())
    conn.close()
