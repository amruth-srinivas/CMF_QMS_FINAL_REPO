-- Scope inspector notes per operation (and document source) so Final Part notes
-- do not appear on every operation inspection.

ALTER TABLE quality.notes
  ADD COLUMN IF NOT EXISTS op_no INTEGER NOT NULL DEFAULT 0;

ALTER TABLE quality.notes
  ADD COLUMN IF NOT EXISTS is_operation_document BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_quality_notes_op_no ON quality.notes (op_no);
