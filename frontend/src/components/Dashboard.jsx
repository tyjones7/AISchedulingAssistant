import { useState, useEffect, useCallback, useMemo } from 'react'
import AssignmentCard from './AssignmentCard'
import AssignmentDetail from './AssignmentDetail'
import SyncButton from './SyncButton'
import { ToastContainer } from './Toast'
import { API_BASE } from '../config/api'
import './Dashboard.css'

const STATUS_LABELS = {
  newly_assigned: 'New',
  not_started: 'Not Started',
  in_progress: 'In Progress',
  submitted: 'Submitted',
  unavailable: 'Unavailable',
}

const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
const DAY_NAMES_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

// Mountain Time date helper
const getMtDateStr = (d) => {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Denver', year: 'numeric', month: '2-digit', day: '2-digit'
  }).formatToParts(d)
  return `${parts.find(p => p.type === 'year').value}-${parts.find(p => p.type === 'month').value}-${parts.find(p => p.type === 'day').value}`
}

const getMtDayOfWeek = (d) => {
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Denver', weekday: 'long'
  }).format(d)
}

const getMtDayIndex = (d) => {
  const dayName = getMtDayOfWeek(d)
  return DAY_NAMES.indexOf(dayName)
}

function Dashboard({ autoSync = false, onSyncTriggered }) {
  const [assignments, setAssignments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [updatingIds, setUpdatingIds] = useState(new Set())
  const [toasts, setToasts] = useState([])
  const [lastSyncTime, setLastSyncTime] = useState(null)
  const [isSyncing, setIsSyncing] = useState(false)
  const [syncStatus, setSyncStatus] = useState(null)

  // Navigation
  const [activeView, setActiveView] = useState('week')

  // Filters for All view
  const [selectedCourse, setSelectedCourse] = useState('all')
  const [selectedStatus, setSelectedStatus] = useState('all')

  // Detail modal
  const [selectedAssignment, setSelectedAssignment] = useState(null)

  // Ref to trigger sync from SyncButton
  const [triggerSync, setTriggerSync] = useState(false)

  // Sidebar collapsed state
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  const addToast = useCallback((message, type = 'success') => {
    const id = Date.now()
    setToasts((prev) => [...prev, { id, message, type }])
  }, [])

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id))
  }, [])

  useEffect(() => {
    fetchAssignments()
    fetchLastSync()
  }, [])

  // Handle auto-sync after login
  useEffect(() => {
    if (autoSync) {
      console.log('[Dashboard] Auto-sync triggered after login')
      setTriggerSync(true)
      if (onSyncTriggered) {
        onSyncTriggered()
      }
    }
  }, [autoSync, onSyncTriggered])

  // Poll for new assignments while a sync is in progress
  useEffect(() => {
    if (!isSyncing) return

    const interval = setInterval(() => {
      console.log('[Dashboard] Polling assignments during sync...')
      fetchAssignments()
    }, 5000)

    return () => clearInterval(interval)
  }, [isSyncing])

  const handleSyncStarted = useCallback(() => {
    setTriggerSync(false)
    setIsSyncing(true)
  }, [])

  const fetchAssignments = async () => {
    try {
      console.log('[Dashboard] Fetching assignments from:', `${API_BASE}/assignments`)
      const response = await fetch(`${API_BASE}/assignments`)
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }
      const data = await response.json()
      setAssignments(data.assignments || [])
      setError(null)
    } catch (err) {
      console.error('[Dashboard] Failed to fetch assignments:', err)
      setError(`Failed to load assignments. Make sure the backend is running on ${API_BASE}`)
    } finally {
      setLoading(false)
    }
  }

  const fetchLastSync = async () => {
    try {
      const response = await fetch(`${API_BASE}/sync/last`)
      if (!response.ok) return
      const data = await response.json()
      if (data.last_sync?.last_sync_at) {
        setLastSyncTime(data.last_sync.last_sync_at)
      }
    } catch (err) {
      console.error('[Dashboard] Error fetching last sync:', err)
    }
  }

  const handleSyncProgress = useCallback((data) => {
    setSyncStatus(data)
  }, [])

  const handleSyncComplete = useCallback(() => {
    setIsSyncing(false)
    setSyncStatus(null)
    fetchAssignments()
    fetchLastSync()
  }, [])

  const handleStatusChange = useCallback(async (assignmentId, newStatus) => {
    const originalAssignment = assignments.find((a) => a.id === assignmentId)
    if (!originalAssignment) return
    const originalStatus = originalAssignment.status

    setAssignments((prev) =>
      prev.map((a) =>
        a.id === assignmentId ? { ...a, status: newStatus } : a
      )
    )

    setUpdatingIds((prev) => new Set([...prev, assignmentId]))

    try {
      const response = await fetch(
        `${API_BASE}/assignments/${assignmentId}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: newStatus }),
        }
      )

      if (!response.ok) throw new Error('Failed to update status')

      const data = await response.json()
      setAssignments((prev) =>
        prev.map((a) => (a.id === assignmentId ? data.assignment : a))
      )

      addToast(`Moved to "${STATUS_LABELS[newStatus]}"`, 'success')
    } catch (err) {
      console.error('Failed to update assignment:', err)
      setAssignments((prev) =>
        prev.map((a) =>
          a.id === assignmentId ? { ...a, status: originalStatus } : a
        )
      )
      addToast('Failed to update status. Please try again.', 'error')
    } finally {
      setUpdatingIds((prev) => {
        const next = new Set(prev)
        next.delete(assignmentId)
        return next
      })
    }
  }, [assignments, addToast])

  // Quick actions
  const handleMarkStarted = useCallback((assignmentId) => {
    handleStatusChange(assignmentId, 'in_progress')
  }, [handleStatusChange])

  const handleMarkDone = useCallback((assignmentId) => {
    handleStatusChange(assignmentId, 'submitted')
  }, [handleStatusChange])

  // Open detail modal
  const handleOpenDetail = useCallback((assignment) => {
    setSelectedAssignment(assignment)
  }, [])

  // Update assignment from detail modal
  const handleAssignmentUpdate = useCallback((updatedAssignment) => {
    setAssignments((prev) =>
      prev.map((a) => (a.id === updatedAssignment.id ? updatedAssignment : a))
    )
    addToast('Assignment updated', 'success')
  }, [addToast])

  // Get unique courses
  const courses = useMemo(() => {
    const courseSet = new Set(assignments.map((a) => a.course_name))
    return ['all', ...Array.from(courseSet).sort()]
  }, [assignments])

  // Active assignments: filter out submitted past-due assignments
  const activeAssignments = useMemo(() => {
    const now = new Date()
    return assignments.filter((a) => {
      // Hide submitted assignments that are past due
      if (a.status === 'submitted' && a.due_date) {
        const dueDate = new Date(a.due_date)
        if (dueDate < now) return false
      }
      return true
    })
  }, [assignments])

  // This Week view data: organized by day (Mon-Sun)
  const weekData = useMemo(() => {
    const now = new Date()
    const todayStr = getMtDateStr(now)
    const todayDayIndex = getMtDayIndex(now)

    // Calculate Monday of this week
    const mondayOffset = todayDayIndex === 0 ? -6 : 1 - todayDayIndex
    const monday = new Date(now.getTime() + mondayOffset * 86400000)

    // Build array of 7 days Mon-Sun
    const days = []
    for (let i = 0; i < 7; i++) {
      const dayDate = new Date(monday.getTime() + i * 86400000)
      const dateStr = getMtDateStr(dayDate)
      const dayIndex = (getMtDayIndex(dayDate))
      days.push({
        date: dayDate,
        dateStr,
        dayName: DAY_NAMES[dayIndex],
        dayNameShort: DAY_NAMES_SHORT[dayIndex],
        dayNum: new Intl.DateTimeFormat('en-US', { timeZone: 'America/Denver', day: 'numeric' }).format(dayDate),
        monthShort: new Intl.DateTimeFormat('en-US', { timeZone: 'America/Denver', month: 'short' }).format(dayDate),
        isToday: dateStr === todayStr,
        isPast: dateStr < todayStr,
        assignments: [],
      })
    }

    // Also collect overdue items (past due, not submitted)
    const overdue = []

    activeAssignments.forEach((a) => {
      if (!a.due_date) return
      if (a.status === 'unavailable') return

      const dueDate = new Date(a.due_date)
      const dueDateStr = getMtDateStr(dueDate)

      // Check if past due and not submitted
      if (dueDate < now && a.status !== 'submitted') {
        // Only include if the due date is before this week's Monday
        const mondayStr = days[0].dateStr
        if (dueDateStr < mondayStr) {
          overdue.push(a)
          return
        }
      }

      // Place into the correct day bucket
      const dayMatch = days.find(d => d.dateStr === dueDateStr)
      if (dayMatch) {
        dayMatch.assignments.push(a)
      }
    })

    // Sort assignments within each day by due_date
    days.forEach(d => d.assignments.sort((a, b) => new Date(a.due_date) - new Date(b.due_date)))
    overdue.sort((a, b) => new Date(a.due_date) - new Date(b.due_date))

    return { days, overdue }
  }, [activeAssignments])

  // Upcoming view: assignments beyond this week, grouped by week
  const upcomingData = useMemo(() => {
    const now = new Date()
    const todayDayIndex = getMtDayIndex(now)

    // Calculate end of this week (Sunday)
    const daysUntilSunday = todayDayIndex === 0 ? 0 : 7 - todayDayIndex
    const sundayDate = new Date(now.getTime() + daysUntilSunday * 86400000)
    const sundayStr = getMtDateStr(sundayDate)

    const futureAssignments = activeAssignments.filter((a) => {
      if (!a.due_date) return false
      if (a.status === 'unavailable') return false
      const dueDateStr = getMtDateStr(new Date(a.due_date))
      return dueDateStr > sundayStr
    }).sort((a, b) => new Date(a.due_date) - new Date(b.due_date))

    // Group by week
    const weeks = new Map()
    futureAssignments.forEach((a) => {
      const dueDate = new Date(a.due_date)
      const dueDayIndex = getMtDayIndex(dueDate)
      const mondayOffset = dueDayIndex === 0 ? -6 : 1 - dueDayIndex
      const weekMonday = new Date(dueDate.getTime() + mondayOffset * 86400000)
      const weekKey = getMtDateStr(weekMonday)

      if (!weeks.has(weekKey)) {
        const weekSunday = new Date(weekMonday.getTime() + 6 * 86400000)
        const monthDay = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Denver', month: 'short', day: 'numeric' })
        weeks.set(weekKey, {
          label: `${monthDay.format(weekMonday)} - ${monthDay.format(weekSunday)}`,
          assignments: [],
        })
      }
      weeks.get(weekKey).assignments.push(a)
    })

    return Array.from(weeks.values())
  }, [activeAssignments])

  // By Course view
  const courseData = useMemo(() => {
    const grouped = new Map()
    activeAssignments.forEach((a) => {
      if (a.status === 'unavailable') return
      const course = a.course_name || 'Unknown Course'
      if (!grouped.has(course)) {
        grouped.set(course, [])
      }
      grouped.get(course).push(a)
    })

    // Sort each course's assignments by due_date
    const result = Array.from(grouped.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, items]) => ({
        name,
        assignments: items.sort((a, b) => {
          const aDate = a.due_date ? new Date(a.due_date) : new Date(9999, 0)
          const bDate = b.due_date ? new Date(b.due_date) : new Date(9999, 0)
          return aDate - bDate
        }),
      }))

    return result
  }, [activeAssignments])

  // All Assignments view with filters
  const allFilteredAssignments = useMemo(() => {
    return assignments.filter((a) => {
      if (selectedCourse !== 'all' && a.course_name !== selectedCourse) return false
      if (selectedStatus !== 'all' && a.status !== selectedStatus) return false
      return true
    }).sort((a, b) => {
      const aDate = a.due_date ? new Date(a.due_date) : new Date(9999, 0)
      const bDate = b.due_date ? new Date(b.due_date) : new Date(9999, 0)
      return aDate - bDate
    })
  }, [assignments, selectedCourse, selectedStatus])

  // Stats
  const stats = useMemo(() => {
    const now = new Date()
    const todayStr = getMtDateStr(now)

    const todayDayIndex = getMtDayIndex(now)
    const mondayOffset = todayDayIndex === 0 ? -6 : 1 - todayDayIndex
    const monday = new Date(now.getTime() + mondayOffset * 86400000)

    const thisWeekDates = new Set()
    for (let i = 0; i < 7; i++) {
      thisWeekDates.add(getMtDateStr(new Date(monday.getTime() + i * 86400000)))
    }

    let dueToday = 0
    let dueThisWeek = 0
    let overdue = 0
    let inProgress = 0

    activeAssignments.forEach((a) => {
      if (!a.due_date || a.status === 'unavailable') return

      const dueDate = new Date(a.due_date)
      const dueDateStr = getMtDateStr(dueDate)

      if (dueDate < now && a.status !== 'submitted') {
        overdue++
      }

      if (dueDateStr === todayStr && a.status !== 'submitted') {
        dueToday++
      }

      if (thisWeekDates.has(dueDateStr) && a.status !== 'submitted') {
        dueThisWeek++
      }

      if (a.status === 'in_progress') {
        inProgress++
      }
    })

    return { dueToday, dueThisWeek, overdue, inProgress }
  }, [activeAssignments])

  // Today's plan: overdue + due today + in-progress items
  const todaysPlan = useMemo(() => {
    const now = new Date()
    const todayStr = getMtDateStr(now)

    return activeAssignments.filter((a) => {
      if (!a.due_date || a.status === 'unavailable' || a.status === 'submitted') return false
      const dueDate = new Date(a.due_date)
      const dueDateStr = getMtDateStr(dueDate)

      // Overdue
      if (dueDate < now && a.status !== 'submitted') return true
      // Due today
      if (dueDateStr === todayStr) return true
      // In progress
      if (a.status === 'in_progress') return true

      return false
    }).sort((a, b) => {
      // Overdue first, then due today, then in-progress
      const now = new Date()
      const aOverdue = new Date(a.due_date) < now ? 0 : 1
      const bOverdue = new Date(b.due_date) < now ? 0 : 1
      if (aOverdue !== bOverdue) return aOverdue - bOverdue
      return new Date(a.due_date) - new Date(b.due_date)
    })
  }, [activeAssignments])

  const hasNeverSynced = !lastSyncTime && assignments.length === 0

  const renderAssignmentCard = (assignment, compact = false) => (
    <AssignmentCard
      key={assignment.id}
      assignment={assignment}
      onStatusChange={handleStatusChange}
      onMarkStarted={handleMarkStarted}
      onMarkDone={handleMarkDone}
      onOpenDetail={handleOpenDetail}
      isUpdating={updatingIds.has(assignment.id)}
      compact={compact}
    />
  )

  // Navigation items
  const navItems = [
    {
      id: 'week',
      label: 'This Week',
      icon: (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      ),
    },
    {
      id: 'upcoming',
      label: 'Upcoming',
      icon: (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="13 17 18 12 13 7" />
          <polyline points="6 17 11 12 6 7" />
        </svg>
      ),
    },
    {
      id: 'course',
      label: 'By Course',
      icon: (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
        </svg>
      ),
    },
    {
      id: 'all',
      label: 'All',
      icon: (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <line x1="8" y1="6" x2="21" y2="6" />
          <line x1="8" y1="12" x2="21" y2="12" />
          <line x1="8" y1="18" x2="21" y2="18" />
          <line x1="3" y1="6" x2="3.01" y2="6" />
          <line x1="3" y1="12" x2="3.01" y2="12" />
          <line x1="3" y1="18" x2="3.01" y2="18" />
        </svg>
      ),
    },
  ]

  // Render This Week view
  const renderWeekView = () => {
    return (
      <div className="view-week">
        {/* Today's Plan */}
        {todaysPlan.length > 0 && (
          <section className="todays-plan">
            <div className="section-header">
              <h2 className="section-title">Today&apos;s Plan</h2>
              <span className="section-count">{todaysPlan.length}</span>
            </div>
            <div className="plan-cards">
              {todaysPlan.map((a) => renderAssignmentCard(a, true))}
            </div>
          </section>
        )}

        {/* Overdue banner */}
        {weekData.overdue.length > 0 && (
          <section className="overdue-section">
            <div className="section-header">
              <h2 className="section-title overdue-title">
                <span className="urgency-dot urgency-overdue" />
                Overdue
              </h2>
              <span className="section-count overdue-count">{weekData.overdue.length}</span>
            </div>
            <div className="day-assignments">
              {weekData.overdue.map((a) => renderAssignmentCard(a, true))}
            </div>
          </section>
        )}

        {/* Week days */}
        <div className="week-grid">
          {weekData.days.map((day) => {
            const hasAssignments = day.assignments.length > 0
            const isToday = day.isToday

            return (
              <div
                key={day.dateStr}
                className={`day-column ${isToday ? 'is-today' : ''} ${day.isPast && !isToday ? 'is-past' : ''} ${!hasAssignments ? 'is-empty' : ''}`}
              >
                <div className="day-header">
                  <div className="day-label">
                    <span className="day-name">{day.dayNameShort}</span>
                    <span className={`day-number ${isToday ? 'today-number' : ''}`}>{day.dayNum}</span>
                  </div>
                  {hasAssignments && (
                    <span className="day-count">{day.assignments.length}</span>
                  )}
                </div>
                <div className="day-assignments">
                  {hasAssignments ? (
                    day.assignments.map((a) => renderAssignmentCard(a, true))
                  ) : (
                    <div className="day-empty">
                      <span className="day-empty-text">
                        {day.isPast && !isToday ? 'Done' : 'Free'}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  // Render Upcoming view
  const renderUpcomingView = () => (
    <div className="view-upcoming">
      {upcomingData.length === 0 ? (
        <div className="empty-view">
          <div className="empty-view-icon">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
              <polyline points="22 4 12 14.01 9 11.01" />
            </svg>
          </div>
          <h3 className="empty-view-title">Nothing upcoming</h3>
          <p className="empty-view-desc">No assignments scheduled beyond this week.</p>
        </div>
      ) : (
        upcomingData.map((week, i) => (
          <section key={i} className="upcoming-week-section">
            <div className="section-header">
              <h2 className="section-title">{week.label}</h2>
              <span className="section-count">{week.assignments.length}</span>
            </div>
            <div className="upcoming-week-list">
              {week.assignments.map((a) => renderAssignmentCard(a))}
            </div>
          </section>
        ))
      )}
    </div>
  )

  // Render By Course view
  const renderCourseView = () => (
    <div className="view-courses">
      {courseData.length === 0 ? (
        <div className="empty-view">
          <div className="empty-view-icon">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
          </div>
          <h3 className="empty-view-title">No courses</h3>
          <p className="empty-view-desc">Sync to import your course assignments.</p>
        </div>
      ) : (
        courseData.map((course) => (
          <section key={course.name} className="course-section">
            <div className="section-header">
              <h2 className="section-title">{course.name}</h2>
              <span className="section-count">{course.assignments.length}</span>
            </div>
            <div className="course-list">
              {course.assignments.map((a) => renderAssignmentCard(a))}
            </div>
          </section>
        ))
      )}
    </div>
  )

  // Render All Assignments view
  const renderAllView = () => (
    <div className="view-all">
      {/* Filters */}
      <div className="all-filters">
        <div className="filter-group">
          <select
            className="filter-select"
            value={selectedCourse}
            onChange={(e) => setSelectedCourse(e.target.value)}
            aria-label="Filter by course"
          >
            <option value="all">All Courses</option>
            {courses.filter((c) => c !== 'all').map((course) => (
              <option key={course} value={course}>
                {course}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-pills">
          {[
            { value: 'all', label: 'All' },
            { value: 'not_started', label: 'Not Started' },
            { value: 'in_progress', label: 'In Progress' },
            { value: 'submitted', label: 'Submitted' },
            { value: 'newly_assigned', label: 'New' },
          ].map((opt) => (
            <button
              key={opt.value}
              className={`filter-pill ${selectedStatus === opt.value ? 'is-active' : ''}`}
              onClick={() => setSelectedStatus(opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {allFilteredAssignments.length === 0 ? (
        <div className="empty-view">
          <h3 className="empty-view-title">No matching assignments</h3>
          <p className="empty-view-desc">Try adjusting your filters.</p>
          <button
            className="btn btn-ghost"
            onClick={() => {
              setSelectedCourse('all')
              setSelectedStatus('all')
            }}
          >
            Clear filters
          </button>
        </div>
      ) : (
        <div className="all-list">
          {allFilteredAssignments.map((a) => renderAssignmentCard(a))}
        </div>
      )}
    </div>
  )

  // View titles
  const viewTitles = {
    week: 'This Week',
    upcoming: 'Upcoming',
    course: 'By Course',
    all: 'All Assignments',
  }

  // Loading state
  if (loading) {
    return (
      <div className="dashboard-layout">
        <aside className="sidebar">
          <div className="sidebar-brand">
            <div className="brand-logo">C</div>
            <span className="brand-name">CampusAI</span>
          </div>
        </aside>
        <div className="main-area">
          <header className="top-bar">
            <div className="top-bar-inner">
              <h1 className="view-title">Loading...</h1>
            </div>
          </header>
          <main className="content-area">
            <div className="loading-skeleton">
              <div className="skeleton-stats-row">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="skeleton-stat" />
                ))}
              </div>
              <div className="skeleton-cards">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="skeleton-card" />
                ))}
              </div>
            </div>
          </main>
        </div>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className="dashboard-layout">
        <aside className="sidebar">
          <div className="sidebar-brand">
            <div className="brand-logo">C</div>
            <span className="brand-name">CampusAI</span>
          </div>
        </aside>
        <div className="main-area">
          <header className="top-bar">
            <div className="top-bar-inner">
              <h1 className="view-title">Connection Error</h1>
            </div>
          </header>
          <main className="content-area">
            <div className="error-state">
              <div className="error-icon-wrap">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="8" x2="12" y2="12" />
                  <line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
              </div>
              <h2 className="error-heading">Unable to connect</h2>
              <p className="error-desc">{error}</p>
              <button className="btn btn-primary" onClick={fetchAssignments}>
                Try Again
              </button>
            </div>
          </main>
        </div>
      </div>
    )
  }

  return (
    <div className="dashboard-layout">
      {/* Sidebar Navigation */}
      <aside className={`sidebar ${sidebarCollapsed ? 'is-collapsed' : ''}`}>
        <div className="sidebar-brand">
          <div className="brand-logo">C</div>
          {!sidebarCollapsed && <span className="brand-name">CampusAI</span>}
        </div>

        <nav className="sidebar-nav">
          {navItems.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${activeView === item.id ? 'is-active' : ''}`}
              onClick={() => setActiveView(item.id)}
              title={item.label}
            >
              <span className="nav-icon">{item.icon}</span>
              {!sidebarCollapsed && <span className="nav-label">{item.label}</span>}
            </button>
          ))}
        </nav>

        <button
          className="sidebar-collapse-btn"
          onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
          title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            {sidebarCollapsed ? (
              <polyline points="9 18 15 12 9 6" />
            ) : (
              <polyline points="15 18 9 12 15 6" />
            )}
          </svg>
        </button>
      </aside>

      {/* Main Content */}
      <div className="main-area">
        {/* Top Bar */}
        <header className="top-bar">
          <div className="top-bar-inner">
            <div className="top-bar-left">
              <h1 className="view-title">{viewTitles[activeView]}</h1>
            </div>
            <div className="top-bar-right">
              <SyncButton
                onSyncComplete={handleSyncComplete}
                triggerSync={triggerSync}
                onSyncStarted={handleSyncStarted}
                onSyncProgress={handleSyncProgress}
              />
            </div>
          </div>
        </header>

        {/* Sync Progress Banner */}
        {isSyncing && syncStatus && (
          <div className="sync-progress-banner">
            <div className="sync-progress-inner">
              <div className="sync-progress-left">
                <div className="sync-pulse-ring">
                  <span className="sync-pulse-dot" />
                </div>
                <div className="sync-progress-info">
                  <span className="sync-progress-label">
                    {syncStatus.total_courses > 0 ? 'SYNCING' : 'CONNECTING'}
                  </span>
                  <span className="sync-progress-detail">
                    {syncStatus.total_courses > 0
                      ? (syncStatus.current_course_name || 'Processing...')
                      : (syncStatus.message || 'Starting sync...')}
                  </span>
                </div>
              </div>
              {syncStatus.total_courses > 0 && (
                <div className="sync-progress-right">
                  <span className="sync-progress-fraction">
                    {syncStatus.current_course}<span className="sync-fraction-sep">/</span>{syncStatus.total_courses}
                  </span>
                  <div className="sync-progress-track">
                    <div
                      className="sync-progress-fill"
                      style={{ width: `${(syncStatus.current_course / syncStatus.total_courses) * 100}%` }}
                    />
                  </div>
                </div>
              )}
            </div>
            <div className="sync-scanline" />
          </div>
        )}

        <main className="content-area">
          {/* Never synced banner */}
          {hasNeverSynced && (
            <div className="welcome-banner">
              <div className="welcome-icon">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="16" x2="12" y2="12" />
                  <line x1="12" y1="8" x2="12.01" y2="8" />
                </svg>
              </div>
              <div className="welcome-text">
                <strong>Welcome to CampusAI</strong>
                <span>Click Sync to import your Learning Suite assignments.</span>
              </div>
            </div>
          )}

          {/* Stats strip */}
          {!hasNeverSynced && (activeView === 'week') && (
            <div className="stats-strip">
              <div className={`stat-item ${stats.overdue > 0 ? 'stat-urgent' : ''}`}>
                <span className="stat-number">{stats.overdue}</span>
                <span className="stat-text">Overdue</span>
              </div>
              <div className="stat-divider" />
              <div className="stat-item">
                <span className="stat-number">{stats.dueToday}</span>
                <span className="stat-text">Due Today</span>
              </div>
              <div className="stat-divider" />
              <div className="stat-item stat-accent">
                <span className="stat-number">{stats.dueThisWeek}</span>
                <span className="stat-text">This Week</span>
              </div>
              <div className="stat-divider" />
              <div className="stat-item">
                <span className="stat-number">{stats.inProgress}</span>
                <span className="stat-text">In Progress</span>
              </div>
            </div>
          )}

          {/* View content */}
          <div className="view-content">
            {activeView === 'week' && renderWeekView()}
            {activeView === 'upcoming' && renderUpcomingView()}
            {activeView === 'course' && renderCourseView()}
            {activeView === 'all' && renderAllView()}
          </div>

          {/* Empty state when no assignments at all */}
          {assignments.length === 0 && !hasNeverSynced && (
            <div className="empty-view">
              <div className="empty-view-icon">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <line x1="16" y1="17" x2="8" y2="17" />
                </svg>
              </div>
              <h3 className="empty-view-title">No assignments found</h3>
              <p className="empty-view-desc">Try syncing again or check your Learning Suite courses.</p>
            </div>
          )}
        </main>
      </div>

      {/* Assignment Detail Modal */}
      {selectedAssignment && (
        <AssignmentDetail
          assignment={selectedAssignment}
          onClose={() => setSelectedAssignment(null)}
          onUpdate={handleAssignmentUpdate}
        />
      )}

      <ToastContainer toasts={toasts} removeToast={removeToast} />
    </div>
  )
}

export default Dashboard
