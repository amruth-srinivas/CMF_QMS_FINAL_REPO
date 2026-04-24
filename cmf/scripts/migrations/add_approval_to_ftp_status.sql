-- Add approved_by_username and approved_at to quality.ftp_status
ALTER TABLE quality.ftp_status ADD COLUMN IF NOT EXISTS approved_by_username VARCHAR(255);
ALTER TABLE quality.ftp_status ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE;
