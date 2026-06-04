-- Migration: Add priority_component to parts table
-- Run this script against your PostgreSQL database before starting the updated backend.
-- Usage: psql -U user -d qms_db -f 002_add_priority_component_to_parts.sql

-- Add priority_component column to parts table
ALTER TABLE parts ADD COLUMN IF NOT EXISTS priority_component BOOLEAN DEFAULT FALSE;

-- Add index for better query performance on priority components
CREATE INDEX IF NOT EXISTS ix_parts_priority_component ON parts(priority_component);
