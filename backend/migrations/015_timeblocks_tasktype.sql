-- Migration 015: task_type on assignments, time_blocks table, work hours on preferences

-- 1. Add task_type to assignments
ALTER TABLE assignments
  ADD COLUMN IF NOT EXISTS task_type TEXT DEFAULT 'assignment';

-- 2. Add work hours to user_preferences
ALTER TABLE user_preferences
  ADD COLUMN IF NOT EXISTS work_start TEXT DEFAULT '08:00',
  ADD COLUMN IF NOT EXISTS work_end   TEXT DEFAULT '22:00';

-- 3. Create time_blocks table
CREATE TABLE IF NOT EXISTS time_blocks (
  id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        UUID        REFERENCES auth.users NOT NULL,
  assignment_id  UUID        REFERENCES assignments(id) ON DELETE CASCADE,
  date           DATE        NOT NULL,
  start_time     TIMESTAMPTZ NOT NULL,
  end_time       TIMESTAMPTZ NOT NULL,
  status         TEXT        NOT NULL DEFAULT 'planned',  -- planned | completed | skipped
  plan_version   INT         DEFAULT 1,
  created_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS time_blocks_user_date ON time_blocks (user_id, date);

ALTER TABLE time_blocks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage own time_blocks" ON time_blocks;
CREATE POLICY "Users can manage own time_blocks" ON time_blocks
  FOR ALL USING (auth.uid() = user_id);
