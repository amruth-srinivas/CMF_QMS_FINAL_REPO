-- Migration: Add name, no, rev to Assembly and Part
-- Run this script against your PostgreSQL database before starting the updated backend.
-- Usage: psql -U user -d qms_db -f 001_add_name_no_rev_to_assembly_and_part.sql

-- Add no and rev to assemblies table
ALTER TABLE assemblies ADD COLUMN IF NOT EXISTS no VARCHAR(255);
ALTER TABLE assemblies ADD COLUMN IF NOT EXISTS rev VARCHAR(64);
CREATE INDEX IF NOT EXISTS ix_assemblies_no ON assemblies(no);

-- Add rev to parts table (name and part_no already exist)
ALTER TABLE parts ADD COLUMN IF NOT EXISTS rev VARCHAR(64);
