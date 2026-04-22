-- Inspection plan request notifications (operator -> supervisor).
-- Run after oms.orders exists.

CREATE SCHEMA IF NOT EXISTS notifications;

CREATE TABLE IF NOT EXISTS notifications.inspection_notifications (
  id SERIAL PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES oms.orders(id),
  part_number VARCHAR(255) NOT NULL,
  op_no INTEGER NOT NULL,
  operation_id INTEGER NOT NULL,
  machine_id INTEGER NULL,
  requested_by_username VARCHAR(255) NULL,
  is_ack BOOLEAN NOT NULL DEFAULT false,
  ack_by VARCHAR(255) NULL,
  ack_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_inspection_notifications_order_op
  ON notifications.inspection_notifications (order_id, part_number, op_no);

CREATE INDEX IF NOT EXISTS ix_inspection_notifications_pending
  ON notifications.inspection_notifications (is_ack, created_at DESC);
