import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Calculate dates relative to today
today = datetime.now()

assignments = [
    {
        "title": "Problem Set 5: Integration Techniques",
        "course_name": "Calculus II",
        "due_date": (today - timedelta(days=2)).isoformat(),
        "description": "Complete problems 1-20 on integration by parts and substitution",
        "link": "https://canvas.example.com/calc2/ps5",
        "status": "submitted"
    },
    {
        "title": "Essay: Themes in Hamlet",
        "course_name": "English Literature",
        "due_date": (today + timedelta(days=1)).isoformat(),
        "description": "5-page analysis of major themes in Shakespeare's Hamlet",
        "link": "https://canvas.example.com/english/hamlet-essay",
        "status": "in_progress"
    },
    {
        "title": "Lab Report: Acid-Base Titration",
        "course_name": "Chemistry 101",
        "due_date": (today + timedelta(days=3)).isoformat(),
        "description": "Write up results from Tuesday's lab experiment",
        "link": None,
        "status": "not_started"
    },
    {
        "title": "Programming Assignment 3: Binary Trees",
        "course_name": "Computer Science 201",
        "due_date": (today + timedelta(days=5)).isoformat(),
        "description": "Implement BST insert, delete, and traversal methods",
        "link": "https://github.com/cs201/pa3",
        "status": "in_progress"
    },
    {
        "title": "Chapter 8 Reading Quiz",
        "course_name": "Psychology 101",
        "due_date": (today - timedelta(days=5)).isoformat(),
        "description": "Online quiz covering memory and cognition",
        "link": "https://canvas.example.com/psych/quiz8",
        "status": "submitted"
    },
    {
        "title": "Midterm Study Guide",
        "course_name": "Calculus II",
        "due_date": (today + timedelta(days=7)).isoformat(),
        "description": "Review all topics from chapters 6-9",
        "link": None,
        "status": "not_started"
    },
    {
        "title": "Group Presentation: Climate Change",
        "course_name": "Environmental Science",
        "due_date": (today + timedelta(days=10)).isoformat(),
        "description": "15-minute group presentation on climate change impacts",
        "link": "https://docs.google.com/presentation/climate-group",
        "status": "not_started"
    },
    {
        "title": "Short Story Analysis",
        "course_name": "English Literature",
        "due_date": (today + timedelta(days=2)).isoformat(),
        "description": "2-page analysis of 'The Lottery' by Shirley Jackson",
        "link": None,
        "status": "newly_assigned"
    },
]

def seed_database():
    print("Seeding database with sample assignments...")

    for assignment in assignments:
        result = supabase.table("assignments").insert(assignment).execute()
        print(f"  Added: {assignment['title']}")

    print(f"\nSuccessfully added {len(assignments)} assignments!")

if __name__ == "__main__":
    seed_database()
