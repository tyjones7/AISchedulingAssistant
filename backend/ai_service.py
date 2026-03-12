"""
AI Service for CampusAI

Manages Groq API client and provides public functions:
  - generate_suggestions(): batch priority scoring for active assignments
  - generate_briefing(): natural-language daily plan summary
  - generate_ai_schedule(): AI-powered time-block schedule using pre-computed free slots
  - chat_stream(): streaming conversational assistant (yields delta strings)
  - extract_plan(): structured plan extraction from a conversation

Follows the module-level singleton pattern used throughout this project
(see auth_store.py). The Groq client is initialized lazily on first call.
"""

import os
import json
import logging
import threading
from datetime import date, datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Model constants ────────────────────────────────────────────────────────────
_FAST_MODEL = "llama-3.1-8b-instant"       # batch scoring, plan extraction
_CHAT_MODEL = "llama-3.3-70b-versatile"    # chat, briefing, AI scheduling (higher quality)

# ── Groq client singleton (lazy init) ─────────────────────────────────────────
_groq_client = None
_groq_lock = threading.Lock()


def _get_groq_client():
    """Return the shared Groq client, initializing it on first call."""
    global _groq_client

    if _groq_client is not None:
        return _groq_client

    with _groq_lock:
        if _groq_client is not None:
            return _groq_client

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to backend/.env and restart the server."
            )

        try:
            from groq import Groq
            _groq_client = Groq(api_key=api_key)
            logger.info("Groq client initialized")
            return _groq_client
        except ImportError:
            raise RuntimeError("groq package not installed. Run: pip install groq")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Groq client: {e}")


# ── Shared context builders ────────────────────────────────────────────────────

def _build_profile_context(prefs: Optional[dict]) -> str:
    """Format user preferences + student context into a natural-language profile."""
    if not prefs:
        return ""

    study_time_labels = {
        "morning": "mornings (before noon)",
        "afternoon": "afternoons (noon–5 pm)",
        "evening": "evenings (5–9 pm)",
        "night": "late at night (9 pm+)",
    }
    work_style_labels = {
        "spread_out": "spread work across multiple shorter sessions",
        "batch": "knock out work in one long sitting",
    }
    involvement_labels = {
        "proactive": "proactive — always suggest plans and check in automatically",
        "balanced": "balanced — suggest plans when deadlines are approaching",
        "prompt_only": "prompt-only — only give advice when directly asked",
    }

    lines = ["\nStudent profile:"]
    study_time = prefs.get("study_time", "evening")
    lines.append(f"  - Best study time: {study_time_labels.get(study_time, study_time)}")
    session_len = prefs.get("session_length_minutes", 60)
    lines.append(f"  - Preferred session length: {session_len} minutes")
    advance = prefs.get("advance_days", 2)
    lines.append(f"  - Likes to start assignments {advance} day(s) before the deadline")
    work_style = prefs.get("work_style", "spread_out")
    lines.append(f"  - Work style: {work_style_labels.get(work_style, work_style)}")
    involvement = prefs.get("involvement_level", "balanced")
    lines.append(f"  - AI involvement preference: {involvement_labels.get(involvement, involvement)}")

    schedule = prefs.get("weekly_schedule") or []
    if schedule:
        lines.append("  - Weekly class/busy schedule:")
        for block in schedule:
            day = block.get("day", "")
            label = block.get("label", "")
            start = block.get("start", "")
            end = block.get("end", "")
            if day and start and end:
                lines.append(f"      • {day}: {start}–{end}" + (f" ({label})" if label else ""))

    # Persistent student context — grows from past conversations
    student_context = (prefs.get("student_context") or "").strip()
    if student_context:
        lines.append(f"\nWhat I know about this student from past conversations:\n  {student_context}")

    lines.append("\nUse this profile to tailor all scheduling advice and time block suggestions.")
    return "\n".join(lines)


def _relative_due(due_iso: Optional[str]) -> str:
    """Convert an ISO due_date string to a human-readable relative label."""
    if not due_iso:
        return "no due date"
    try:
        due_dt = datetime.fromisoformat(due_iso.replace("Z", "+00:00"))
        diff = (due_dt.date() - date.today()).days
        if diff < 0:
            return f"OVERDUE by {abs(diff)} day(s)"
        if diff == 0:
            return "due TODAY"
        if diff == 1:
            return "due TOMORROW"
        return f"due in {diff} day(s) ({due_dt.strftime('%b %d')})"
    except (ValueError, TypeError):
        return f"due {due_iso}"


def _build_assignment_context(assignments: list[dict]) -> str:
    """Format assignments into a concise numbered list for prompt injection."""
    today = date.today()
    lines = [f"Today is {today.strftime('%A, %B %d, %Y')}."]
    lines.append(f"The student has {len(assignments)} active assignment(s):\n")
    for a in assignments:
        title = a.get("title", "Untitled")
        course = a.get("course_name", "Unknown")
        status = a.get("status", "not_started")
        due_label = _relative_due(a.get("due_date"))
        est = a.get("estimated_minutes")
        est_str = f", est. {est} min" if est else " [NO TIME ESTIMATE — ask student]"
        notes = (a.get("notes") or "").strip()
        notes_str = f', notes: "{notes[:80]}"' if notes else ""
        atype = a.get("assignment_type") or ""
        type_str = f" [{atype}]" if atype and atype != "assignment" else ""
        task_type = a.get("task_type") or ""
        ttype_str = f" [task:{task_type}]" if task_type and task_type != "assignment" else ""
        pts = a.get("point_value")
        pts_str = f", {pts:g} pts" if pts is not None else ""
        desc = (a.get("description") or "").strip()
        desc_str = f'\n      Description: "{desc[:200]}"' if desc else ""
        aid = a.get("id", "")
        lines.append(
            f'  - ID:{aid} | "{title}"{type_str}{ttype_str} ({course}) | {status} | {due_label}{pts_str}{est_str}{notes_str}{desc_str}'
        )
    return "\n".join(lines)


def _build_schedule_context(time_blocks: list[dict]) -> str:
    """Format the current week's time blocks into a readable schedule for the chat prompt."""
    if not time_blocks:
        return "\nNo study blocks are currently scheduled for this week."

    # Group by date
    by_date: dict[str, list[dict]] = {}
    for b in time_blocks:
        d = b.get("date", "")
        by_date.setdefault(d, []).append(b)

    today_str = date.today().isoformat()
    lines = ["\nCurrent week's study schedule (already planned):"]
    for date_str in sorted(by_date.keys()):
        day_dt = datetime.strptime(date_str, "%Y-%m-%d")
        is_today = date_str == today_str
        day_label = day_dt.strftime("%A %b %d") + (" (TODAY)" if is_today else "")
        day_lines = []
        for b in sorted(by_date[date_str], key=lambda x: x.get("start_time", "")):
            asgn = b.get("assignments") or {}
            title = b.get("label") or asgn.get("title") or "Study block"
            status = b.get("status", "planned")
            try:
                s = datetime.fromisoformat(b["start_time"].replace("Z", "+00:00"))
                e = datetime.fromisoformat(b["end_time"].replace("Z", "+00:00"))
                from zoneinfo import ZoneInfo
                MOUNTAIN = ZoneInfo("America/Denver")
                s = s.astimezone(MOUNTAIN)
                e = e.astimezone(MOUNTAIN)
                time_str = f"{s.strftime('%-I:%M%p').lower()}–{e.strftime('%-I:%M%p').lower()}"
                dur_min = int((e - s).total_seconds() / 60)
                dur_str = f"{dur_min}min"
            except Exception:
                time_str = "?"
                dur_str = ""
            status_str = f" [{status}]" if status != "planned" else ""
            day_lines.append(f"    • {time_str} ({dur_str}): {title}{status_str}")
        lines.append(f"  {day_label}:")
        lines.extend(day_lines)

    lines.append(
        "\nIf the student asks to adjust the schedule, reference these specific blocks. "
        "Suggest rescheduling by day and time, then output an updated <plan> block."
    )
    return "\n".join(lines)


# ── Prompt templates ───────────────────────────────────────────────────────────

_SUGGESTIONS_SYSTEM = """\
You are an academic scheduling assistant for BYU students.
Analyze the student's active assignments and score each one.

Priority scoring rules (1–10):
- 10 = most urgent (overdue + not started, or due today with no estimated time)
- 7–9 = high (due tomorrow or within 2 days, or overdue but already in progress)
- 4–6 = medium (due this week, some work started or reasonable time available)
- 1–3 = low (due next week or later, plenty of time)

For suggested_start: recommend a specific YYYY-MM-DD date.
  - Overdue → today
  - Due today/tomorrow → today
  - Due within a week → 2–3 days before due date
  - Due later → about half the remaining time before due

For estimated_minutes: provide a realistic estimate if not already set (null means not set).
For rationale: one sentence, max 100 characters, explaining the score/timing.

Respond ONLY with valid JSON. No markdown, no code fences.
Return a top-level JSON object with a "suggestions" key containing an array.
Each item must have exactly: assignment_id, priority_score (int), suggested_start (YYYY-MM-DD or null), rationale (string), estimated_minutes (int or null).

Example:
{"suggestions":[{"assignment_id":"abc-123","priority_score":9,"suggested_start":"2026-02-19","rationale":"Overdue and not started \u2014 do this first.","estimated_minutes":60}]}"""

_BRIEFING_SYSTEM = """\
You are CampusAI, a friendly academic scheduling assistant for BYU students.
Write a concise daily briefing (2–4 sentences) for the student based on their assignments and today's scheduled study blocks.

Rules:
- Lead with what they should do TODAY specifically (name the assignment and ideally the time)
- Mention the most urgent item(s) and why
- Be encouraging but honest about deadlines
- Do NOT use bullet points or headers — write flowing sentences
- Keep it under 80 words total"""

_SCHEDULE_SYSTEM = """\
You are an expert academic scheduling assistant for BYU students.
Your job: given a student's free time slots and active assignments, build the optimal weekly study schedule.

Scheduling rules:
1. Most urgent first (soonest deadline, highest point value)
2. Schedule complex tasks (essays, problem sets, exam prep) during the student's best focus hours
3. Respect the student's preferred session length — split larger tasks across multiple blocks
4. Leave buffer before deadlines — do NOT schedule work the same day as the deadline if avoidable
5. If work_style is "batch", prefer fewer longer sessions; if "spread_out", prefer shorter sessions on more days
6. Do NOT schedule past a task's due date
7. Minimum block size: 20 minutes. Do not create micro-sessions.
8. Use realistic time estimates — if no estimate is provided, make a reasonable one based on task type

Output a JSON object with two keys:
  "blocks": array of scheduled blocks
  "overbooked": array of assignment titles that couldn't fit this week

Each block in "blocks" must have EXACTLY:
  - assignment_id: exact UUID string from the input
  - date: "YYYY-MM-DD"
  - start_time: "HH:MM" (24-hour, Mountain Time)
  - end_time: "HH:MM" (24-hour, Mountain Time)
  - label: short activity label, e.g. "Stats HW 5 – Session 1" or "Econ Essay – Outline"

Respond ONLY with valid JSON. No markdown, no explanation, no code fences."""

_BRIEFING_SYSTEM = """\
You are CampusAI, a friendly academic scheduling assistant for BYU students.
Write a concise daily briefing (2–4 sentences) for the student based on their assignments and today's schedule.

Rules:
- Lead with what they should do TODAY specifically (name the assignment and ideally the scheduled time if blocks exist)
- Mention the most urgent item(s) and why
- Be encouraging but honest about deadlines
- Do NOT use bullet points or headers — write flowing sentences
- Keep it under 80 words total"""

_CHAT_SYSTEM_TEMPLATE = """\
You are CampusAI, a friendly and practical academic scheduling assistant for BYU students.
You have full context of the student's assignments, schedule, and preferences.

{context}

{schedule_context}

Your role:
- Help decide what to work on and when
- Give concrete, actionable advice (not vague platitudes)
- Be encouraging but honest about deadlines
- Keep responses concise (2–5 sentences for simple questions)
- When the student mentions something important (e.g. an exam date, how long a course's work actually takes), note it for context

Clarifying questions:
- For any assignment with [NO TIME ESTIMATE — ask student], ask one brief question to understand the scope.
  For example: "What does the assignment involve — is it a paper, problem set, or something else? Roughly how long do you expect it to take?"
  Only ask about one unknown per message to avoid overwhelming the student.

When you build or adjust a study plan, lay it out day by day with specific times.
At the end of any response that includes a concrete schedule with specific dates AND times, append a machine-readable block in EXACTLY this format (no spaces around tags):
<plan>{{"blocks":[{{"assignment_id":"<uuid>","date":"YYYY-MM-DD","start_time":"HH:MM","end_time":"HH:MM","label":"Short label"}}]}}</plan>

Guidelines for the <plan> block:
- Use 24-hour HH:MM times in Mountain Time
- Only include it when giving a concrete schedule with specific dates and times
- Do NOT include it for general advice, single-question answers, or vague "start Monday" suggestions
- When adjusting an existing schedule, include ALL blocks for the week (not just the changed ones)

Context learning:
When the student tells you something specific and durable that would improve future scheduling
(e.g. an exam date, how long a course's work actually takes, a recurring commitment, a difficulty level),
append a <context> tag at the very end of your response (after the <plan> block if any):
<context>One-sentence summary of what you learned, e.g. "Stats 121 midterm is March 20. ECON essays take ~3h not 60 min."</context>
Only include <context> when you learn something genuinely new and useful. Do NOT include it for every message.

Do NOT mention that you are Groq or any specific AI model. You are CampusAI."""

_EXTRACT_SYSTEM_TEMPLATE = """\
You are a data extraction assistant. Given a conversation between a student and CampusAI,
extract the study schedule (if any) into a structured JSON object.

The student has these assignments (use these exact IDs):
{assignment_list}

Return a JSON object with a "blocks" key containing an array.
Each item: {{"assignment_id": "<exact UUID from above>", "date": "YYYY-MM-DD", "start_time": "HH:MM", "end_time": "HH:MM", "label": "short label"}}.
- start_time and end_time are in 24-hour Mountain Time
- Match assignment titles from the conversation to IDs above (fuzzy match is fine)
- Only include blocks that have a specific date AND time mentioned in the conversation
- If only a date (no time) was mentioned, use "09:00" as start and add estimated_minutes for end
- If no schedule is found, return {{"blocks": []}}

Respond ONLY with valid JSON. No markdown, no explanation."""


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_suggestions(assignments: list[dict], prefs: Optional[dict] = None) -> list[dict]:
    """Generate AI priority suggestions for a batch of active assignments.

    Uses llama-3.1-8b-instant (fast) for cost efficiency.

    Returns:
        List of dicts with keys: assignment_id, priority_score, suggested_start,
        rationale, estimated_minutes
    """
    if not assignments:
        return []

    client = _get_groq_client()
    user_msg = (
        _build_assignment_context(assignments)
        + _build_profile_context(prefs)
        + "\n\nScore every assignment listed above and return the JSON."
    )

    logger.info(f"[ai_service] generate_suggestions: {len(assignments)} assignment(s)")

    try:
        resp = client.chat.completions.create(
            model=_FAST_MODEL,
            messages=[
                {"role": "system", "content": _SUGGESTIONS_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=2048,
        )
        raw = resp.choices[0].message.content.strip()
        logger.debug(f"[ai_service] suggestions raw: {raw[:300]}")

        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            for key in ("suggestions", "assignments", "results", "data"):
                if key in parsed and isinstance(parsed[key], list):
                    return parsed[key]
            return next((v for v in parsed.values() if isinstance(v, list)), [])
        if isinstance(parsed, list):
            return parsed
        raise ValueError(f"Unexpected response structure: {type(parsed)}")

    except json.JSONDecodeError as e:
        logger.error(f"[ai_service] suggestions JSON parse error: {e}")
        raise ValueError(f"AI returned unparseable JSON: {e}")
    except Exception:
        raise


def generate_briefing(
    assignments: list[dict],
    prefs: Optional[dict] = None,
    time_blocks: Optional[list[dict]] = None,
) -> str:
    """Generate a short natural-language daily briefing.

    Uses llama-3.3-70b-versatile for higher quality prose.
    Optionally accepts today's time_blocks to make the briefing more specific.

    Returns:
        2–4 sentence plain-text briefing string
    """
    client = _get_groq_client()
    context = _build_assignment_context(assignments) + _build_profile_context(prefs)
    if time_blocks:
        context += _build_schedule_context(time_blocks)

    logger.info(f"[ai_service] generate_briefing: {len(assignments)} assignment(s)")

    resp = client.chat.completions.create(
        model=_CHAT_MODEL,
        messages=[
            {"role": "system", "content": _BRIEFING_SYSTEM},
            {"role": "user", "content": context + "\n\nWrite the daily briefing now."},
        ],
        temperature=0.5,
        max_tokens=300,
    )
    briefing = resp.choices[0].message.content.strip()
    logger.info(f"[ai_service] briefing: {len(briefing)} chars")
    return briefing


def generate_ai_schedule(
    assignments: list[dict],
    free_slots_text: str,
    prefs: Optional[dict] = None,
) -> dict:
    """Generate an AI-powered study schedule from pre-computed free time slots.

    Uses llama-3.3-70b-versatile for high-quality scheduling decisions.

    Args:
        assignments: Active assignments with id, title, course_name, due_date,
                     estimated_minutes, task_type, status
        free_slots_text: Pre-formatted string describing available time windows
                         (produced by schedule_service.format_free_slots_for_ai)
        prefs: User preferences dict

    Returns:
        {
            "blocks": [{"assignment_id", "date", "start_time", "end_time", "label"}],
            "overbooked": ["Assignment title", ...]  # titles that didn't fit
        }

    Raises:
        RuntimeError, ValueError, Exception
    """
    if not assignments:
        return {"blocks": [], "overbooked": []}

    client = _get_groq_client()

    # Build assignment list with urgency context
    today = date.today()
    asgn_lines = [f"Today is {today.strftime('%A, %B %d, %Y')}.\n\nASSIGNMENTS TO SCHEDULE:"]
    for a in assignments:
        title = a.get("title", "Untitled")
        course = a.get("course_name", "")
        due_label = _relative_due(a.get("due_date"))
        est = a.get("estimated_minutes")
        est_str = f"{est} min estimated" if est else "no time estimate (use judgment)"
        pts = a.get("point_value")
        pts_str = f", {pts:g} pts" if pts is not None else ""
        task_type = a.get("task_type") or a.get("assignment_type") or "assignment"
        status = a.get("status", "not_started")
        aid = a.get("id", "")
        asgn_lines.append(
            f'  - ID:{aid} | "{title}" [{task_type}] ({course}) | {status} | {due_label}{pts_str} | {est_str}'
        )

    assignment_context = "\n".join(asgn_lines)
    profile_context = _build_profile_context(prefs)

    user_msg = f"{assignment_context}\n\n{free_slots_text}{profile_context}\n\nBuild the optimal study schedule for this week."

    logger.info(f"[ai_service] generate_ai_schedule: {len(assignments)} assignments")

    try:
        resp = client.chat.completions.create(
            model=_CHAT_MODEL,
            messages=[
                {"role": "system", "content": _SCHEDULE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=4096,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip markdown code fences if model adds them despite instructions
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        logger.debug(f"[ai_service] ai_schedule raw: {raw[:500]}")

        parsed = json.loads(raw)
        blocks = parsed.get("blocks", [])
        overbooked = parsed.get("overbooked", [])
        logger.info(f"[ai_service] ai_schedule: {len(blocks)} blocks, {len(overbooked)} overbooked")
        return {"blocks": blocks, "overbooked": overbooked}

    except json.JSONDecodeError as e:
        logger.error(f"[ai_service] ai_schedule JSON parse error: {e}\nraw: {raw[:500]}")
        raise ValueError(f"AI returned unparseable schedule JSON: {e}")
    except Exception:
        raise


def chat_stream(
    messages: list[dict],
    assignments: list[dict],
    prefs: Optional[dict] = None,
    time_blocks: Optional[list[dict]] = None,
):
    """Yield delta strings from a streaming Groq chat completion.

    Uses llama-3.3-70b-versatile with stream=True.
    Injects current schedule (time_blocks) into the system prompt so the AI
    knows what is already planned and can adjust it intelligently.

    Args:
        messages: Conversation history [{role, content}]
        assignments: Active assignments for context injection
        prefs: User preferences
        time_blocks: Current week's time blocks for schedule context

    Yields:
        str — each text chunk from the model
    """
    client = _get_groq_client()
    context = _build_assignment_context(assignments) + _build_profile_context(prefs)
    schedule_context = _build_schedule_context(time_blocks or [])
    system_prompt = _CHAT_SYSTEM_TEMPLATE.format(
        context=context,
        schedule_context=schedule_context,
    )

    groq_messages = [{"role": "system", "content": system_prompt}] + messages

    logger.info(
        f"[ai_service] chat_stream: {len(messages)} msg(s), "
        f"{len(assignments)} assignment(s), "
        f"{len(time_blocks or [])} time block(s) in context"
    )

    stream = client.chat.completions.create(
        model=_CHAT_MODEL,
        messages=groq_messages,
        temperature=0.7,
        max_tokens=1500,
        stream=True,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def extract_plan(conversation_messages: list[dict], assignments: list[dict]) -> list[dict]:
    """Extract a structured study plan (with times) from a conversation.

    Uses llama-3.1-8b-instant (fast, deterministic) to parse the plan
    discussed in the conversation.

    Returns:
        List of dicts: [{
            assignment_id: str,
            date: str (YYYY-MM-DD),
            start_time: str (HH:MM, 24h Mountain Time),
            end_time: str (HH:MM),
            label: str
        }]
        Empty list if no plan found.
    """
    client = _get_groq_client()

    assignment_list = "\n".join(
        f'  - ID:{a["id"]} | "{a.get("title","")}" ({a.get("course_name","")}) | est. {a.get("estimated_minutes","?")} min'
        for a in assignments
    )
    system_prompt = _EXTRACT_SYSTEM_TEMPLATE.format(assignment_list=assignment_list)

    transcript_lines = []
    for m in conversation_messages:
        role = "Student" if m["role"] == "user" else "CampusAI"
        transcript_lines.append(f"{role}: {m['content']}")
    transcript = "\n\n".join(transcript_lines)

    logger.info(f"[ai_service] extract_plan: {len(conversation_messages)} messages")

    try:
        resp = client.chat.completions.create(
            model=_FAST_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript},
            ],
            temperature=0,
            max_tokens=2048,
        )
        raw = resp.choices[0].message.content.strip()
        logger.debug(f"[ai_service] extract_plan raw: {raw[:300]}")

        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "blocks" in parsed:
            return parsed["blocks"]
        # Backward-compatible: old format used "assignments" key with planned_start
        if isinstance(parsed, dict) and "assignments" in parsed:
            return parsed["assignments"]
        if isinstance(parsed, list):
            return parsed
        return []

    except json.JSONDecodeError as e:
        logger.error(f"[ai_service] extract_plan JSON parse error: {e}")
        raise ValueError(f"AI returned unparseable plan JSON: {e}")
    except Exception:
        raise
