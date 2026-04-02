-- Migration 021: Add label column to time_blocks
-- Stores the display label for a time block (usually the assignment title)
-- so blocks can render without requiring the assignments join.

ALTER TABLE time_blocks
  ADD COLUMN IF NOT EXISTS label TEXT;
