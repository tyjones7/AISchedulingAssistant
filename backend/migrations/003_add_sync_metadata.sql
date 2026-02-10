-- Migration: Add sync_metadata table for tracking sync history
-- Run this in the Supabase SQL Editor

CREATE TABLE IF NOT EXISTS sync_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    last_sync_at TIMESTAMPTZ,
    last_sync_status TEXT,  -- 'success', 'failed', 'partial'
    last_sync_summary JSONB,  -- {"courses_scraped": N, "assignments_added": N, "assignments_updated": N}
    last_sync_error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add index for efficient queries on last sync time
CREATE INDEX IF NOT EXISTS idx_sync_metadata_last_sync_at ON sync_metadata(last_sync_at DESC);

-- Add comment explaining the table
COMMENT ON TABLE sync_metadata IS 'Tracks Learning Suite sync history and status';
