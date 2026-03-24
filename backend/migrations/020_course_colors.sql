-- Migration 020: Add course_colors to user_preferences
-- Stores user-chosen palette indices per course: {"Course Name": 3, ...}

ALTER TABLE user_preferences
  ADD COLUMN IF NOT EXISTS course_colors JSONB DEFAULT '{}';
