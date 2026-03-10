"""
Rules-based scheduling engine.

Generates a conflict-free weekly plan by fitting task blocks into free time
slots derived from work hours and weekly class/busy schedule.
"""

import logging
from datetime import datetime, timedelta, time
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


def generate_schedule(user_id: str, supabase_client, days: int = 7) -> dict:
    """
    Generate a conflict-free weekly schedule for all active tasks.

    Only tasks with estimated_minutes set are scheduled.

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

    study_time = prefs.get("study_time", "evening")
    default_start, default_end = STUDY_TIME_WINDOWS.get(study_time, ("08:00", "22:00"))
    work_start_str = prefs.get("work_start") or default_start
    work_end_str   = prefs.get("work_end")   or default_end
    max_block_min  = prefs.get("session_length_minutes") or 60
    weekly_schedule = prefs.get("weekly_schedule") or []

    # ── 3. Fetch already-completed blocks to credit against remaining time ──
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

    # Track remaining minutes per task
    today = datetime.now(MOUNTAIN).date()
    remaining: dict[str, float] = {}
    for t in tasks:
        est = t.get("estimated_minutes") or 60
        done = completed_min.get(t["id"], 0)
        remaining[t["id"]] = max(0.0, est - done)

    new_blocks = []
    ws_h, ws_m = _parse_hm(work_start_str)
    we_h, we_m = _parse_hm(work_end_str)

    for day_offset in range(days):
        day = today + timedelta(days=day_offset)
        weekday_str = day.strftime("%a")  # "Mon", "Tue", …

        # Build work window
        work_start_dt = datetime.combine(day, time(ws_h, ws_m)).replace(tzinfo=MOUNTAIN)
        if we_h < ws_h:
            # Crosses midnight
            work_end_dt = datetime.combine(day + timedelta(days=1), time(we_h, we_m)).replace(tzinfo=MOUNTAIN)
        else:
            work_end_dt = datetime.combine(day, time(we_h, we_m)).replace(tzinfo=MOUNTAIN)

        # Build busy slots from weekly_schedule
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

        for task in tasks:
            rem = remaining.get(task["id"], 0)
            if rem <= 0:
                continue

            # Don't schedule past due date
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
                    "date":          day.isoformat(),
                    "start_time":    slot_start.isoformat(),
                    "end_time":      block_end.isoformat(),
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
