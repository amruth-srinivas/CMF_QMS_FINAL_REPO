-- CMF: keep only quality.master_boc, quality.stage_inspection, quality.ftp_status
-- 1) Drop all foreign keys on those three tables (models no longer use FK constraints).
-- 2) Drop any other tables in schema "quality" (balloons, legacy, etc.).

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT tc.constraint_name, tc.table_name
    FROM information_schema.table_constraints tc
    WHERE tc.table_schema = 'quality'
      AND tc.table_name IN ('master_boc', 'stage_inspection', 'ftp_status')
      AND tc.constraint_type = 'FOREIGN KEY'
  LOOP
    EXECUTE format('ALTER TABLE quality.%I DROP CONSTRAINT IF EXISTS %I CASCADE', r.table_name, r.constraint_name);
  END LOOP;
END $$;

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'quality'
      AND tablename NOT IN ('master_boc', 'stage_inspection', 'ftp_status')
  LOOP
    EXECUTE format('DROP TABLE IF EXISTS quality.%I CASCADE', r.tablename);
  END LOOP;
END $$;
