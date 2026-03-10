"""
Seed the database with demo assignments for a specific user.

Usage:
    python3 seed.py <your-email>

Find your email in Supabase Auth dashboard, or just use the email you signed up with.
"""
import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

today = datetime.now()

ASSIGNMENTS = [
    {
        "title": "Case Study: Netflix Strategy Analysis",
        "course_name": "STRAT 490R – AI & Business",
        "due_date": (today + timedelta(days=1)).isoformat(),
        "description": "Analyze Netflix's pivot to AI-driven content recommendation. 4-6 pages.",
        "status": "in_progress",
        "assignment_type": "online_upload",
        "point_value": 100,
        "source": "canvas",
        "canvas_id": 900001,
    },
    {
        "title": "Reading: Ch. 9 – Competitive Dynamics",
        "course_name": "STRAT 490R – AI & Business",
        "due_date": (today + timedelta(days=2)).isoformat(),
        "description": "Read pages 210–245 and come prepared to discuss.",
        "status": "newly_assigned",
        "assignment_type": "not_graded",
        "point_value": 20,
        "source": "canvas",
        "canvas_id": 900002,
    },
    {
        "title": "Entrepreneurship Venture Pitch Deck",
        "course_name": "ENT 401 – New Ventures",
        "due_date": (today + timedelta(days=3)).isoformat(),
        "description": "Submit your 10-slide pitch deck via Canvas before class.",
        "status": "in_progress",
        "assignment_type": "online_upload",
        "point_value": 150,
        "source": "canvas",
        "canvas_id": 900003,
    },
    {
        "title": "Problem Set 4: Game Theory",
        "course_name": "ECON 382 – Microeconomics",
        "due_date": (today + timedelta(days=4)).isoformat(),
        "description": "Problems 1–8 on Nash equilibrium and dominant strategies.",
        "status": "not_started",
        "assignment_type": "online_upload",
        "point_value": 50,
        "source": "canvas",
        "canvas_id": 900004,
    },
    {
        "title": "Weekly Discussion Post",
        "course_name": "STRAT 490R – AI & Business",
        "due_date": (today + timedelta(days=5)).isoformat(),
        "description": "Post a 200-word response to this week's reading prompt by Thursday.",
        "status": "newly_assigned",
        "assignment_type": "discussion_topic",
        "point_value": 25,
        "source": "canvas",
        "canvas_id": 900005,
    },
    {
        "title": "Financial Statement Analysis",
        "course_name": "ACC 310 – Managerial Accounting",
        "due_date": (today + timedelta(days=7)).isoformat(),
        "description": "Analyze the Q3 financial statements for two competing firms.",
        "status": "not_started",
        "assignment_type": "online_upload",
        "point_value": 75,
        "source": "canvas",
        "canvas_id": 900006,
    },
    {
        "title": "Group Project: Market Entry Strategy",
        "course_name": "ENT 401 – New Ventures",
        "due_date": (today + timedelta(days=10)).isoformat(),
        "description": "Team deliverable: 15-page go-to-market strategy report.",
        "status": "in_progress",
        "assignment_type": "online_upload",
        "point_value": 200,
        "source": "canvas",
        "canvas_id": 900007,
    },
    {
        "title": "Midterm Exam",
        "course_name": "ECON 382 – Microeconomics",
        "due_date": (today + timedelta(days=12)).isoformat(),
        "description": "Covers chapters 1–8. Bring your BYU ID.",
        "status": "not_started",
        "assignment_type": "none",
        "point_value": 200,
        "source": "canvas",
        "canvas_id": 900008,
    },
    {
        "title": "LinkedIn Reflection Essay",
        "course_name": "BUS 301 – Professional Development",
        "due_date": (today - timedelta(days=1)).isoformat(),
        "description": "Reflect on your LinkedIn profile updates and networking outreach.",
        "status": "submitted",
        "assignment_type": "online_upload",
        "point_value": 30,
        "source": "canvas",
        "canvas_id": 900009,
    },
    {
        "title": "Chapter 5 Quiz",
        "course_name": "ACC 310 – Managerial Accounting",
        "due_date": (today - timedelta(days=3)).isoformat(),
        "description": "10-question quiz on cost-volume-profit analysis.",
        "status": "submitted",
        "assignment_type": "online_quiz",
        "point_value": 25,
        "source": "canvas",
        "canvas_id": 900010,
    },
]


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
    print(f"Seeding demo assignments for user {user_id[:8]}...")

    # Clear existing demo assignments (canvas_id 900001-900010)
    supabase.table("assignments").delete().gte("canvas_id", 900001).lte("canvas_id", 900010).execute()

    for a in ASSIGNMENTS:
        supabase.table("assignments").insert({**a, "user_id": user_id}).execute()
        print(f"  Added: {a['title']}")

    print(f"\nDone! Added {len(ASSIGNMENTS)} demo assignments.")
    print(f"Visit https://campusai-six.vercel.app to see them.")


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
        print("Make sure you've signed up at campusai-six.vercel.app first.")
        sys.exit(1)
