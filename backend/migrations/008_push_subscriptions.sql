-- Migration 008: Push notification subscriptions
-- Run this in the Supabase SQL Editor before starting the backend.

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE push_subscriptions IS 'Web Push API subscriptions for browser notifications';
COMMENT ON COLUMN push_subscriptions.endpoint IS 'Push service endpoint URL';
COMMENT ON COLUMN push_subscriptions.p256dh IS 'Client public key (p256dh)';
COMMENT ON COLUMN push_subscriptions.auth IS 'Client auth secret';
