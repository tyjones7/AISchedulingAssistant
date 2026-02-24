"""
AI Service for CampusAI

Manages Groq API client and provides four public functions:
  - generate_suggestions(): batch priority scoring for active assignments
  - generate_briefing(): natural-language daily plan summary
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
_CHAT_MODEL = "llama-3.3-70b-versatile"    # chat, briefing (higher quality)

# ── Groq client singleton (lazy init) ─────────────────────────────────────────
_groq_client = None
_groq_lock = threading.Lock()


def _get_groq_client():
    """Return the shared Groq client, initializing it on first call.

    Raises RuntimeError if GROQ_API_KEY is missing or groq is not installed.
    """
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
            raise RuntimeError(
                "groq package not installed. Run: pip install groq"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Groq client: {e}")


# ── Shared context builders ────────────────────────────────────────────────────

def _build_profile_context(prefs: Optional[dict]) -> str:
    """Format user preferences into a natural-language profile for prompts."""
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
    lines.append("Use this profile to tailor all scheduling advice and time block suggestions.")
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
        est_str = f", est. {est} min" if est else ""
        notes = (a.get("notes") or "").strip()
        notes_str = f', notes: "{notes[:80]}"' if notes else ""
        atype = a.get("assignment_type") or ""
        type_str = f" [{atype}]" if atype and atype != "assignment" else ""
        pts = a.get("point_value")
        pts_str = f", {pts:g} pts" if pts is not None else ""
        desc = (a.get("description") or "").strip()
        desc_str = f'\n      Description: "{desc[:200]}"' if desc else ""
        no_context = not desc and not est
        unknown_str = " [no description — ask student about this]" if no_context else ""
        aid = a.get("id", "")
        lines.append(
            f'  - ID:{aid} | "{title}"{type_str} ({course}) | {status} | {due_label}{pts_str}{est_str}{notes_str}{unknown_str}{desc_str}'
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
Write a concise daily briefing (2–4 sentences) for the student based on their assignments.

Rules:
- Lead with what they should do TODAY specifically (name the assignment)
- Mention the most urgent item(s) and why
- Be encouraging but honest about deadlines
- Do NOT use bullet points or headers — write flowing sentences
- Keep it under 80 words total"""

_CHAT_SYSTEM_TEMPLATE = """\
You are CampusAI, a friendly and practical academic scheduling assistant for BYU students.
You have full context of the student's current assignments.

{context}

Your role:
- Help decide what to work on and when
- Give concrete, actionable advice (not vague platitudes)
- Be encouraging but honest about deadlines
- Keep responses concise (2–5 sentences for simple questions)

Clarifying questions:
- For any assignment marked [no description — ask student about this], ask one brief question
  to understand it better before scheduling it. For example: "What does the '{title}' assignment
  involve — is it a paper, problem set, or something else? And roughly how long do you expect it
  to take?" Only ask about one unknown assignment per message to avoid overwhelming the student.
- Use what you learn to give better time estimates and scheduling advice.

When you build a study plan or weekly schedule, lay it out day by day.
At the end of any response that includes a specific study schedule or plan,
append a machine-readable block in EXACTLY this format (no spaces around tags):
<plan>{{"assignments":[{{"title":"Assignment Title","start":"YYYY-MM-DD"}}]}}</plan>

Only include the <plan> block when you are giving a concrete schedule with specific dates.
Do NOT include it for general advice or single-question answers.
Do NOT mention that you are Groq or any specific AI model. You are CampusAI."""

_EXTRACT_SYSTEM_TEMPLATE = """\
You are a data extraction assistant. Given a conversation between a student and CampusAI,
extract the study plan (if any) into a structured JSON object.

The student has these assignments (use these exact IDs):
{assignment_list}

Return a JSON object with an "assignments" key containing an array.
Each item: {{"assignment_id": "<exact UUID from above>", "planned_start": "YYYY-MM-DD"}}.
Match assignment titles from the conversation to IDs above (fuzzy match is fine).
Only include assignments that have a specific start date mentioned in the conversation.
If no plan is found, return {{"assignments": []}}.

Respond ONLY with valid JSON. No markdown, no explanation."""


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_suggestions(assignments: list[dict], prefs: Optional[dict] = None) -> list[dict]:
    """Generate AI priority suggestions for a batch of active assignments.

    Uses llama-3.1-8b-instant (fast) for cost efficiency.

    Returns:
        List of dicts with keys: assignment_id, priority_score, suggested_start,
        rationale, estimated_minutes

    Raises:
        RuntimeError: GROQ_API_KEY missing or groq not installed
        ValueError: Groq returned unparseable JSON
        Exception: Groq API errors (rate limit, auth, etc.) — re-raised
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
        # Unwrap if model returns {"suggestions": [...]}
        if isinstance(parsed, dict):
            for key in ("suggestions", "assignments", "results", "data"):
                if key in parsed and isinstance(parsed[key], list):
                    return parsed[key]
            # Fallback: first list value
            return next((v for v in parsed.values() if isinstance(v, list)), [])
        if isinstance(parsed, list):
            return parsed
        raise ValueError(f"Unexpected response structure: {type(parsed)}")

    except json.JSONDecodeError as e:
        logger.error(f"[ai_service] suggestions JSON parse error: {e}")
        raise ValueError(f"AI returned unparseable JSON: {e}")
    except Exception:
        raise


def generate_briefing(assignments: list[dict], prefs: Optional[dict] = None) -> str:
    """Generate a short natural-language daily briefing.

    Uses llama-3.3-70b-versatile for higher quality prose.

    Returns:
        2–4 sentence plain-text briefing string

    Raises:
        RuntimeError, Exception — same as generate_suggestions
    """
    client = _get_groq_client()
    context = _build_assignment_context(assignments) + _build_profile_context(prefs)

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


def chat_stream(messages: list[dict], assignments: list[dict], prefs: Optional[dict] = None):
    """Yield delta strings from a streaming Groq chat completion.

    Uses llama-3.3-70b-versatile with stream=True.
    Empty-string deltas are filtered out before yielding.

    Args:
        messages: Conversation history [{role, content}]
        assignments: Active assignments for context injection

    Yields:
        str — each text chunk from the model

    Raises:
        RuntimeError, Exception — same as generate_suggestions
    """
    client = _get_groq_client()
    context = _build_assignment_context(assignments) + _build_profile_context(prefs)
    system_prompt = _CHAT_SYSTEM_TEMPLATE.format(context=context)

    groq_messages = [{"role": "system", "content": system_prompt}] + messages

    logger.info(
        f"[ai_service] chat_stream: {len(messages)} msg(s), "
        f"{len(assignments)} assignment(s) in context"
    )

    stream = client.chat.completions.create(
        model=_CHAT_MODEL,
        messages=groq_messages,
        temperature=0.7,
        max_tokens=1024,
        stream=True,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def extract_plan(conversation_messages: list[dict], assignments: list[dict]) -> list[dict]:
    """Extract a structured study plan from a conversation.

    Uses llama-3.1-8b-instant (fast, deterministic) to parse the plan
    that was discussed in the conversation.

    Returns:
        List of dicts: [{assignment_id: str, planned_start: str (YYYY-MM-DD)}]
        Empty list if no plan found.

    Raises:
        RuntimeError, ValueError, Exception — same as generate_suggestions
    """
    client = _get_groq_client()

    assignment_list = "\n".join(
        f'  - ID:{a["id"]} | "{a.get("title","")}" ({a.get("course_name","")})'
        for a in assignments
    )
    system_prompt = _EXTRACT_SYSTEM_TEMPLATE.format(assignment_list=assignment_list)

    # Build a readable transcript for the extraction prompt
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
            max_tokens=1024,
        )
        raw = resp.choices[0].message.content.strip()
        logger.debug(f"[ai_service] extract_plan raw: {raw[:300]}")

        parsed = json.loads(raw)
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
