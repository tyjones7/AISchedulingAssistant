-- Migration 011: Backfill source field on assignments that have a NULL source
-- Run this in the Supabase SQL Editor before starting the backend.
--
-- Assignments scraped by the Learning Suite scraper before source tracking was
-- introduced have source = NULL.  These two UPDATE statements infer the correct
-- source from the columns that are reliably populated by each scraper:
--   - ls_cid  is only set by the Learning Suite scraper
--   - canvas_id is only set by the Canvas scraper
--
-- Safe to run multiple times: the WHERE source IS NULL guard ensures already-
-- corrected rows are never touched again.

-- Backfill Learning Suite assignments
UPDATE assignments
SET source = 'learning_suite'
WHERE ls_cid IS NOT NULL
  AND source IS NULL;

-- Backfill Canvas assignments
UPDATE assignments
SET source = 'canvas'
WHERE canvas_id IS NOT NULL
  AND source IS NULL;
