-- Migration: Add scraper-related columns to assignments table
-- Run this in Supabase SQL Editor

-- Add is_modified column to track teacher changes
ALTER TABLE assignments
ADD COLUMN IF NOT EXISTS is_modified BOOLEAN DEFAULT false;

-- Add last_scraped_at column to track when assignment was last checked
ALTER TABLE assignments
ADD COLUMN IF NOT EXISTS last_scraped_at TIMESTAMPTZ;

-- Add learning_suite_url column to store the direct link to the assignment
ALTER TABLE assignments
ADD COLUMN IF NOT EXISTS learning_suite_url TEXT;

-- Add assignment_type column (quiz, exam, assignment, discussion, etc.)
ALTER TABLE assignments
ADD COLUMN IF NOT EXISTS assignment_type TEXT;

-- Update status constraint to include 'unavailable'
ALTER TABLE assignments
DROP CONSTRAINT IF EXISTS assignments_status_check;

ALTER TABLE assignments
ADD CONSTRAINT assignments_status_check
CHECK (status IN ('newly_assigned', 'not_started', 'in_progress', 'submitted', 'unavailable'));
