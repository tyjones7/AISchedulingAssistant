-- Migration 018: AI-powered content classification for LS iCal events
--
-- content_type: 'graded' (student deliverable) | 'course_content' (class topic, reading guide, etc.)
-- classification_confirmed: false = AI classified but awaiting user review
--                           true  = confirmed (either by user or pre-existing assignment)

ALTER TABLE assignments
  ADD COLUMN IF NOT EXISTS content_type TEXT DEFAULT 'graded',
  ADD COLUMN IF NOT EXISTS classification_confirmed BOOLEAN DEFAULT TRUE;

-- All existing assignments are assumed confirmed graded (they were already in the dashboard)
UPDATE assignments SET classification_confirmed = TRUE WHERE classification_confirmed IS NULL;
