-- Migration: Add Learning Suite course ID column
-- Run this in Supabase SQL Editor

-- Add ls_cid column to store the Learning Suite course ID
-- This is needed to build working URLs (e.g., /cid-abc123/student/assignment/xyz)
ALTER TABLE assignments
ADD COLUMN IF NOT EXISTS ls_cid TEXT;

-- Create an index for faster lookups by course
CREATE INDEX IF NOT EXISTS idx_assignments_ls_cid ON assignments(ls_cid);
