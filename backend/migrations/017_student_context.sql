-- Migration 017: student_context on user_preferences, label on time_blocks

-- 1. Persistent student context the AI can read/write to understand the student over time
ALTER TABLE user_preferences
  ADD COLUMN IF NOT EXISTS student_context TEXT DEFAULT '';

-- 2. Human-readable label for each time block (e.g. "Stats HW 5 – Session 1")
ALTER TABLE time_blocks
  ADD COLUMN IF NOT EXISTS label TEXT;
