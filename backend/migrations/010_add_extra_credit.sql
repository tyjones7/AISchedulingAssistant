-- Migration 010: Add is_extra_credit flag to assignments
-- Run this in the Supabase SQL Editor before starting the backend.

ALTER TABLE assignments
ADD COLUMN IF NOT EXISTS is_extra_credit BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN assignments.is_extra_credit IS
    'True if Learning Suite or Canvas marks this assignment as extra credit';
