# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CampusAI — an AI-powered scheduling assistant for BYU students. Syncs assignments from Canvas LMS, displays them in a timeline dashboard, and uses Groq-powered AI to personalize scheduling advice, proactively surface study plans, and send push notifications. Uses Supabase (PostgreSQL) as the database.

## Common Commands

### Backend (FastAPI)
```bash
cd backend
python3 -m uvicorn main:app --reload    # Start dev server on localhost:8000
python3 main.py                          # Alternative: run directly
python3 seed.py                          # Seed database with sample assignments
python3 diagnose_db.py                   # View database contents by course
python3 clear_assignments.py             # Clear all assignments from database
```

### Frontend (React + Vite)
```bash
cd frontend
npm run dev      # Start dev server on localhost:5173
npm run build    # Production build
npm run lint     # Run ESLint
npm run preview  # Preview production build
```

## Architecture

```
Canvas LMS API (REST) ──────────────────────────→ Supabase PostgreSQL
                                                         ↓
React Frontend (Dashboard) ← FastAPI Backend ←──────────┘
                                   ↕
                              Groq AI API
```

### Backend (`/backend`)
- `main.py` - FastAPI app. Key route groups:
  - Assignments: `GET /assignments`, `GET /assignments/stats/summary`, `PATCH /assignments/{id}`, `POST /assignments/dismiss-overdue`
  - Sync: `POST /sync/start`, `GET /sync/status/{task_id}`, `GET /sync/last`
  - Auth: `GET /auth/canvas-status`, `POST /auth/canvas-token`, `POST /auth/logout`
  - AI: `GET /ai/suggestions`, `POST /ai/suggestions/generate`, `POST /ai/briefing/generate`, `POST /ai/chat` (SSE streaming), `POST /ai/apply-plan`
  - Preferences: `GET /preferences`, `POST /preferences`
  - Push: `GET /push/vapid-public-key`, `POST /push/subscribe`, `DELETE /push/subscribe`, `POST /push/send-deadline-reminders`
- `ai_service.py` - Groq AI client (singleton). Four public functions:
  - `generate_suggestions(assignments, prefs)` - batch priority scoring, returns `[{assignment_id, priority_score, suggested_start, rationale, estimated_minutes}]`
  - `generate_briefing(assignments, prefs)` - natural-language daily overview
  - `chat_stream(messages, assignments, prefs)` - streaming SSE chat, yields delta strings
  - `extract_plan(messages, assignments)` - structured plan extraction from conversation
  - All functions accept optional `prefs` dict and inject student profile into prompts
- `scraper/canvas_client.py` - Canvas REST API client. Uses personal access token (Bearer auth). Key methods: `get_courses()`, `get_assignments(course_id, course_name)`, `scrape_all_courses()`, `update_database()`.
- `sync_service.py` - Background sync orchestrator with thread-safe status tracking
- `canvas_auth_store.py` - Canvas API token store (per-user, Supabase-backed)

### Frontend (`/frontend`)
- `src/components/Dashboard.jsx` - Main dashboard. Two-column layout (timeline left, AI sidebar right, max-width 1400px). Accepts `preferences` and `onPreferencesChange` props. Contains `openChatRef` for programmatic chat opening. No involvement selector in header — that lives in Settings.
- `src/components/AssignmentCard.jsx` - Assignment card with status dropdown, AI suggested-start pill, and AI-estimated time badge (italic, shown when no user estimate set).
- `src/components/AssignmentDetail.jsx` - Modal for viewing/editing assignment details. When `source === 'manual'`, renders editable title/course/due date fields.
- `src/components/AIChat.jsx` - Floating chat panel. Accepts `involvementLevel` and `openChatRef` props. Auto-loads daily briefing as first message on first open of the day (proactive/balanced only). Streaming SSE, persistent localStorage history, "Apply as my schedule" button.
- `src/components/AIBriefing.jsx` - Daily AI briefing display panel on dashboard (right sidebar).
- `src/components/ProactivePlan.jsx` - Proactive AI study plan card shown in right sidebar. Auto-generates suggestions for proactive users, shows top 4 priorities, has "Apply this plan" (with Google Cal + ICS export) and "Chat to adjust" buttons. Dismissible per day.
- `src/components/OnboardingSurvey.jsx` - Full-screen overlay wizard shown on first use. Steps: -1=Welcome, 0=Canvas Connect, 1-5=Survey questions. `onComplete(prefs, canvasConnected)` signature.
- `src/components/SyncButton.jsx` - Sync trigger with status polling and stale indicator.
- `src/components/Settings.jsx` - Settings panel: Canvas reconnect, preferences (involvement level, study habits), weekly schedule busy-blocks, push notifications toggle.
- `src/components/StatsPanel.jsx` - Assignment stats with points progress bar.
- `src/components/Toast.jsx` - Toast notification system.
- `src/lib/api.js` - `authFetch` (injects Authorization header) and `API_BASE`.
- `src/utils/pushNotifications.js` - Web Push helpers: `registerPushNotifications()`, `unregisterPushNotifications()`, `isPushSupported()`, `getPushPermission()`.
- `src/utils/calendar.js` - `getGoogleCalendarUrl()`, `downloadMultiICS()` for calendar export.
- `public/sw.js` - Service worker for background push notifications. Has `/* global clients */` comment to suppress ESLint false-positives.

### Database Schema

Table: `assignments`
- `id`, `title`, `course_name`, `due_date`, `description`, `link`, `status`
- `is_modified`, `last_scraped_at`, `assignment_type`, `canvas_id`
- `estimated_minutes`, `planned_start`, `planned_end`, `notes`
- `source` (`canvas` | `manual`), `canvas_id`
- `point_value` — points possible (always refreshed on re-sync)
- `is_extra_credit` — BOOLEAN DEFAULT FALSE (migration 010)

Valid status values: `newly_assigned`, `not_started`, `in_progress`, `submitted`, `unavailable`

Table: `sync_metadata`
- `last_sync_at`, `last_sync_status`, `last_sync_summary`, `last_sync_error`

Table: `ai_suggestions`
- `id`, `assignment_id` (FK → assignments), `priority_score` (1–10), `suggested_start` (DATE), `rationale`, `estimated_minutes`, `generated_at`

Table: `user_preferences` (single row per user)
- `id`, `study_time` (`morning`|`afternoon`|`evening`|`night`), `session_length_minutes`, `advance_days`, `work_style` (`spread_out`|`batch`), `involvement_level` (`proactive`|`balanced`|`prompt_only`), `weekly_schedule` (JSONB array of `{days, label, start, end}` blocks), `created_at`, `updated_at`

Table: `push_subscriptions`
- `id`, `endpoint`, `p256dh`, `auth`, `created_at`

Table: `canvas_tokens` — per-user Canvas API tokens (encrypted)

Table: `user_sessions` — per-user LS session cookies

Migrations: `/backend/migrations/` (001–014)

## Environment Variables

Backend `.env` requires:
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_KEY` - Supabase anon API key
- `SUPABASE_SERVICE_KEY` - Service role key (bypasses RLS for backend writes)
- `SUPABASE_JWT_SECRET` - JWT secret for verifying auth tokens
- `GROQ_API_KEY` - Groq API key for AI features
- `VAPID_PUBLIC_KEY` - Web Push VAPID public key (base64url)
- `VAPID_PRIVATE_KEY` - Web Push VAPID private key (PEM)
- `VAPID_CONTACT` - Contact email for VAPID (e.g. `mailto:admin@campusai.app`)
- `CORS_ORIGIN` - (optional) Comma-separated allowed origins, defaults to `http://localhost:5173`

Frontend `.env`:
- `VITE_API_URL` - Backend API URL, defaults to `http://localhost:8000`
- `VITE_SUPABASE_URL` - Supabase project URL
- `VITE_SUPABASE_ANON_KEY` - Supabase anon key
- `VITE_VAPID_PUBLIC_KEY` - VAPID public key (must match backend)

## Canvas Scraper Details

- Auth: Bearer token stored in `canvas_tokens` table via `canvas_auth_store.py`
- `get_courses()`: calls `/api/v1/courses?enrollment_state=active&include[]=enrollments&per_page=100`, then filters to `StudentEnrollment` type in Python. **Do NOT add `enrollment_type[]` or `state[]` query params** — BYU's Canvas instance returns 500 for those params with student tokens.
- `get_assignments()`: includes `submission` and `overrides` for student-effective due dates and submission status
- Due dates: UTC from Canvas → converted to Mountain Time (`America/Denver`)
- `update_database()`: match key is `canvas_id`. New → `newly_assigned`. Existing + not modified → sync status (preserve `newly_assigned`/`in_progress`). Existing + `is_modified=true` → update metadata only (never touch status/planning fields).

## AI Feature Details

### Models (Groq)
- `llama-3.1-8b-instant` — batch priority scoring (`generate_suggestions`), plan extraction (`extract_plan`)
- `llama-3.3-70b-versatile` — chat (`chat_stream`), daily briefing (`generate_briefing`)

### Student Profile Injection
All AI calls receive a `prefs` dict from `_fetch_user_preferences()`. The `_build_profile_context(prefs)` helper formats it into natural language appended to every prompt, including `weekly_schedule` busy blocks so AI schedules around class times.

### Assignment Context
`_build_assignment_context(assignments)` formats active assignments with: ID, title, type, course, status, due date (relative), point value, estimated time, notes, description (truncated to 200 chars).

### Active Assignment Filter
`_fetch_active_assignments()` uses `.not_.in_("status", ["submitted", "unavailable"])` — only truly active assignments reach the AI. Do NOT add a due_date filter — that caused submitted assignments to bleed through.

### Involvement Levels
- `proactive` — ProactivePlan auto-generates suggestions on dashboard load; chat auto-opens with day overview; push subscription requested after onboarding
- `balanced` — ProactivePlan shows existing suggestions (no auto-generate); chat auto-opens with day overview; push subscription requested
- `prompt_only` — ProactivePlan hidden; chat starts blank; no push subscription

Involvement level is set in **Settings**, not in the Dashboard header.

### Push Notifications
- VAPID keys generated with `py_vapid` (stored in `.env`)
- `pywebpush` sends notifications from `/push/send-deadline-reminders`
- Service worker at `public/sw.js` handles `push` and `notificationclick` events
- Stale subscriptions (404/410) are cleaned up automatically on send

## Key Details

- Frontend runs on port 5173, backend on port 8000
- Use `python3` (not `python`) — this macOS environment has no `python` alias
- All scraped dates are localized to `America/Denver` (Mountain Time) via `zoneinfo.ZoneInfo`
- All internal timestamps use `datetime.now(timezone.utc)`
- During sync, Dashboard polls `GET /assignments` every 5 seconds for real-time updates
- Stale sync guard: if `_current_task_id` is >10 minutes old it's force-expired so a new sync can start
- ESLint: all errors/warnings suppressed with inline `// eslint-disable` comments where intentional
- Chat conversation is persisted in localStorage under `campus-ai-chat`; daily briefing date tracked under `campus-ai-briefing-date`; proactive plan dismissal under `campus-ai-plan-dismissed`
- Onboarding flow: new users see Welcome → Canvas Connect → Survey overlay on top of Dashboard. Returning users (canvas connected + prefs saved) go straight to Dashboard.
- Dashboard layout: two-column CSS grid (`1fr 340px`), max-width 1400px. Right sidebar is sticky with ProactivePlan + AIBriefing + AIChat.
- Manual assignments (`source === 'manual'`): title, course, and due date are editable in AssignmentDetail modal. Canvas assignments are read-only for those fields.
