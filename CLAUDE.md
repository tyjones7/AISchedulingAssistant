# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Scheduling Assistant for BYU students. Scrapes assignments from BYU Learning Suite and displays them in a Kanban board interface. Uses Supabase (PostgreSQL) as the database.

## Common Commands

### Backend (FastAPI)
```bash
cd backend
python -m uvicorn main:app --reload    # Start dev server on localhost:8000
python main.py                          # Alternative: run directly
python scraper/learning_suite_scraper.py  # Run the Learning Suite scraper
python test_scraper.py --debug          # Test scraper with verbose logging
python seed.py                          # Seed database with sample assignments
python diagnose_db.py                   # View database contents by course
python clear_assignments.py             # Clear all assignments from database
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
React Frontend (Kanban Board) ← FastAPI Backend ←─────────────┘
```

### Backend (`/backend`)
- `main.py` - FastAPI app with REST endpoints: GET `/assignments`, PATCH `/assignments/{id}`
- `scraper/learning_suite_scraper.py` - Selenium scraper for BYU Learning Suite with CAS auth and Duo MFA support (2-minute manual timeout)
- Uses Supabase Python client for database operations

### Frontend (`/frontend`)
- `src/components/Dashboard.jsx` - Main Kanban board with 5 status columns
- `src/components/AssignmentCard.jsx` - Assignment card with status dropdown
- Fetches from backend API, not directly from Supabase

### Database Schema
Table: `assignments`
- `id`, `title`, `course_name`, `due_date`, `description`, `link`, `status`
- `is_modified`, `last_scraped_at`, `learning_suite_url`, `assignment_type`

Valid status values: `newly_assigned`, `not_started`, `in_progress`, `submitted`, `unavailable`

## Environment Variables

Backend `.env` requires:
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_KEY` - Supabase API key
- `BYU_NETID` - For Learning Suite authentication
- `BYU_PASSWORD` - For Learning Suite authentication

## Key Details

- Frontend runs on port 5173, backend on port 8000
- CORS configured for localhost:5173 only
- Scraper maps Learning Suite button text ("begin", "continue", "graded") to assignment statuses
- Database migrations in `/backend/migrations/`
