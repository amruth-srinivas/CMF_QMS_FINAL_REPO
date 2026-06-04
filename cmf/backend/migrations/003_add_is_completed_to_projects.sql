-- Add is_completed column to projects table
-- This column will track whether a project has been marked as complete
-- A project can only be marked as complete when all its parts have inspection_plan_status = true

ALTER TABLE projects 
ADD COLUMN is_completed BOOLEAN DEFAULT FALSE NOT NULL;

-- Add index for better query performance on completed projects
CREATE INDEX idx_projects_is_completed ON projects(is_completed);

-- Add comment to document the purpose of this column
COMMENT ON COLUMN projects.is_completed IS 'Indicates whether the project is complete. A project can only be marked as complete when all associated parts have completed inspection status.';
