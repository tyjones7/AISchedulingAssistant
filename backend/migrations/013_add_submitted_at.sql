-- Migration 013: Add submitted_at timestamp for submission timing analytics
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ;
