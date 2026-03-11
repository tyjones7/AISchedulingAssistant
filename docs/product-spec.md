# CampusAI — Product Specification (MVP)

**Version:** 1.0
**Date:** March 2026
**Status:** Active

---

## 1. Problem Statement

College students at BYU manage 5–6 courses spread across Canvas, Learning Suite, and personal commitments. Their deadlines live in at least two separate LMS platforms, their personal obligations live in their head or a calendar app, and nothing talks to anything else. The result: students either over-plan and burn out or under-plan and miss things.

**Job to be Done:**
> I'm trying to manage my busy schedule by staying on top of all my classes, deadlines, and commitments, so I can feel in control, avoid last-minute stress, and perform better academically while still having a positive college life experience.

---

## 2. Value Proposition

We help overwhelmed college students turn messy assignment lists into a real, optimized, auto-updating plan — using AI to build their schedule, surface the right work at the right time, and eliminate the cognitive overhead of deciding "what should I work on next?"

---

## 3. Ideal Customer Profile

**Name:** Emily Carter
**Age / Role:** 20-year-old full-time sophomore/junior at BYU
**Situation:** Taking 5–6 courses, active in 1+ club, possibly working part-time (5–15 hrs/week). Ambitious — GPA-conscious, targeting internships or grad school. Already uses Google Calendar, Learning Suite, and Canvas but feels her system is barely holding together.

**When the pain is worst:**
- Sunday evenings when she tries to plan the week across syllabi, LS, Canvas, and her job schedule
- Late nights before exams when she realizes she underestimated how long things would take
- Midterm season when new obligations (recruiting events, club commitments) blow up an already fragile plan

---

## 4. User Stories

### Priority: MUST HAVE

---

**US-01 — Assignment Aggregation**
*"As a student with classes on both Canvas and Learning Suite, I want all my assignments automatically pulled into one place, so that I never miss a deadline because I forgot to check a platform."*

**Priority:** Must Have — the MVP has zero value if assignments aren't in one place.

**Acceptance Criteria:**
- [ ] User can connect a Canvas API token and see all active Canvas assignments within 60 seconds of first sync
- [ ] User can add one or more Learning Suite iCal feed URLs and see those assignments synced
- [ ] Assignments from both sources appear in a single unified timeline view, sorted by due date
- [ ] A manual sync can be triggered at any time; sync completes in under 30 seconds
- [ ] Assignments that no longer exist in the source (dropped, renamed) are removed from the app on the next sync
- [ ] Due dates are displayed in the user's local time (Mountain Time for BYU students)
- [ ] Duplicate assignments (same assignment updated at source) do not create duplicate entries

---

**US-02 — AI-Generated Study Plan**
*"As a student who doesn't know where to start each week, I want the AI to suggest a prioritized order and schedule for my assignments, so that I can stop wasting time deciding what to work on and actually get things done."*

**Priority:** Must Have — this is the core differentiator from a plain calendar app.

**Acceptance Criteria:**
- [ ] AI generates a prioritized list of active assignments with a priority score (1–10), a suggested start date, and an estimated time to complete
- [ ] Suggestions are generated within 10 seconds of request
- [ ] Suggestions account for the student's stated preferences: preferred study time (morning/afternoon/evening/night), session length, work style (spread-out vs. batch), and busy blocks (class times, work)
- [ ] Student can accept a suggested plan, which writes `planned_start` and `planned_end` to each assignment
- [ ] Accepted plans can be exported to Google Calendar or downloaded as an .ics file
- [ ] Suggestions are regeneratable if the student disagrees with the initial output

---

### Priority: SHOULD HAVE

---

**US-03 — Assignment Status Tracking**
*"As a student working through my task list, I want to mark assignments as in-progress or submitted, so that the app always reflects reality and the AI doesn't keep surfacing work I've already finished."*

**Priority:** Should Have — without this, the AI plan degrades fast; the app becomes noise rather than signal.

**Acceptance Criteria:**
- [ ] Each assignment has a status: `newly_assigned`, `not_started`, `in_progress`, `submitted`, `unavailable`
- [ ] User can change status from the dashboard card or detail view
- [ ] Submitted and unavailable assignments are excluded from AI suggestions and the active timeline
- [ ] Status changes made by the user are preserved across syncs (a re-sync from Canvas/LS does not reset a user-modified status)
- [ ] Overdue assignments (past due date, not submitted) are visually distinct in the UI

---

**US-04 — Personalized Onboarding**
*"As a new student, I want to set up the app and connect my classes in under 5 minutes, so that I can see value immediately without needing a tutorial."*

**Priority:** Should Have — without smooth onboarding, users churn before experiencing the core value.

**Acceptance Criteria:**
- [ ] Onboarding flow is completable in under 5 minutes for a typical student
- [ ] Flow asks which platforms the student uses (Canvas, Learning Suite, or both) and only shows the relevant setup steps
- [ ] Step-by-step instructions for finding the Canvas API token and Learning Suite iCal URL are shown inline — no external documentation needed
- [ ] Student can preview assignments found before confirming each feed
- [ ] Onboarding is skipped on subsequent logins; prior data persists
- [ ] LS-only students (no Canvas) can complete onboarding and reach the dashboard successfully

---

### Priority: COULD HAVE

---

**US-05 — AI Chat for Schedule Adjustment**
*"As a student whose week just got derailed by a surprise exam, I want to chat with the AI to quickly re-prioritize my remaining assignments, so that I can adapt my plan in seconds without rebuilding it from scratch."*

**Priority:** Could Have — high retention value, but the core plan feature (US-02) works without it.

**Acceptance Criteria:**
- [ ] Student can open a chat panel and describe a change ("I have an extra exam Friday")
- [ ] AI responds with a revised suggestion that accounts for the new constraint, referencing specific assignments by name
- [ ] Student can apply the AI's suggested plan from within the chat ("Apply as my schedule")
- [ ] Chat history persists within the session; not required to persist across days
- [ ] Response streams in real-time (SSE); total response begins within 2 seconds

---

## 5. Functional Requirements (MVP)

### 5.1 Authentication
- [ ] Email/password account creation and login via Supabase Auth
- [ ] All user data (assignments, feeds, preferences) is scoped to the authenticated user
- [ ] Sessions persist across browser closes; no re-login required unless explicitly signed out

### 5.2 Data Ingestion
- [ ] **Canvas:** Accept a personal access token, fetch all active courses and their assignments via Canvas REST API. Re-sync preserves user-modified fields.
- [ ] **Learning Suite:** Accept one or more iCal feed URLs (one per course). Parse VEVENT entries; filter out non-assignment events (class sessions, office hours, TA hours, "NO CLASS" markers). Re-sync cleans up removed events.
- [ ] Both sources converge into a single `assignments` table with a unified schema.
- [ ] Background sync runs on demand; syncs all sources in a single operation.

### 5.3 Assignment Management
- [ ] Timeline view: assignments grouped or sorted by due date, showing title, course, status, due date, and point value (if available)
- [ ] Status can be updated per assignment
- [ ] User can add manual assignments (title, course, due date) not sourced from Canvas or LS
- [ ] User can dismiss or mark overdue assignments as unavailable

### 5.4 AI Scheduling
- [ ] AI ingests all active (non-submitted) assignments plus user preferences to produce a prioritized plan
- [ ] Plan output: priority score, suggested start date, estimated minutes per assignment, short rationale
- [ ] Plan can be applied in bulk (sets `planned_start`/`planned_end` for each assignment)
- [ ] Applied plan is exportable to Google Calendar (URL) and .ics (download)

### 5.5 User Preferences
- [ ] Preferred study time of day
- [ ] Preferred session length (minutes)
- [ ] Days in advance to start working on assignments
- [ ] Work style: spread-out vs. batch
- [ ] Weekly busy blocks: recurring time blocks (e.g., "MWF 10–11 am — STRAT 411") excluded from scheduling
- [ ] AI involvement level: proactive (auto-generates plan), balanced (on request), prompt-only (no suggestions)

### 5.6 Sync Status
- [ ] Last sync time is visible in the UI
- [ ] Sync status (running / complete / error) is displayed in real-time
- [ ] Per-course counts (new, updated) are shown in sync completion summary

---

## 6. Non-Functional Requirements

| Requirement | Target |
|---|---|
| Canvas sync latency | < 30 seconds for a typical 5-course load |
| AI suggestion generation | < 10 seconds |
| AI chat first token | < 2 seconds |
| Availability | Best-effort for MVP; no SLA |
| Data isolation | All data is per-user; no cross-user data leakage (Supabase RLS) |
| Platform | Web app; responsive on desktop and mobile |

---

## 7. Success Metrics

### Primary (Does it solve the core problem?)

| Metric | Target at 30 days |
|---|---|
| **Assignments successfully synced per user** | ≥ 20 on first sync (proves aggregation works) |
| **AI plan generated and applied** | ≥ 60% of active users generate and apply at least one plan |
| **Day-7 retention** | ≥ 40% of signed-up users return within 7 days |

### Secondary (Is it working well?)

| Metric | Target |
|---|---|
| Onboarding completion rate | ≥ 75% of users who start onboarding complete it |
| Sync error rate | < 5% of sync attempts result in an error |
| Assignment status update rate | ≥ 50% of users update at least one assignment status per week (signals real use) |
| Support / "why doesn't this work" messages | < 10% of active users in first 30 days |

### Leading Indicator (Are we building the right thing?)

- **Qualitative:** In user interviews, students report feeling "more in control" or "less stressed" within the first week of use.
- **Behavioral:** Users who apply an AI-generated plan return to the app more days per week than users who don't (validates the plan feature as the retention driver).

---

## 8. Out of Scope (MVP)

The following are explicitly NOT being built in the MVP. Revisit after validating core retention.

| Feature | Reason excluded |
|---|---|
| Grade tracking / GPA calculation | Adds complexity; not required to solve the scheduling problem |
| Canvas submission (submitting work from within the app) | OAuth/API scope is complex; out of band from the scheduling JTBD |
| Collaboration / shared plans with study partners | Multi-user coordination is a different product |
| Mobile native app (iOS / Android) | Web-first; native adds significant build/maintenance cost |
| Email or SMS notifications | Push notifications cover the MVP need; email/SMS = separate infra |
| Professor/TA-facing features | Target user is the student, not the instructor |
| Automatic time blocking in Google/Apple Calendar | Export covers this; live two-way sync is high engineering cost |
| LMS platforms beyond Canvas and Learning Suite | BYU-specific MVP first; expand after product-market fit |
| AI-generated assignment content / writing assistance | Scope creep; different JTBD ("help me do work" vs. "help me plan work") |
| Billing / subscription management | MVP is free; monetization is post-PMF |

---

## 9. Open Questions

1. **Sync frequency:** Should the app auto-sync in the background (e.g., once per day via a scheduled job), or remain user-triggered only? Auto-sync reduces friction but adds infra complexity.
2. **Canvas token refresh:** Personal access tokens don't expire, but students sometimes revoke them. How should the app surface and recover from a broken token gracefully?
3. **LS iCal feed access:** iCal URLs appear to be semi-public (no auth required). Are they stable across semesters, or do they change when a new semester starts? This affects how often users need to re-configure feeds.
4. **Multi-semester handling:** How should the app behave when a new semester starts and old assignments become irrelevant? Should prior-semester data be archived or deleted?
5. **Privacy:** Canvas tokens and iCal URLs give read access to a student's academic record. What is the appropriate data retention policy?

---

## 10. Revision History

| Version | Date | Change |
|---|---|---|
| 1.0 | March 2026 | Initial MVP spec |
