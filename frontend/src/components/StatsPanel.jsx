import { useState, useEffect } from 'react'
import { authFetch, API_BASE } from '../lib/api'
import './StatsPanel.css'

const STATUS_LABELS = {
  newly_assigned: 'Newly Assigned',
  not_started: 'Not Started',
  in_progress: 'In Progress',
  submitted: 'Submitted',
  unavailable: 'Unavailable',
}

const STATUS_COLORS = {
  newly_assigned: '#0071e3',
  not_started: '#6366f1',
  in_progress: '#f59e0b',
  submitted: '#10b981',
  unavailable: '#6b7280',
}

function daysBetween(dateA, dateB) {
  const msPerDay = 1000 * 60 * 60 * 24
  return (dateA - dateB) / msPerDay
}

function getWeekLabel(daysFromNow) {
  if (daysFromNow < 7)  return 'This week'
  if (daysFromNow < 14) return 'Next week'
  if (daysFromNow < 21) return 'In 2 weeks'
  if (daysFromNow < 28) return 'In 3 weeks'
  return 'Later'
}

function StatsPanel({ onClose }) {
  const [assignments, setAssignments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    authFetch(`${API_BASE}/assignments`)
      .then(res => {
        if (!res.ok) throw new Error('Failed to load')
        return res.json()
      })
      .then(data => {
        setAssignments(data.assignments || [])
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const handleBackdrop = (e) => {
    if (e.target === e.currentTarget) onClose()
  }

  // ── Computed stats ──────────────────────────────────────────────────
  const now = new Date()

  const total = assignments.length
  const submitted = assignments.filter(a => a.status === 'submitted').length
  const completionRate = total > 0 ? Math.round((submitted / total) * 100) : 0

  const sevenDaysFromNow = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000)
  const dueThisWeek = assignments.filter(a => {
    if (a.status === 'submitted' || !a.due_date) return false
    const d = new Date(a.due_date)
    return d >= now && d <= sevenDaysFromNow
  }).length

  // Submission timing
  const timedSubmissions = assignments.filter(a => a.submitted_at && a.due_date)
  const timingBuckets = {
    'Early 3+ days': 0,
    'Early 1–2 days': 0,
    'Day of': 0,
    'Late 1–2 days': 0,
    'Late 3+ days': 0,
  }
  let timingTotal = 0
  let timingSum = 0

  timedSubmissions.forEach(a => {
    const delta = daysBetween(new Date(a.due_date), new Date(a.submitted_at))
    timingSum += delta
    timingTotal++
    if (delta >= 3)        timingBuckets['Early 3+ days']++
    else if (delta >= 1)   timingBuckets['Early 1–2 days']++
    else if (delta >= -0.5) timingBuckets['Day of']++
    else if (delta >= -2)  timingBuckets['Late 1–2 days']++
    else                   timingBuckets['Late 3+ days']++
  })

  const avgDelta = timingTotal > 0 ? timingSum / timingTotal : null
  const timingMaxBucket = Math.max(...Object.values(timingBuckets), 1)

  // By course
  const courseMap = {}
  assignments.forEach(a => {
    const course = a.course_name || 'Unknown Course'
    if (!courseMap[course]) courseMap[course] = { total: 0, submitted: 0 }
    courseMap[course].total++
    if (a.status === 'submitted') courseMap[course].submitted++
  })
  const courses = Object.entries(courseMap)
    .map(([name, counts]) => ({ name, ...counts, pct: Math.round((counts.submitted / counts.total) * 100) }))
    .sort((a, b) => b.total - a.total)
  const maxCourseTotal = Math.max(...courses.map(c => c.total), 1)

  // Workload timeline (non-submitted future assignments)
  const weekMap = {}
  const weekOrder = ['This week', 'Next week', 'In 2 weeks', 'In 3 weeks', 'Later']
  weekOrder.forEach(w => { weekMap[w] = 0 })

  assignments.forEach(a => {
    if (a.status === 'submitted' || a.status === 'unavailable' || !a.due_date) return
    const d = new Date(a.due_date)
    if (d < now) return
    const daysAway = daysBetween(d, now)
    const label = getWeekLabel(daysAway)
    weekMap[label] = (weekMap[label] || 0) + 1
  })
  const maxWeekCount = Math.max(...Object.values(weekMap), 1)

  // Status breakdown
  const statusCounts = {}
  Object.keys(STATUS_LABELS).forEach(s => { statusCounts[s] = 0 })
  assignments.forEach(a => {
    if (statusCounts[a.status] !== undefined) statusCounts[a.status]++
  })

  // ── Render ──────────────────────────────────────────────────────────
  return (
    <div className="stats-backdrop" onClick={handleBackdrop}>
      <div className="stats-panel" role="dialog" aria-modal="true" aria-label="Insights">

        {/* Header */}
        <div className="stats-header">
          <h2 className="stats-title">Insights</h2>
          <button className="stats-close" onClick={onClose} aria-label="Close insights">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="stats-body">
          {loading && (
            <div className="stats-loading">
              <div className="stats-spinner" />
              <span>Loading your data...</span>
            </div>
          )}

          {error && (
            <div className="stats-error-msg">Failed to load data: {error}</div>
          )}

          {!loading && !error && (
            <>
              {/* Top stat cards */}
              <div className="stats-cards-row">
                <div className="stats-card">
                  <span className="stats-card-value">{total}</span>
                  <span className="stats-card-label">Total assignments</span>
                </div>
                <div className="stats-card">
                  <span className="stats-card-value stats-card-value--green">{submitted}</span>
                  <span className="stats-card-label">Submitted</span>
                </div>
                <div className="stats-card">
                  <span className="stats-card-value stats-card-value--blue">{completionRate}%</span>
                  <span className="stats-card-label">Completion rate</span>
                </div>
                <div className="stats-card">
                  <span className="stats-card-value stats-card-value--amber">{dueThisWeek}</span>
                  <span className="stats-card-label">Due this week</span>
                </div>
              </div>

              {/* Submission Timing */}
              <div className="stats-section">
                <h3 className="stats-section-title">Submission Timing</h3>
                {timingTotal === 0 ? (
                  <p className="stats-empty-msg">
                    Submission timing will track as you mark assignments complete going forward.
                  </p>
                ) : (
                  <>
                    <div className="stats-timing-summary">
                      <span className={`stats-timing-big ${avgDelta >= 0 ? 'is-early' : 'is-late'}`}>
                        {Math.abs(avgDelta).toFixed(1)}
                      </span>
                      <span className="stats-timing-label">
                        days {avgDelta >= 0 ? 'early on average' : 'late on average'}
                      </span>
                    </div>
                    <div className="stats-bar-list">
                      {Object.entries(timingBuckets).map(([label, count]) => (
                        <div key={label} className="stats-bar-row">
                          <span className="stats-bar-label">{label}</span>
                          <div className="stats-bar-track">
                            <div
                              className={`stats-bar-fill ${label.startsWith('Late') ? 'is-late' : label === 'Day of' ? 'is-neutral' : 'is-early'}`}
                              style={{ width: `${(count / timingMaxBucket) * 100}%` }}
                            />
                          </div>
                          <span className="stats-bar-count">{count}</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>

              {/* By Course */}
              <div className="stats-section">
                <h3 className="stats-section-title">By Course</h3>
                {courses.length === 0 ? (
                  <p className="stats-empty-msg">No course data yet.</p>
                ) : (
                  <div className="stats-bar-list">
                    {courses.map(course => (
                      <div key={course.name} className="stats-course-row">
                        <div className="stats-course-header">
                          <span className="stats-course-name">{course.name}</span>
                          <span className="stats-course-meta">{course.submitted}/{course.total} submitted · {course.pct}%</span>
                        </div>
                        <div className="stats-bar-track stats-bar-track--thick">
                          <div
                            className="stats-bar-fill stats-bar-fill--course"
                            style={{ width: `${(course.total / maxCourseTotal) * 100}%` }}
                          >
                            <div
                              className="stats-bar-fill--submitted-overlay"
                              style={{ width: `${course.pct}%` }}
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Workload Timeline */}
              <div className="stats-section">
                <h3 className="stats-section-title">Upcoming Workload</h3>
                <div className="stats-bar-list">
                  {weekOrder.map(week => {
                    const count = weekMap[week] || 0
                    return (
                      <div key={week} className="stats-bar-row">
                        <span className="stats-bar-label">{week}</span>
                        <div className="stats-bar-track">
                          <div
                            className="stats-bar-fill"
                            style={{ width: count > 0 ? `${(count / maxWeekCount) * 100}%` : '0%' }}
                          />
                        </div>
                        <span className="stats-bar-count">{count}</span>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Status Breakdown */}
              <div className="stats-section">
                <h3 className="stats-section-title">Status Breakdown</h3>
                <div className="stats-status-list">
                  {Object.entries(STATUS_LABELS).map(([key, label]) => {
                    const count = statusCounts[key] || 0
                    const pct = total > 0 ? Math.round((count / total) * 100) : 0
                    return (
                      <div key={key} className="stats-bar-row">
                        <span className="stats-bar-label">
                          <span
                            className="stats-status-dot"
                            style={{ background: STATUS_COLORS[key] }}
                          />
                          {label}
                        </span>
                        <div className="stats-bar-track">
                          <div
                            className="stats-bar-fill"
                            style={{
                              width: count > 0 ? `${pct}%` : '0%',
                              background: STATUS_COLORS[key],
                            }}
                          />
                        </div>
                        <span className="stats-bar-count">{count}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export default StatsPanel
