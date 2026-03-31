"""
Scheduling engine for CampusAI.

Hybrid scheduling approach:
  generate_schedule_ai()  — AI scores priorities + rules engine does all placement.
                            Guarantees: daily cap, multi-day spreading, break gaps,
                            never schedule after due date.
  generate_schedule()     — Pure rules fallback (earliest-deadline-first bin-packing)
                            used when AI is unavailable.

Scheduling constants (tunable):
  DAILY_CAP_MIN    = 150   max study minutes per day (2.5 h)
  BREAK_GAP_MIN    = 8     mandatory gap after each study block
  MAX_SESSION_MIN  = 90    hard cap on a single study session
  MIN_BLOCK_MIN    = 20    minimum useful block length
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, time, date as _date_type
from zoneinfo import ZoneInfo

DAILY_CAP_MIN   = 150
BREAK_GAP_MIN   = 8
MAX_SESSION_MIN = 90
MIN_BLOCK_MIN   = 20

logger = logging.getLogger(__name__)
MOUNTAIN = ZoneInfo("America/Denver")

STUDY_TIME_WINDOWS = {
    "morning":   ("07:00", "13:00"),
    "afternoon": ("12:00", "18:00"),
    "evening":   ("16:00", "22:00"),
    "night":     ("19:00", "23:30"),
}


def _parse_hm(t_str: str) -> tuple[int, int]:
    h, m = t_str.split(":")
    return int(h), int(m)


def _subtract_busy(
    work_start: datetime,
    work_end: datetime,
    busy_slots: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Return list of (start, end) free slots after removing busy periods."""
    free = [(work_start, work_end)]
    for b_start, b_end in sorted(busy_slots):
        new_free = []
        for f_start, f_end in free:
            if b_end <= f_start or b_start >= f_end:
                new_free.append((f_start, f_end))
            else:
                if f_start < b_start:
                    new_free.append((f_start, b_start))
                if b_end < f_end:
                    new_free.append((b_end, f_end))
        free = new_free
    return free


def compute_free_slots(prefs: dict, days: int = 7) -> dict[str, list[tuple[datetime, datetime]]]:
    """Compute free time windows for the next `days` days.

    Subtracts class/busy blocks from the student's work window to produce
    a map of {date_str: [(start_dt, end_dt), ...]} in Mountain Time.

    Args:
        prefs: User preferences dict (study_time, work_start, work_end, weekly_schedule)
        days: Number of days to compute (default 7)

    Returns:
        Dict mapping "YYYY-MM-DD" → list of (start_datetime, end_datetime) free windows
    """
    study_time = prefs.get("study_time", "evening")
    default_start, default_end = STUDY_TIME_WINDOWS.get(study_time, ("08:00", "22:00"))
    work_start_str = prefs.get("work_start") or default_start
    work_end_str   = prefs.get("work_end")   or default_end
    weekly_schedule = prefs.get("weekly_schedule") or []

    ws_h, ws_m = _parse_hm(work_start_str)
    we_h, we_m = _parse_hm(work_end_str)

    today = datetime.now(MOUNTAIN).date()
    result: dict[str, list[tuple[datetime, datetime]]] = {}

    for day_offset in range(days):
        day = today + timedelta(days=day_offset)
        weekday_str = day.strftime("%a")  # "Mon", "Tue", …

        work_start_dt = datetime.combine(day, time(ws_h, ws_m)).replace(tzinfo=MOUNTAIN)
        if we_h < ws_h:
            work_end_dt = datetime.combine(day + timedelta(days=1), time(we_h, we_m)).replace(tzinfo=MOUNTAIN)
        else:
            work_end_dt = datetime.combine(day, time(we_h, we_m)).replace(tzinfo=MOUNTAIN)

        busy = []
        for block in weekly_schedule:
            # Support both {day: "Mon"} (singular, from Settings) and {days: ["Mon",...]} (legacy)
            day_val = block.get("day") or ""
            days_val = block.get("days") or []
            if weekday_str == day_val or weekday_str in days_val:
                try:
                    bs_h, bs_m = _parse_hm(block.get("start", "00:00"))
                    be_h, be_m = _parse_hm(block.get("end", "00:00"))
                    b_start = datetime.combine(day, time(bs_h, bs_m)).replace(tzinfo=MOUNTAIN)
                    b_end   = datetime.combine(day, time(be_h, be_m)).replace(tzinfo=MOUNTAIN)
                    if b_end > b_start:
                        busy.append((b_start, b_end))
                except Exception:
                    pass

        free_slots = _subtract_busy(work_start_dt, work_end_dt, busy)
        result[day.isoformat()] = free_slots

    return result


def format_free_slots_for_ai(free_slots_by_day: dict[str, list[tuple[datetime, datetime]]]) -> str:
    """Format free slot map into human-readable text for AI schedule generation prompt."""
    lines = ["FREE TIME SLOTS THIS WEEK (Mountain Time):"]
    total_free_min = 0

    for date_str in sorted(free_slots_by_day.keys()):
        slots = free_slots_by_day[date_str]
        day_dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_name = day_dt.strftime("%a %b %d")
        usable = [(s, e) for s, e in slots if int((e - s).total_seconds() / 60) >= 20]

        if not usable:
            lines.append(f"  {day_name}: (fully booked — no usable free time)")
        else:
            slot_strs = []
            for s, e in usable:
                total_min = int((e - s).total_seconds() / 60)
                total_free_min += total_min
                h, m = divmod(total_min, 60)
                dur = f"{h}h{m:02d}m" if m else f"{h}h"
                slot_strs.append(f"{s.strftime('%H:%M')}–{e.strftime('%H:%M')} ({dur} free)")
            lines.append(f"  {day_name}: {', '.join(slot_strs)}")

    total_h, total_m = divmod(total_free_min, 60)
    lines.append(f"\nTotal free time available: {total_h}h{total_m:02d}m")
    return "\n".join(lines)


def generate_schedule_ai(user_id: str, supabase_client, days: int = 7) -> dict:
    """Hybrid scheduler: AI priority scoring + rules-based slot placement.

    AI is used ONLY to rank assignments by urgency and fill missing time estimates.
    All placement math (daily cap, spreading, break gaps, due-date cutoff) is done
    by the rules engine below — LLMs are unreliable at arithmetic constraints.

    Guarantees:
      - No block scheduled on or after its assignment's due date
      - Max DAILY_CAP_MIN minutes of study per day
      - At most one session per assignment per day (forces multi-day spreading)
      - BREAK_GAP_MIN gap consumed from the slot after each block
      - Sessions capped at min(session_length_minutes, MAX_SESSION_MIN)

    Falls back to generate_schedule() if AI raises an exception.
    """
    import ai_service

    # ── 1. Fetch active graded tasks ──
    resp = supabase_client.table("assignments").select(
        "id, title, course_name, due_date, estimated_minutes, task_type, assignment_type, status, point_value, notes"
    ).eq("user_id", user_id).not_.in_("status", ["submitted", "unavailable"]).execute()

    tasks = resp.data or []
    if not tasks:
        logger.info(f"schedule_hybrid [{user_id[:8]}]: no active tasks")
        return {"blocks": [], "overbooked": []}

    # ── 2. Fetch preferences ──
    prefs_resp = supabase_client.table("user_preferences").select(
        "study_time, session_length_minutes, work_start, work_end, weekly_schedule, "
        "work_style, advance_days, student_context"
    ).eq("user_id", user_id).limit(1).execute()
    prefs = prefs_resp.data[0] if prefs_resp.data else {}

    max_session_min = min(prefs.get("session_length_minutes") or 60, MAX_SESSION_MIN)

    # ── 3. AI: priority scores + fill missing estimates ──
    score_map: dict[str, dict] = {}
    try:
        suggestions = ai_service.generate_suggestions(tasks, prefs)
        for s in suggestions:
            score_map[s["assignment_id"]] = s
        # Apply AI-estimated minutes to tasks that have none
        for t in tasks:
            if not t.get("estimated_minutes"):
                ai_est = score_map.get(t["id"], {}).get("estimated_minutes")
                if ai_est:
                    t["estimated_minutes"] = ai_est
        logger.info(f"schedule_hybrid [{user_id[:8]}]: AI scored {len(score_map)} tasks")
    except Exception as e:
        logger.warning(f"schedule_hybrid [{user_id[:8]}]: AI priority failed ({e}), using deadline order")

    # ── 4. Sort: highest priority first, then earliest due date ──
    def _sort_key(t):
        score = score_map.get(t["id"], {}).get("priority_score", 5)
        due   = t.get("due_date") or "9999-12-31"
        return (-score, due)

    tasks.sort(key=_sort_key)

    # ── 5. Compute free slots (mutable copy we consume as we place blocks) ──
    free_slots_by_day = compute_free_slots(prefs, days=days)
    # Each slot is [start_dt, end_dt] — mutable list so we can shrink it
    slots: dict[str, list[list]] = {
        d: [[s, e] for s, e in windows]
        for d, windows in free_slots_by_day.items()
    }

    today       = datetime.now(MOUNTAIN).date()
    daily_used  = defaultdict(int)   # date_str → minutes already placed
    new_blocks  = []
    id_to_task  = {t["id"]: t for t in tasks}

    # ── 6. Rules-based placement ──
    for task in tasks:
        est = task.get("estimated_minutes") or 60
        remaining = est

        due_dt_mt = None
        due_str = task.get("due_date")
        if due_str:
            try:
                due_dt_mt = datetime.fromisoformat(
                    due_str.replace("Z", "+00:00")
                ).astimezone(MOUNTAIN)
            except Exception:
                pass

        # Walk days in order, place at most one session per day per assignment
        for date_str in sorted(slots.keys()):
            if remaining <= 0:
                break

            day = _date_type.fromisoformat(date_str)
            if day < today:
                continue

            # Never schedule on or after the due date
            if due_dt_mt and day >= due_dt_mt.date():
                break

            # Respect daily cap
            cap_left = DAILY_CAP_MIN - daily_used[date_str]
            if cap_left < MIN_BLOCK_MIN:
                continue

            # Find first usable slot on this day
            for slot in slots[date_str]:
                slot_start, slot_end = slot
                avail_min = int((slot_end - slot_start).total_seconds() / 60)
                if avail_min < MIN_BLOCK_MIN:
                    continue

                block_len = min(max_session_min, remaining, cap_left, avail_min)
                if block_len < MIN_BLOCK_MIN:
                    continue

                block_end = slot_start + timedelta(minutes=block_len)
                new_blocks.append({
                    "user_id":       user_id,
                    "assignment_id": task["id"],
                    "date":          date_str,
                    "start_time":    slot_start.isoformat(),
                    "end_time":      block_end.isoformat(),
                    "label":         task.get("title", "Study"),
                    "status":        "planned",
                    "plan_version":  1,
                })

                remaining           -= block_len
                daily_used[date_str] += block_len

                # Advance slot by block + mandatory break gap
                new_slot_start = block_end + timedelta(minutes=BREAK_GAP_MIN)
                slot[0] = new_slot_start  # mutate in place

                break  # one session per assignment per day — forces spreading

    # ── 7. Back-fill estimated_minutes for tasks that still had none ──
    scheduled_min_by_id: dict[str, int] = defaultdict(int)
    for b in new_blocks:
        dur = int((datetime.fromisoformat(b["end_time"]) -
                   datetime.fromisoformat(b["start_time"])).total_seconds() / 60)
        scheduled_min_by_id[b["assignment_id"]] += dur

    for t in tasks:
        if not t.get("estimated_minutes") and scheduled_min_by_id.get(t["id"], 0) > 0:
            try:
                supabase_client.table("assignments").update(
                    {"estimated_minutes": scheduled_min_by_id[t["id"]]}
                ).eq("id", t["id"]).eq("user_id", user_id).execute()
            except Exception:
                pass

    # ── 8. Overbooked = tasks with less than 50% of their time scheduled ──
    overbooked = [
        t for t in tasks
        if scheduled_min_by_id.get(t["id"], 0) < (t.get("estimated_minutes") or 60) * 0.5
    ]

    logger.info(
        f"schedule_hybrid [{user_id[:8]}]: {len(new_blocks)} blocks across "
        f"{len({b['date'] for b in new_blocks})} days, "
        f"{len(overbooked)} overbooked (cap={DAILY_CAP_MIN}min/day, "
        f"max_session={max_session_min}min)"
    )
    return {"blocks": new_blocks, "overbooked": overbooked}


def generate_schedule(user_id: str, supabase_client, days: int = 7) -> dict:
    """Rules-based fallback scheduler (earliest-deadline-first bin-packing).

    Used when AI scheduling is unavailable. Only schedules tasks that have
    estimated_minutes set.

    Returns:
        {
            "blocks": [list of dicts ready for DB insert],
            "overbooked": [list of task dicts that couldn't be fully scheduled],
        }
    """
    # ── 1. Fetch active tasks that have an estimated time ──
    resp = supabase_client.table("assignments").select(
        "id, title, course_name, due_date, estimated_minutes, task_type, status"
    ).eq("user_id", user_id).not_.in_("status", ["submitted", "unavailable"]).execute()

    tasks = [t for t in (resp.data or []) if t.get("estimated_minutes")]

    if not tasks:
        logger.info(f"schedule [{user_id[:8]}]: no tasks with estimated_minutes")
        return {"blocks": [], "overbooked": []}

    # ── 2. Fetch preferences ──
    prefs_resp = supabase_client.table("user_preferences").select(
        "study_time, session_length_minutes, work_start, work_end, weekly_schedule"
    ).eq("user_id", user_id).limit(1).execute()
    prefs = prefs_resp.data[0] if prefs_resp.data else {}

    max_block_min = prefs.get("session_length_minutes") or 60

    # ── 3. Credit completed blocks against remaining time ──
    completed_resp = supabase_client.table("time_blocks").select(
        "assignment_id, start_time, end_time"
    ).eq("user_id", user_id).eq("status", "completed").execute()

    completed_min: dict[str, float] = {}
    for cb in (completed_resp.data or []):
        aid = cb["assignment_id"]
        try:
            s = datetime.fromisoformat(cb["start_time"].replace("Z", "+00:00"))
            e = datetime.fromisoformat(cb["end_time"].replace("Z", "+00:00"))
            completed_min[aid] = completed_min.get(aid, 0) + (e - s).total_seconds() / 60
        except Exception:
            pass

    # ── 4. Sort: earlier due date first, then larger tasks ──
    def sort_key(t):
        due = t.get("due_date") or "9999-12-31"
        return (due, -(t.get("estimated_minutes") or 60))

    tasks.sort(key=sort_key)

    today = datetime.now(MOUNTAIN).date()
    remaining: dict[str, float] = {}
    for t in tasks:
        est = t.get("estimated_minutes") or 60
        done = completed_min.get(t["id"], 0)
        remaining[t["id"]] = max(0.0, est - done)

    # ── 5. Compute free slots and fill them ──
    free_slots_by_day = compute_free_slots(prefs, days=days)
    new_blocks = []

    for day_offset in range(days):
        day = today + timedelta(days=day_offset)
        date_str = day.isoformat()
        free_slots = list(free_slots_by_day.get(date_str, []))

        for task in tasks:
            rem = remaining.get(task["id"], 0)
            if rem <= 0:
                continue

            due_str = task.get("due_date")
            if due_str:
                try:
                    due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
                    if due_dt.astimezone(MOUNTAIN).date() < day:
                        continue
                except Exception:
                    pass

            for i in range(len(free_slots)):
                slot_start, slot_end = free_slots[i]
                avail_min = int((slot_end - slot_start).total_seconds() / 60)
                if avail_min < 15:
                    continue

                block_len = min(max_block_min, rem, avail_min)
                block_end = slot_start + timedelta(minutes=block_len)

                new_blocks.append({
                    "user_id":       user_id,
                    "assignment_id": task["id"],
                    "date":          date_str,
                    "start_time":    slot_start.isoformat(),
                    "end_time":      block_end.isoformat(),
                    "label":         task.get("title", "Study"),
                    "status":        "planned",
                    "plan_version":  1,
                })

                remaining[task["id"]] -= block_len
                free_slots[i] = (block_end, slot_end)

                if remaining[task["id"]] <= 0:
                    break

    overbooked = [t for t in tasks if remaining.get(t["id"], 0) > 0]

    logger.info(
        f"schedule [{user_id[:8]}]: generated {len(new_blocks)} blocks, "
        f"{len(overbooked)} overbooked"
    )
    return {"blocks": new_blocks, "overbooked": overbooked}
