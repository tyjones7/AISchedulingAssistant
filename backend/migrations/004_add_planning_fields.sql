-- Migration: Add planning fields to assignments table
-- Run this in Supabase SQL Editor

-- Add estimated_minutes for user's time estimate
ALTER TABLE assignments
ADD COLUMN IF NOT EXISTS estimated_minutes INTEGER;

-- Add planned work block start time
ALTER TABLE assignments
ADD COLUMN IF NOT EXISTS planned_start TIMESTAMPTZ;

-- Add planned work block end time
ALTER TABLE assignments
ADD COLUMN IF NOT EXISTS planned_end TIMESTAMPTZ;

-- Add user notes
ALTER TABLE assignments
ADD COLUMN IF NOT EXISTS notes TEXT;

-- Add index for efficient queries on planned time
CREATE INDEX IF NOT EXISTS idx_assignments_planned_start ON assignments(planned_start)
WHERE planned_start IS NOT NULL;

-- Add comment explaining new fields
COMMENT ON COLUMN assignments.estimated_minutes IS 'User estimate of time needed in minutes';
COMMENT ON COLUMN assignments.planned_start IS 'Planned work block start time';
COMMENT ON COLUMN assignments.planned_end IS 'Planned work block end time';
COMMENT ON COLUMN assignments.notes IS 'User notes about the assignment';
