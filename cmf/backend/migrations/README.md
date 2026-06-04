# Database Migrations

Run SQL migrations in order when upgrading the database.

## Migrations

| File | Description |
|------|-------------|
| 001_add_name_no_rev_to_assembly_and_part.sql | Add name, no, rev to Assembly and Part |
| 002_add_priority_component_to_parts.sql | Add priority/component to parts |
| 003_add_is_completed_to_projects.sql | Add is_completed to projects |
| 004_add_next_calibration_date_to_bluetooth_devices.sql | Add next_calibration_date to bluetooth_devices |
| 005_create_report_config_tables.sql | Create report_config and report_config_fields tables |

## Running migrations

**Option 1 – psql (PostgreSQL):**
```bash
psql -U your_user -d qms_db -f migrations/005_create_report_config_tables.sql
```

**Option 2 – From backend directory with Python:**
```bash
cd backend
python -c "
from app.database import engine
from sqlalchemy import text
with open('migrations/005_create_report_config_tables.sql') as f:
    with engine.connect() as conn:
        conn.execute(text(f.read()))
        conn.commit()
print('Migration 005 applied.')
"
```

**Note:** If the backend is started after adding the new models, `init_db()` will create the new tables automatically. Use the SQL migration when you need to apply schema changes without restarting or when managing production databases manually.
