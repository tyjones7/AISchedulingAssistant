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

const getMtDateStr = (d) => {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Denver', year: 'numeric', month: '2-digit', day: '2-digit'
  }).formatToParts(d)
  return `${parts.find(p => p.type === 'year').value}-${parts.find(p => p.type === 'month').value}-${parts.find(p => p.type === 'day').value}`
}

const getMtDayIndex = (d) => {
  const dayName = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Denver', weekday: 'long'
  }).format(d)
  return DAY_NAMES.indexOf(dayName)
}

const TIMELINE_SECTIONS = [
  { key: 'overdue', label: 'Overdue', urgency: 'overdue' },
  { key: 'today', label: 'Today', urgency: 'today' },
  { key: 'tomorrow', label: 'Tomorrow', urgency: 'tomorrow' },
  { key: 'thisWeek', label: 'This Week', urgency: 'normal' },
  { key: 'nextWeek', label: 'Next Week', urgency: 'normal' },
  { key: 'later', label: 'Later', urgency: 'normal', collapsible: true },
]

function Dashboard({ autoSync = false, onSyncTriggered, onLogout }) {
  const [assignments, setAssignments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [updatingIds, setUpdatingIds] = useState(new Set())
  const [toasts, setToasts] = useState([])
  const [lastSyncTime, setLastSyncTime] = useState(null)
  const [isSyncing, setIsSyncing] = useState(false)
  const [syncStatus, setSyncStatus] = useState(null)

  // Detail modal
  const [selectedAssignment, setSelectedAssignment] = useState(null)

  // Trigger sync from SyncButton
  const [triggerSync, setTriggerSync] = useState(false)

  // Later section collapsed by default
  const [laterCollapsed, setLaterCollapsed] = useState(true)

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
      setTriggerSync(true)
      if (onSyncTriggered) {
        onSyncTriggered()
      }
    }
  }, [autoSync, onSyncTriggered])

  // Poll for new assignments while sync is in progress
  useEffect(() => {
    if (!isSyncing) return
    const interval = setInterval(() => {
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
      const response = await fetch(`${API_BASE}/assignments?exclude_past_submitted=true`)
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

  const handleSyncComplete = useCallback((data) => {
    setIsSyncing(false)
    setSyncStatus(null)
    fetchAssignments()
    fetchLastSync()
    if (data && data.status === 'completed') {
      const added = data.assignments_added || 0
      const updated = data.assignments_updated || 0
      const courses = data.courses_scraped || 0
      addToast(`Sync complete: ${added} new, ${updated} updated from ${courses} courses`)
    }
  }, [addToast])

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

  const handleMarkStarted = useCallback((assignmentId) => {
    handleStatusChange(assignmentId, 'in_progress')
  }, [handleStatusChange])

  const handleMarkDone = useCallback((assignmentId) => {
    handleStatusChange(assignmentId, 'submitted')
  }, [handleStatusChange])

  const handleOpenDetail = useCallback((assignment) => {
    setSelectedAssignment(assignment)
  }, [])

  const handleAssignmentUpdate = useCallback((updatedAssignment) => {
    setAssignments((prev) =>
      prev.map((a) => (a.id === updatedAssignment.id ? updatedAssignment : a))
    )
    addToast('Assignment updated', 'success')
  }, [addToast])

  // Active assignments: filter out submitted past-due
  const activeAssignments = useMemo(() => {
    const now = new Date()
    return assignments.filter((a) => {
      if (a.status === 'submitted' && a.due_date) {
        const dueDate = new Date(a.due_date)
        if (dueDate < now) return false
      }
      return true
    })
  }, [assignments])

  // Timeline grouping: Overdue → Today → Tomorrow → This Week → Next Week → Later
  const timelineData = useMemo(() => {
    const now = new Date()
    const todayStr = getMtDateStr(now)
    const tomorrowStr = getMtDateStr(new Date(now.getTime() + 86400000))

    const todayDayIndex = getMtDayIndex(now)
    const daysUntilSunday = todayDayIndex === 0 ? 0 : 7 - todayDayIndex
    const sundayDate = new Date(now.getTime() + daysUntilSunday * 86400000)
    const sundayStr = getMtDateStr(sundayDate)

    const nextSundayDate = new Date(sundayDate.getTime() + 7 * 86400000)
    const nextSundayStr = getMtDateStr(nextSundayDate)

    const groups = {
      overdue: [],
      today: [],
      tomorrow: [],
      thisWeek: [],
      nextWeek: [],
      later: [],
    }

    activeAssignments.forEach((a) => {
      if (a.status === 'unavailable') return

      if (!a.due_date) {
        groups.later.push(a)
        return
      }

      const dueDate = new Date(a.due_date)
      const dueDateStr = getMtDateStr(dueDate)

      if (dueDate < now && a.status !== 'submitted') {
        groups.overdue.push(a)
      } else if (dueDateStr === todayStr) {
        groups.today.push(a)
      } else if (dueDateStr === tomorrowStr) {
        groups.tomorrow.push(a)
      } else if (dueDateStr > todayStr && dueDateStr <= sundayStr) {
        groups.thisWeek.push(a)
      } else if (dueDateStr > sundayStr && dueDateStr <= nextSundayStr) {
        groups.nextWeek.push(a)
      } else if (dueDateStr > nextSundayStr) {
        groups.later.push(a)
      }
    })

    const sortByDue = (a, b) => {
      const aDate = a.due_date ? new Date(a.due_date) : new Date(9999, 0)
      const bDate = b.due_date ? new Date(b.due_date) : new Date(9999, 0)
      return aDate - bDate
    }

    Object.values(groups).forEach(group => group.sort(sortByDue))

    return groups
  }, [activeAssignments])

  const hasNeverSynced = !lastSyncTime && assignments.length === 0
  const allClearToday = timelineData.overdue.length === 0 && timelineData.today.length === 0
    && assignments.length > 0 && !hasNeverSynced

  const renderAssignmentCard = (assignment) => (
    <AssignmentCard
      key={assignment.id}
      assignment={assignment}
      onStatusChange={handleStatusChange}
      onMarkStarted={handleMarkStarted}
      onMarkDone={handleMarkDone}
      onOpenDetail={handleOpenDetail}
      isUpdating={updatingIds.has(assignment.id)}
      compact
    />
  )

  const renderTimelineGroup = (section) => {
    const items = timelineData[section.key]
    if (!items || items.length === 0) return null

    const isCollapsed = section.collapsible && laterCollapsed

    return (
      <section key={section.key} className={`timeline-group urgency-${section.urgency}`}>
        <div
          className={`group-header ${section.collapsible ? 'is-collapsible' : ''}`}
          onClick={section.collapsible ? () => setLaterCollapsed(!laterCollapsed) : undefined}
        >
          <div className="group-label-row">
            {section.urgency === 'overdue' && <span className="urgency-dot" />}
            <h2 className="group-label">{section.label}</h2>
            <span className={`group-count ${section.urgency === 'overdue' ? 'count-overdue' : ''}`}>
              {items.length}
            </span>
          </div>
          {section.collapsible && (
            <svg
              className={`group-chevron ${isCollapsed ? 'is-collapsed' : ''}`}
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          )}
        </div>
        {!isCollapsed && (
          <div className="group-list">
            {items.map(renderAssignmentCard)}
          </div>
        )}
      </section>
    )
  }

  const logoutButton = onLogout ? (
    <button className="logout-btn" onClick={onLogout} title="Sign out" aria-label="Sign out">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
        <polyline points="16 17 21 12 16 7" />
        <line x1="21" y1="12" x2="9" y2="12" />
      </svg>
    </button>
  ) : null

  // Loading state
  if (loading) {
    return (
      <div className="dashboard">
        <header className="dash-header">
          <div className="dash-header-inner">
            <div className="dash-brand">
              <div className="brand-logo">C</div>
              <span className="brand-name">CampusAI</span>
            </div>
            <div className="dash-header-actions">
              {logoutButton}
            </div>
          </div>
        </header>
        <main className="dash-content">
          <div className="loading-skeleton">
            <div className="skeleton-group">
              <div className="skeleton-header" />
              {[1, 2, 3].map((i) => (
                <div key={i} className="skeleton-card" />
              ))}
            </div>
            <div className="skeleton-group">
              <div className="skeleton-header" />
              {[1, 2].map((i) => (
                <div key={i} className="skeleton-card" />
              ))}
            </div>
          </div>
        </main>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className="dashboard">
        <header className="dash-header">
          <div className="dash-header-inner">
            <div className="dash-brand">
              <div className="brand-logo">C</div>
              <span className="brand-name">CampusAI</span>
            </div>
            <div className="dash-header-actions">
              {logoutButton}
            </div>
          </div>
        </header>
        <main className="dash-content">
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
    )
  }

  return (
    <div className="dashboard">
      {/* Header */}
      <header className="dash-header">
        <div className="dash-header-inner">
          <div className="dash-brand">
            <div className="brand-logo">C</div>
            <span className="brand-name">CampusAI</span>
          </div>
          <div className="dash-header-actions">
            <SyncButton
              onSyncComplete={handleSyncComplete}
              triggerSync={triggerSync}
              onSyncStarted={handleSyncStarted}
              onSyncProgress={handleSyncProgress}
            />
            {logoutButton}
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

      <main className="dash-content">
        {/* Welcome banner for first-time users */}
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
              <span>Click Sync to import your assignments.</span>
            </div>
          </div>
        )}

        {/* All-clear message when nothing is due today */}
        {allClearToday && (
          <div className="all-clear">
            <div className="all-clear-icon">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </div>
            <p className="all-clear-text">Nothing due today. You&apos;re all caught up!</p>
          </div>
        )}

        {/* Timeline */}
        <div className="timeline">
          {TIMELINE_SECTIONS.map(renderTimelineGroup)}
        </div>

        {/* Empty state when no assignments at all */}
        {assignments.length === 0 && !hasNeverSynced && (
          <div className="empty-state">
            <div className="empty-state-icon">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
            </div>
            <h3 className="empty-state-title">No assignments found</h3>
            <p className="empty-state-desc">Try syncing again or check your Learning Suite / Canvas courses.</p>
          </div>
        )}
      </main>

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
