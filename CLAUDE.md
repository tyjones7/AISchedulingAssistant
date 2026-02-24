# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CampusAI — an AI-powered scheduling assistant for BYU students. Scrapes assignments from BYU Learning Suite and Canvas, displays them in a timeline dashboard, and uses Groq-powered AI to personalize scheduling advice, proactively surface study plans, and send push notifications. Uses Supabase (PostgreSQL) as the database.

## Common Commands

### Backend (FastAPI)
```bash
cd backend
python3 -m uvicorn main:app --reload    # Start dev server on localhost:8000
python3 main.py                          # Alternative: run directly
python3 scraper/learning_suite_scraper.py  # Run the Learning Suite scraper
python3 test_scraper.py --debug          # Test scraper with verbose logging
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
BYU Learning Suite → LearningSuiteScraper (Selenium) ──┐
Canvas LMS API ─────────────────────────────────────────┼→ Supabase PostgreSQL
                                                        │        ↓
React Frontend (Dashboard) ← FastAPI Backend ←──────────┘
                                   ↕
                              Groq AI API
```

### Backend (`/backend`)
- `main.py` - FastAPI app. Key route groups:
  - Assignments: `GET /assignments`, `GET /assignments/stats/summary`, `PATCH /assignments/{id}`
  - Sync: `POST /sync/start`, `GET /sync/status/{task_id}`, `GET /sync/last`
  - Auth: `POST /auth/browser-login`, `GET /auth/status`, `POST /auth/logout`
  - AI: `GET /ai/suggestions`, `POST /ai/suggestions/generate`, `POST /ai/briefing/generate`, `POST /ai/chat` (SSE streaming), `POST /ai/apply-plan`
  - Preferences: `GET /preferences`, `POST /preferences`
  - Push: `GET /push/vapid-public-key`, `POST /push/subscribe`, `DELETE /push/subscribe`, `POST /push/send-deadline-reminders`
- `ai_service.py` - Groq AI client (singleton). Four public functions:
  - `generate_suggestions(assignments, prefs)` - batch priority scoring, returns `[{assignment_id, priority_score, suggested_start, rationale, estimated_minutes}]`
  - `generate_briefing(assignments, prefs)` - natural-language daily overview
  - `chat_stream(messages, assignments, prefs)` - streaming SSE chat, yields delta strings
  - `extract_plan(messages, assignments)` - structured plan extraction from conversation
  - All functions accept optional `prefs` dict and inject student profile into prompts
- `scraper/learning_suite_scraper.py` - Selenium scraper for BYU Learning Suite with CAS auth and Duo MFA support (5-minute browser login timeout). Extracts `description`, `point_value`, `assignment_type` from embedded JS JSON.
- `sync_service.py` - Background sync orchestrator with thread-safe status tracking
- `auth_store.py` - Singleton store for the authenticated Selenium scraper session
- `canvas_auth_store.py` - Canvas API token store

### Frontend (`/frontend`)
- `src/components/Dashboard.jsx` - Main dashboard. Accepts `preferences` and `onPreferencesChange` props. Contains involvement level selector and `openChatRef` for programmatic chat opening.
- `src/components/AssignmentCard.jsx` - Assignment card with status dropdown, AI suggested-start pill, and AI-estimated time badge (italic, shown when no user estimate set).
- `src/components/AssignmentDetail.jsx` - Modal for viewing/editing assignment details (estimated time, planned start/end, notes, calendar export).
- `src/components/AIChat.jsx` - Floating chat panel. Accepts `involvementLevel` and `openChatRef` props. Auto-loads daily briefing as first message on first open of the day (proactive/balanced only). Streaming SSE, persistent localStorage history, "Apply as my schedule" button.
- `src/components/AIBriefing.jsx` - Daily AI briefing display panel on dashboard.
- `src/components/ProactivePlan.jsx` - Proactive AI study plan card shown at top of dashboard. Auto-generates suggestions for proactive users, shows top 4 priorities, has "Apply this plan" and "Chat to adjust" buttons. Dismissible per day.
- `src/components/OnboardingSurvey.jsx` - Full-screen modal shown on first use. 5 questions: study time, session length, advance days, work style, involvement level. Posts to `/preferences`.
- `src/components/SyncButton.jsx` - Sync trigger with status polling and stale indicator.
- `src/components/LoginPage.jsx` - BYU browser-based authentication flow.
- `src/components/Toast.jsx` - Toast notification system.
- `src/config/api.js` - API base URL configuration.
- `src/utils/pushNotifications.js` - Web Push helpers: `registerPushNotifications()`, `unregisterPushNotifications()`, `isPushSupported()`, `getPushPermission()`.
- `public/sw.js` - Service worker for background push notifications.

### Database Schema

Table: `assignments`
- `id`, `title`, `course_name`, `due_date`, `description`, `link`, `status`
- `is_modified`, `last_scraped_at`, `learning_suite_url`, `assignment_type`, `ls_cid`
- `estimated_minutes`, `planned_start`, `planned_end`, `notes`
- `source` (`learning_suite` | `canvas`), `canvas_id`
- `point_value` — points possible, scraped from Learning Suite

Valid status values: `newly_assigned`, `not_started`, `in_progress`, `submitted`, `unavailable`

Table: `sync_metadata`
- `last_sync_at`, `last_sync_status`, `last_sync_summary`, `last_sync_error`

Table: `ai_suggestions`
- `id`, `assignment_id` (FK → assignments), `priority_score` (1–10), `suggested_start` (DATE), `rationale`, `estimated_minutes`, `generated_at`

Table: `user_preferences` (single row)
- `id`, `study_time` (`morning`|`afternoon`|`evening`|`night`), `session_length_minutes`, `advance_days`, `work_style` (`spread_out`|`batch`), `involvement_level` (`proactive`|`balanced`|`prompt_only`), `created_at`, `updated_at`

Table: `push_subscriptions`
- `id`, `endpoint`, `p256dh`, `auth`, `created_at`

Migrations: `/backend/migrations/` (001–009)

## Environment Variables

Backend `.env` requires:
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_KEY` - Supabase anon API key
- `GROQ_API_KEY` - Groq API key for AI features
- `VAPID_PUBLIC_KEY` - Web Push VAPID public key (base64url)
- `VAPID_PRIVATE_KEY` - Web Push VAPID private key (PEM)
- `VAPID_CONTACT` - Contact email for VAPID (e.g. `mailto:admin@campusai.app`)
- `CORS_ORIGIN` - (optional) Comma-separated allowed origins, defaults to `http://localhost:5173`

Frontend `.env`:
- `VITE_API_URL` - Backend API URL, defaults to `http://localhost:8000`
- `VITE_VAPID_PUBLIC_KEY` - VAPID public key (must match backend)

## AI Feature Details

### Models (Groq)
- `llama-3.1-8b-instant` — batch priority scoring (`generate_suggestions`), plan extraction (`extract_plan`)
- `llama-3.3-70b-versatile` — chat (`chat_stream`), daily briefing (`generate_briefing`)

### Student Profile Injection
All AI calls receive a `prefs` dict from `_fetch_user_preferences()`. The `_build_profile_context(prefs)` helper formats it into natural language appended to every prompt. This personalizes session length suggestions, advance-planning advice, and tone.

### Assignment Context
`_build_assignment_context(assignments)` formats active assignments with: ID, title, type, course, status, due date (relative), point value, estimated time, notes, description (truncated to 200 chars). Assignments with no description and no estimate are flagged `[no description — ask student about this]` so the chat AI asks clarifying questions.

### Active Assignment Filter
`_fetch_active_assignments()` uses `.not_.in_("status", ["submitted", "unavailable"])` — only truly active assignments reach the AI. Do NOT change this to an OR/AND with due_date, as that caused 60+ submitted assignments to bleed through and truncate the AI response.

### Involvement Levels
- `proactive` — ProactivePlan auto-generates suggestions on dashboard load; chat auto-opens with day overview; push subscription requested after onboarding
- `balanced` — ProactivePlan shows existing suggestions (no auto-generate); chat auto-opens with day overview; push subscription requested
- `prompt_only` — ProactivePlan hidden; chat starts blank; no push subscription

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
- Authentication: backend opens a visible Chrome window, user logs in to BYU CAS + Duo, authenticated Selenium session is reused for scraping
- Pre-existing ESLint warning in `App.jsx` (variable used before declaration) — not a bug, React hoists function declarations
- Chat conversation is persisted in localStorage under `campus-ai-chat`; daily briefing date tracked under `campus-ai-briefing-date`; proactive plan dismissal under `campus-ai-plan-dismissed`
