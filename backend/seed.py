"""
Seed the database with demo assignments and preferences for a specific user.

Usage:
    python3 seed.py <your-email>

Find your email in Supabase Auth dashboard, or just use the email you signed up with.
"""
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

MT = ZoneInfo("America/Denver")
today = datetime.now(MT)


def due(days_offset: int, hour: int = 23, minute: int = 59) -> str:
    d = today + timedelta(days=days_offset)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()


ASSIGNMENTS = [
    # ── STRAT 490R ──────────────────────────────────────────────────────────
    {
        "title": "Case Study: Netflix Strategy Analysis",
        "course_name": "STRAT 490R – AI & Business",
        "due_date": due(1, 23, 59),
        "description": "Analyze Netflix's pivot to AI-driven content recommendation. 4–6 pages. Use the Porter Five Forces + Jobs-to-be-Done frameworks from Week 8.",
        "status": "in_progress",
        "assignment_type": "online_upload",
        "point_value": 100,
        "estimated_minutes": 180,
        "notes": "Focus the analysis on AI personalization as the core differentiator. Coordinate with Maya on the financial data section.",
        "source": "canvas",
        "canvas_id": 900001,
    },
    {
        "title": "Reading: Ch. 9 – Competitive Dynamics",
        "course_name": "STRAT 490R – AI & Business",
        "due_date": due(2, 23, 59),
        "description": "Read pages 210–245. Come prepared to discuss the hypercompetition framework.",
        "status": "newly_assigned",
        "assignment_type": "not_graded",
        "point_value": 0,
        "estimated_minutes": 60,
        "notes": "",
        "source": "canvas",
        "canvas_id": 900002,
    },
    {
        "title": "Weekly Discussion Post",
        "course_name": "STRAT 490R – AI & Business",
        "due_date": due(4, 23, 59),
        "description": "Post a 200-word response to this week's prompt: 'Where does AI create sustainable competitive advantage vs. temporary efficiency gains?'",
        "status": "not_started",
        "assignment_type": "discussion_topic",
        "point_value": 25,
        "estimated_minutes": 45,
        "notes": "",
        "source": "canvas",
        "canvas_id": 900005,
    },
    # ── ENT 401 ─────────────────────────────────────────────────────────────
    {
        "title": "Venture Pitch Deck",
        "course_name": "ENT 401 – New Ventures",
        "due_date": due(3, 17, 0),
        "description": "Submit your 10-slide pitch deck via Canvas before class at 5 PM. Must include problem, solution, market size, traction, and ask.",
        "status": "in_progress",
        "assignment_type": "online_upload",
        "point_value": 150,
        "estimated_minutes": 240,
        "notes": "Need to finalize the market size slide — check the Gartner report Jake shared.",
        "source": "canvas",
        "canvas_id": 900003,
    },
    {
        "title": "Group Project: Market Entry Strategy",
        "course_name": "ENT 401 – New Ventures",
        "due_date": due(10, 23, 59),
        "description": "Team deliverable: 15-page go-to-market strategy report for your chosen startup concept.",
        "status": "in_progress",
        "assignment_type": "online_upload",
        "point_value": 200,
        "estimated_minutes": 300,
        "notes": "Team sync scheduled for Saturday. I'm responsible for competitive landscape section.",
        "source": "canvas",
        "canvas_id": 900007,
    },
    # ── ECON 382 ─────────────────────────────────────────────────────────────
    {
        "title": "Problem Set 4: Game Theory",
        "course_name": "ECON 382 – Microeconomics",
        "due_date": due(4, 23, 59),
        "description": "Problems 1–8 on Nash equilibrium and dominant strategies. Show all work.",
        "status": "not_started",
        "assignment_type": "online_upload",
        "point_value": 50,
        "estimated_minutes": 120,
        "notes": "Review Nash equilibrium examples from Tuesday's lecture first.",
        "source": "canvas",
        "canvas_id": 900004,
    },
    {
        "title": "Midterm Exam",
        "course_name": "ECON 382 – Microeconomics",
        "due_date": due(12, 10, 0),
        "description": "Covers chapters 1–9: supply/demand, elasticity, game theory, market structures. Bring your BYU ID. 90 minutes.",
        "status": "not_started",
        "assignment_type": "none",
        "point_value": 200,
        "estimated_minutes": 360,
        "notes": "Plan 3 study sessions: review notes, practice problems, mock exam.",
        "source": "canvas",
        "canvas_id": 900008,
    },
    # ── ACC 310 ──────────────────────────────────────────────────────────────
    {
        "title": "Financial Statement Analysis",
        "course_name": "ACC 310 – Managerial Accounting",
        "due_date": due(7, 23, 59),
        "description": "Analyze Q3 financial statements for Apple and Microsoft. Calculate and compare key ratios: ROE, ROA, current ratio, debt-to-equity.",
        "status": "not_started",
        "assignment_type": "online_upload",
        "point_value": 75,
        "estimated_minutes": 150,
        "notes": "",
        "source": "canvas",
        "canvas_id": 900006,
    },
    # ── Submitted (past) ─────────────────────────────────────────────────────
    {
        "title": "LinkedIn Reflection Essay",
        "course_name": "BUS 301 – Professional Development",
        "due_date": due(-1, 23, 59),
        "description": "Reflect on your LinkedIn profile updates and networking outreach this semester.",
        "status": "submitted",
        "assignment_type": "online_upload",
        "point_value": 30,
        "estimated_minutes": 60,
        "notes": "",
        "source": "canvas",
        "canvas_id": 900009,
    },
    {
        "title": "Chapter 5 Quiz",
        "course_name": "ACC 310 – Managerial Accounting",
        "due_date": due(-3, 23, 59),
        "description": "10-question quiz on cost-volume-profit analysis.",
        "status": "submitted",
        "assignment_type": "online_quiz",
        "point_value": 25,
        "estimated_minutes": 30,
        "notes": "",
        "source": "canvas",
        "canvas_id": 900010,
    },
]

# Course colors — indices into WeeklyGrid PALETTE
COURSE_COLORS = {
    "STRAT 490R – AI & Business": 0,   # indigo
    "ENT 401 – New Ventures":     2,   # emerald
    "ECON 382 – Microeconomics":  3,   # amber
    "ACC 310 – Managerial Accounting": 4,  # red
    "BUS 301 – Professional Development": 5,  # purple
}

USER_PREFS = {
    "study_time": "evening",
    "session_length_minutes": 90,
    "advance_days": 3,
    "work_style": "spread_out",
    "involvement_level": "balanced",
    "work_start": "08:30",
    "work_end": "23:00",
    "student_context": (
        "Senior BYU business major finishing capstone semester. "
        "Work ~10 hrs/week as a part-time strategy consultant. "
        "Prefer 90-minute deep-focus blocks with short breaks. "
        "Strongest in strategy and writing; weaker in financial modeling — "
        "accounting assignments take longer than expected."
    ),
    "course_colors": COURSE_COLORS,
    "weekly_schedule": [
        {"days": ["Tuesday", "Thursday"], "label": "STRAT 490R", "start": "11:00", "end": "12:15"},
        {"days": ["Monday", "Wednesday", "Friday"], "label": "ECON 382", "start": "10:00", "end": "10:50"},
        {"days": ["Tuesday", "Thursday"], "label": "ENT 401", "start": "14:00", "end": "15:15"},
        {"days": ["Monday", "Wednesday"], "label": "ACC 310", "start": "13:00", "end": "13:50"},
        {"days": ["Friday"], "label": "Consulting project", "start": "14:00", "end": "17:00"},
    ],
}


def get_user_id(email: str) -> str:
    """Look up user_id from Supabase Auth by email."""
    result = supabase.auth.admin.list_users()
    for user in result:
        if hasattr(user, '__iter__'):
            for u in user:
                if hasattr(u, 'email') and u.email == email:
                    return u.id
        elif hasattr(result, 'users'):
            for u in result.users:
                if u.email == email:
                    return u.id
    raise ValueError(f"No user found with email: {email}")


def seed_database(user_id: str):
    print(f"Seeding demo data for user {user_id[:8]}...")

    # Clear existing demo assignments (canvas_id 900001–900010)
    supabase.table("assignments").delete().gte("canvas_id", 900001).lte("canvas_id", 900010).execute()
    print("  Cleared old demo assignments.")

    for a in ASSIGNMENTS:
        supabase.table("assignments").insert({**a, "user_id": user_id}).execute()
        print(f"  Added: {a['title']}")

    # Upsert user preferences
    supabase.table("user_preferences").upsert(
        {**USER_PREFS, "user_id": user_id},
        on_conflict="user_id"
    ).execute()
    print("  Set user preferences (study time, course colors, weekly schedule, student context).")

    print(f"\nDone! {len(ASSIGNMENTS)} assignments + preferences seeded.")
    print("Tip: open the app and click 'Generate plan' on the AI sidebar to see the schedule.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 seed.py <your-email>")
        print("Example: python3 seed.py tyler@byu.edu")
        sys.exit(1)

    email = sys.argv[1]
    try:
        uid = get_user_id(email)
        print(f"Found user: {email} ({uid[:8]}...)")
        seed_database(uid)
    except ValueError as e:
        print(f"Error: {e}")
        print("Make sure you've signed up at the app first.")
        sys.exit(1)
