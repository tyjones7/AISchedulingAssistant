-- Add Canvas LMS support: source tracking and Canvas assignment ID
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'learning_suite';
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS canvas_id BIGINT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_assignments_canvas_id ON assignments(canvas_id) WHERE canvas_id IS NOT NULL;
UPDATE assignments SET source = 'learning_suite' WHERE source IS NULL;
