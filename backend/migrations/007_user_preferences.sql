-- Migration 007: User preferences for AI personalization
-- Run this in the Supabase SQL Editor before starting the backend.

CREATE TABLE IF NOT EXISTS user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    study_time TEXT CHECK (study_time IN ('morning', 'afternoon', 'evening', 'night')) DEFAULT 'evening',
    session_length_minutes INTEGER DEFAULT 60,
    advance_days INTEGER DEFAULT 2,
    work_style TEXT CHECK (work_style IN ('spread_out', 'batch')) DEFAULT 'spread_out',
    involvement_level TEXT CHECK (involvement_level IN ('proactive', 'balanced', 'prompt_only')) DEFAULT 'balanced',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE user_preferences IS 'Single-row table storing the student AI scheduling preferences';
COMMENT ON COLUMN user_preferences.study_time IS 'When the student does their best work';
COMMENT ON COLUMN user_preferences.session_length_minutes IS 'Preferred study session length in minutes';
COMMENT ON COLUMN user_preferences.advance_days IS 'How many days before a deadline the student likes to start';
COMMENT ON COLUMN user_preferences.work_style IS 'spread_out = multiple sessions, batch = one sitting';
COMMENT ON COLUMN user_preferences.involvement_level IS 'proactive = AI suggests automatically, balanced = near deadlines, prompt_only = waits to be asked';
