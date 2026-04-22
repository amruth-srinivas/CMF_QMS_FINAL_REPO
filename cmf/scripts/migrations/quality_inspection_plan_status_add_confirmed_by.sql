-- Add who confirmed the inspection plan (username for transparency).
ALTER TABLE quality.inspection_plan_status
  ADD COLUMN IF NOT EXISTS confirmed_by_username VARCHAR(255) NULL;
