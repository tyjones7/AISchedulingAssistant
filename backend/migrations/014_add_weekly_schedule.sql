-- Add weekly_schedule column to user_preferences for storing recurring busy times
ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS weekly_schedule JSONB DEFAULT '[]'::jsonb;
