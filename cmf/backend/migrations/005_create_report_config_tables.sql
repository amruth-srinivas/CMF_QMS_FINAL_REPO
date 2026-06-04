-- Migration: Create report_config and report_config_fields tables
-- Run this script against your PostgreSQL database.
-- Usage: psql -U user -d qms_db -f 005_create_report_config_tables.sql

-- Base report configuration
CREATE TABLE IF NOT EXISTS report_config (
    id SERIAL PRIMARY KEY,
    report_name VARCHAR(255) NOT NULL DEFAULT 'Inspection Report',
    company_name VARCHAR(255),
    logo_path VARCHAR(512),
    is_locked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_report_config_id ON report_config(id);

-- Dynamic header/footer fields
CREATE TABLE IF NOT EXISTS report_config_fields (
    id SERIAL PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES report_config(id) ON DELETE CASCADE,
    section VARCHAR(20) NOT NULL,
    field_label VARCHAR(255) NOT NULL,
    backend_key VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_report_config_fields_id ON report_config_fields(id);
CREATE INDEX IF NOT EXISTS ix_report_config_fields_report_id ON report_config_fields(report_id);

COMMENT ON TABLE report_config IS 'Stores base report template configuration';
COMMENT ON TABLE report_config_fields IS 'Stores dynamic header/footer fields for report templates';
COMMENT ON COLUMN report_config_fields.section IS 'Either header or footer';
