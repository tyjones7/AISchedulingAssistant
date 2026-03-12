"""
Scheduling engine for CampusAI.

Two scheduling paths:
  1. generate_schedule_ai()   — AI-powered: uses Groq to reason about the best
                                assignment for each free slot (recommended)
  2. generate_schedule()      — Rules-based fallback: earliest-deadline-first
                                bin-packing, used when AI is unavailable

Both functions accept (user_id, supabase_client) and return:
  {"blocks": [list of dicts ready for DB insert], "overbooked": [...]}

Public helpers:
  compute_free_slots()        — returns free time windows per day
  format_free_slots_for_ai()  — formats free slots as human-readable text for AI prompts
"""

import logging
from datetime import datetime, timedelta, time, date as _date_type
from zoneinfo import ZoneInfo

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
            if weekday_str in (block.get("days") or []):
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
    """Generate an AI-powered weekly schedule using Groq.

    Computes free slots locally (fast), then sends them + assignments to the AI
    which reasons about priorities, task types, and work style to fill the slots.

    Falls back to generate_schedule() if AI raises an exception.

    Returns:
        {
            "blocks": [list of dicts ready for DB insert],
            "overbooked": [list of task dicts that couldn't be fully scheduled],
        }
    """
    import ai_service

    # ── 1. Fetch active tasks ──
    resp = supabase_client.table("assignments").select(
        "id, title, course_name, due_date, estimated_minutes, task_type, assignment_type, status, point_value, notes"
    ).eq("user_id", user_id).not_.in_("status", ["submitted", "unavailable"]).execute()

    tasks = resp.data or []
    if not tasks:
        logger.info(f"schedule_ai [{user_id[:8]}]: no active tasks")
        return {"blocks": [], "overbooked": []}

    # ── 2. Fetch preferences ──
    prefs_resp = supabase_client.table("user_preferences").select(
        "study_time, session_length_minutes, work_start, work_end, weekly_schedule, "
        "work_style, advance_days, student_context"
    ).eq("user_id", user_id).limit(1).execute()
    prefs = prefs_resp.data[0] if prefs_resp.data else {}

    # ── 3. Compute free slots ──
    free_slots_by_day = compute_free_slots(prefs, days=days)
    free_slots_text = format_free_slots_for_ai(free_slots_by_day)

    # ── 4. Call AI scheduler ──
    logger.info(f"schedule_ai [{user_id[:8]}]: calling AI for {len(tasks)} tasks")
    try:
        result = ai_service.generate_ai_schedule(tasks, free_slots_text, prefs)
    except Exception as e:
        logger.warning(f"schedule_ai [{user_id[:8]}]: AI failed ({e}), falling back to rules-based")
        return generate_schedule(user_id, supabase_client, days=days)

    # ── 5. Convert AI output to DB-ready rows ──
    valid_ids = {t["id"] for t in tasks}
    id_to_task = {t["id"]: t for t in tasks}
    new_blocks = []
    today = datetime.now(MOUNTAIN).date()

    for b in result.get("blocks", []):
        aid = b.get("assignment_id", "")
        if aid not in valid_ids:
            logger.warning(f"schedule_ai: skipping block with unknown assignment_id {aid!r}")
            continue

        date_str = b.get("date", "")
        start_str = b.get("start_time", "")
        end_str = b.get("end_time", "")
        label = b.get("label", "")

        try:
            sh, sm = _parse_hm(start_str)
            eh, em = _parse_hm(end_str)
            day = _date_type.fromisoformat(date_str)
            start_dt = datetime.combine(day, time(sh, sm)).replace(tzinfo=MOUNTAIN)
            end_dt   = datetime.combine(day, time(eh, em)).replace(tzinfo=MOUNTAIN)
            if end_dt <= start_dt:
                logger.warning(f"schedule_ai: skipping zero/negative block for {aid}")
                continue
        except Exception as ex:
            logger.warning(f"schedule_ai: could not parse block times {start_str}–{end_str}: {ex}")
            continue

        # Verify block doesn't land in a busy slot
        day_free = free_slots_by_day.get(date_str, [])
        fits = any(fs <= start_dt and end_dt <= fe for fs, fe in day_free)
        if not fits:
            # Allow with a warning — AI may slightly exceed slots; don't silently drop valid work
            logger.debug(f"schedule_ai: block {aid} {date_str} {start_str}–{end_str} slightly outside free slots, keeping")

        new_blocks.append({
            "user_id":       user_id,
            "assignment_id": aid,
            "date":          date_str,
            "start_time":    start_dt.isoformat(),
            "end_time":      end_dt.isoformat(),
            "label":         label or id_to_task.get(aid, {}).get("title", "Study"),
            "status":        "planned",
            "plan_version":  1,
        })

    # ── 6. Back-fill estimated_minutes for tasks that had none ──
    # Tally total scheduled minutes per assignment_id from the blocks we just built,
    # then write back to assignments where estimated_minutes was null/missing.
    scheduled_minutes: dict[str, int] = {}
    for b in new_blocks:
        aid = b["assignment_id"]
        dur = int((datetime.fromisoformat(b["end_time"]) - datetime.fromisoformat(b["start_time"])).total_seconds() / 60)
        scheduled_minutes[aid] = scheduled_minutes.get(aid, 0) + dur

    for t in tasks:
        if not t.get("estimated_minutes") and scheduled_minutes.get(t["id"], 0) > 0:
            try:
                supabase_client.table("assignments").update(
                    {"estimated_minutes": scheduled_minutes[t["id"]]}
                ).eq("id", t["id"]).eq("user_id", user_id).execute()
                logger.info(f"schedule_ai: set estimated_minutes={scheduled_minutes[t['id']]} for {t['title']!r}")
            except Exception as e:
                logger.warning(f"schedule_ai: failed to write estimate for {t['id']}: {e}")

    # Determine overbooked tasks (those with no scheduled blocks)
    scheduled_ids = {b["assignment_id"] for b in new_blocks}
    overbooked_titles = result.get("overbooked", [])
    # Also catch tasks the AI silently omitted
    for t in tasks:
        if t["id"] not in scheduled_ids and t.get("estimated_minutes"):
            if t["title"] not in overbooked_titles:
                overbooked_titles.append(t["title"])

    overbooked_tasks = [t for t in tasks if t["title"] in overbooked_titles]

    logger.info(
        f"schedule_ai [{user_id[:8]}]: {len(new_blocks)} blocks ready, "
        f"{len(overbooked_tasks)} overbooked"
    )
    return {"blocks": new_blocks, "overbooked": overbooked_tasks}


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
