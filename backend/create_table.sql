-- Create assignments table for AI Scheduling Assistant
CREATE TABLE IF NOT EXISTS assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    course_name TEXT NOT NULL,
    due_date TIMESTAMPTZ NOT NULL,
    description TEXT,
    link TEXT,
    status TEXT NOT NULL DEFAULT 'newly_assigned'
        CHECK (status IN ('newly_assigned', 'not_started', 'in_progress', 'submitted')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Enable Row Level Security (recommended for Supabase)
ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;

-- Create a policy that allows all operations for now (you can restrict this later with auth)
CREATE POLICY "Allow all operations" ON assignments
    FOR ALL
    USING (true)
    WITH CHECK (true);
