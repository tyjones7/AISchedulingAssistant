-- Migration 006: AI Suggestions table
-- Run this in the Supabase SQL Editor before starting the backend.

CREATE TABLE IF NOT EXISTS ai_suggestions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id UUID REFERENCES assignments(id) ON DELETE CASCADE,
    priority_score INTEGER CHECK (priority_score BETWEEN 1 AND 10),
    suggested_start DATE,
    rationale TEXT,
    estimated_minutes INTEGER,
    generated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_suggestions_assignment_id
    ON ai_suggestions(assignment_id);

CREATE INDEX IF NOT EXISTS idx_ai_suggestions_generated_at
    ON ai_suggestions(generated_at DESC);

COMMENT ON TABLE ai_suggestions IS
    'AI-generated priority scores and start date suggestions for assignments';
COMMENT ON COLUMN ai_suggestions.priority_score IS
    '1-10 priority score where 10 is most urgent';
COMMENT ON COLUMN ai_suggestions.suggested_start IS
    'AI-recommended date to begin working on the assignment';
COMMENT ON COLUMN ai_suggestions.rationale IS
    'One-sentence explanation for the priority/timing recommendation';
COMMENT ON COLUMN ai_suggestions.estimated_minutes IS
    'AI time estimate (may differ from user-set estimated_minutes on the assignment)';
