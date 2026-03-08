-- Migration 012: Add user_id to all tables + Row Level Security
-- Run in Supabase SQL Editor

-- ── 1. Add user_id column to all tables ───────────────────────────────────────

ALTER TABLE assignments ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE ai_suggestions ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE sync_metadata ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);

-- ── 2. Enable Row Level Security ──────────────────────────────────────────────

ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_suggestions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sync_metadata ENABLE ROW LEVEL SECURITY;
ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY;

-- ── 3. RLS policies: users see only their own rows ────────────────────────────

-- Drop existing policies if re-running migration
DROP POLICY IF EXISTS "own_assignments" ON assignments;
DROP POLICY IF EXISTS "own_preferences" ON user_preferences;
DROP POLICY IF EXISTS "own_suggestions" ON ai_suggestions;
DROP POLICY IF EXISTS "own_sync" ON sync_metadata;
DROP POLICY IF EXISTS "own_push" ON push_subscriptions;

CREATE POLICY "own_assignments"    ON assignments        USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "own_preferences"    ON user_preferences   USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "own_suggestions"    ON ai_suggestions     USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "own_sync"           ON sync_metadata      USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "own_push"           ON push_subscriptions USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- ── 4. user_sessions table: persists LS cookies across Render restarts ────────

CREATE TABLE IF NOT EXISTS user_sessions (
    id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id     UUID REFERENCES auth.users(id) UNIQUE NOT NULL,
    cookies     JSONB,
    base_url    TEXT,
    local_storage   JSONB DEFAULT '{}'::jsonb,
    session_storage JSONB DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE user_sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_sessions" ON user_sessions;
CREATE POLICY "own_sessions" ON user_sessions USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- ── 5. canvas_tokens table: persists Canvas tokens across Render restarts ─────

CREATE TABLE IF NOT EXISTS canvas_tokens (
    id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id     UUID REFERENCES auth.users(id) UNIQUE NOT NULL,
    token       TEXT NOT NULL,
    user_name   TEXT,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE canvas_tokens ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_canvas_tokens" ON canvas_tokens;
CREATE POLICY "own_canvas_tokens" ON canvas_tokens USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- ── 6. Service-role bypass for backend writes (using service key) ─────────────
-- The backend uses the service role key (SUPABASE_SERVICE_KEY) to write data
-- on behalf of users. RLS is enforced at the anon/auth level for frontend calls.
-- No additional grants needed — service role bypasses RLS by design.
