-- Migration 009: Add point_value to assignments for richer AI context
-- Run this in the Supabase SQL Editor before starting the backend.

ALTER TABLE assignments
ADD COLUMN IF NOT EXISTS point_value NUMERIC;

COMMENT ON COLUMN assignments.point_value IS
    'Points possible for this assignment, scraped from Learning Suite';
