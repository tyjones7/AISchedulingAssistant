# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Scheduling Assistant for BYU students. Scrapes assignments from BYU Learning Suite and displays them in a Kanban board interface. Uses Supabase (PostgreSQL) as the database.

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
BYU Learning Suite → LearningSuiteScraper (Selenium) → Supabase PostgreSQL
                                                              ↓
React Frontend (Dashboard) ← FastAPI Backend ←────────────────┘
```

### Backend (`/backend`)
- `main.py` - FastAPI app with REST endpoints: GET `/assignments`, GET `/assignments/stats/summary`, PATCH `/assignments/{id}`, sync and auth routes
- `scraper/learning_suite_scraper.py` - Selenium scraper for BYU Learning Suite with CAS auth and Duo MFA support (5-minute browser login timeout)
- `sync_service.py` - Background sync orchestrator with thread-safe status tracking; exposes task-based polling API
- `auth_store.py` - Singleton store for the authenticated Selenium scraper session
- Uses Supabase Python client for database operations

### Frontend (`/frontend`)
- `src/components/Dashboard.jsx` - Main dashboard with Focus/Upcoming panels, stats bar, filters, and live polling during sync
- `src/components/AssignmentCard.jsx` - Assignment card with status dropdown and quick actions
- `src/components/AssignmentDetail.jsx` - Modal for viewing/editing assignment details (estimated time, planned start/end, notes)
- `src/components/SyncButton.jsx` - Sync trigger with status polling, last-sync display, and stale indicator
- `src/components/LoginPage.jsx` - BYU browser-based authentication flow
- `src/components/Toast.jsx` - Toast notification system
- `src/config/api.js` - API base URL configuration
- Fetches from backend API, not directly from Supabase

### Database Schema
Table: `assignments`
- `id`, `title`, `course_name`, `due_date`, `description`, `link`, `status`
- `is_modified`, `last_scraped_at`, `learning_suite_url`, `assignment_type`, `ls_cid`
- `estimated_minutes`, `planned_start`, `planned_end`, `notes`

Valid status values: `newly_assigned`, `not_started`, `in_progress`, `submitted`, `unavailable`

Table: `sync_metadata`
- `last_sync_at`, `last_sync_status`, `last_sync_summary`, `last_sync_error`

## Environment Variables

Backend `.env` requires:
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_KEY` - Supabase API key
- `CORS_ORIGIN` - (optional) Comma-separated allowed origins, defaults to `http://localhost:5173`

Frontend `.env` (optional):
- `VITE_API_URL` - Backend API URL, defaults to `http://localhost:8000`

## Key Details

- Frontend runs on port 5173, backend on port 8000
- CORS origin is configurable via `CORS_ORIGIN` env var (defaults to localhost:5173)
- Use `python3` (not `python`) — this macOS environment has no `python` alias
- Scraper maps Learning Suite button text ("begin", "continue", "graded") to assignment statuses
- Database migrations in `/backend/migrations/`
- All scraped dates are localized to `America/Denver` (Mountain Time) via `zoneinfo.ZoneInfo` before storing as ISO strings with offset
- All internal timestamps (`last_scraped_at`, sync metadata, task timestamps) use `datetime.now(timezone.utc)`
- During sync, Dashboard polls `GET /assignments` every 5 seconds so assignments appear in real-time as each course is scraped
- Authentication uses a browser-based flow: backend opens a visible Chrome window, user logs in to BYU CAS + Duo, then the authenticated Selenium session is reused for scraping
- Pre-existing ESLint warning in `App.jsx` (variable used before declaration) — not a bug, React hoists function declarations
