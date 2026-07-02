-- Inspection plan lifecycle: draft (editing) vs confirmed (measurements).
-- Run against PostgreSQL after quality schema exists.

CREATE TABLE IF NOT EXISTS quality.inspection_plan_status (
  id SERIAL PRIMARY KEY,
  part_number VARCHAR(255) NOT NULL,
  sales_order_id INTEGER NOT NULL,
  op_no INTEGER NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'draft',
  confirmed_by_username VARCHAR(255) NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uix_inspection_plan_scope UNIQUE (part_number, sales_order_id, op_no)
);

CREATE INDEX IF NOT EXISTS ix_inspection_plan_status_part_order
  ON quality.inspection_plan_status (sales_order_id, part_number);
