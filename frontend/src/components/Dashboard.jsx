import { useState, useEffect, useCallback, useMemo } from 'react'
import AssignmentCard from './AssignmentCard'
import AssignmentDetail from './AssignmentDetail'
import SyncButton from './SyncButton'
import { ToastContainer } from './Toast'
import { API_BASE } from '../config/api'
import './Dashboard.css'

const STATUS_OPTIONS = [
  { value: 'all', label: 'All', icon: null },
  { value: 'not_started', label: 'Not Started', color: 'slate' },
  { value: 'in_progress', label: 'In Progress', color: 'warning' },
  { value: 'submitted', label: 'Submitted', color: 'success' },
  { value: 'unavailable', label: 'Unavailable', color: 'muted' },
]

const STATUS_LABELS = {
  newly_assigned: 'New',
  not_started: 'Not Started',
  in_progress: 'In Progress',
  submitted: 'Submitted',
  unavailable: 'Unavailable',
}

function Dashboard({ autoSync = false, onSyncTriggered }) {
  const [assignments, setAssignments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [updatingIds, setUpdatingIds] = useState(new Set())
  const [toasts, setToasts] = useState([])
  const [lastSyncTime, setLastSyncTime] = useState(null)
  const [isSyncing, setIsSyncing] = useState(false)

  // Filters
  const [selectedCourse, setSelectedCourse] = useState('all')
  const [selectedStatus, setSelectedStatus] = useState('all')

  // Detail modal
  const [selectedAssignment, setSelectedAssignment] = useState(null)

  // Ref to trigger sync from SyncButton
  const [triggerSync, setTriggerSync] = useState(false)

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

  const handleSyncComplete = useCallback(() => {
    setIsSyncing(false)
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

  // Filter assignments
  const filteredAssignments = useMemo(() => {
    return assignments.filter((a) => {
      if (selectedCourse !== 'all' && a.course_name !== selectedCourse) return false
      if (selectedStatus !== 'all' && a.status !== selectedStatus) return false
      return true
    })
  }, [assignments, selectedCourse, selectedStatus])

  // Group by time categories
  const groupedAssignments = useMemo(() => {
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const tomorrow = new Date(today)
    tomorrow.setDate(tomorrow.getDate() + 1)
    const dayAfterTomorrow = new Date(today)
    dayAfterTomorrow.setDate(dayAfterTomorrow.getDate() + 2)
    const nextWeek = new Date(today)
    nextWeek.setDate(nextWeek.getDate() + 7)

    const groups = {
      overdue: [],
      today: [],
      tomorrow: [],
      thisWeek: [],
      later: [],
    }

    filteredAssignments.forEach((assignment) => {
      const dueDate = new Date(assignment.due_date)
      const dueDateOnly = new Date(dueDate.getFullYear(), dueDate.getMonth(), dueDate.getDate())

      if (dueDate < now && assignment.status !== 'submitted') {
        groups.overdue.push(assignment)
      } else if (dueDateOnly.getTime() === today.getTime()) {
        groups.today.push(assignment)
      } else if (dueDateOnly.getTime() === tomorrow.getTime()) {
        groups.tomorrow.push(assignment)
      } else if (dueDateOnly < nextWeek) {
        groups.thisWeek.push(assignment)
      } else {
        groups.later.push(assignment)
      }
    })

    // Sort each group by due date
    Object.values(groups).forEach((group) =>
      group.sort((a, b) => new Date(a.due_date) - new Date(b.due_date))
    )

    return groups
  }, [filteredAssignments])

  // Today panel items (overdue + today + tomorrow)
  const todayPanelItems = useMemo(() => {
    return [
      ...groupedAssignments.overdue,
      ...groupedAssignments.today,
      ...groupedAssignments.tomorrow,
    ]
  }, [groupedAssignments])

  // Upcoming items (this week + later)
  const upcomingItems = useMemo(() => {
    return [...groupedAssignments.thisWeek, ...groupedAssignments.later]
  }, [groupedAssignments])

  // Stats with analytics
  const stats = useMemo(() => {
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const nextWeek = new Date(today)
    nextWeek.setDate(nextWeek.getDate() + 7)

    const total = assignments.length
    const submitted = assignments.filter((a) => a.status === 'submitted').length
    const active = assignments.filter((a) => a.status !== 'submitted' && a.status !== 'unavailable').length
    const overdue = groupedAssignments.overdue.length
    const dueToday = groupedAssignments.today.length
    const inProgress = assignments.filter((a) => a.status === 'in_progress').length

    // Due this week calculation
    let dueThisWeek = 0
    assignments.forEach((a) => {
      if (a.status !== 'submitted' && a.due_date) {
        try {
          const dueDate = new Date(a.due_date)
          const dueDateOnly = new Date(dueDate.getFullYear(), dueDate.getMonth(), dueDate.getDate())
          if (dueDateOnly >= today && dueDateOnly < nextWeek) {
            dueThisWeek++
          }
        } catch {
          // Ignore invalid dates
        }
      }
    })

    // Completion rate
    const completionRate = total > 0 ? Math.round((submitted / total) * 100) : 0

    return {
      active,
      overdue,
      dueToday,
      inProgress,
      dueThisWeek,
      completionRate,
      total,
      submitted,
    }
  }, [assignments, groupedAssignments])

  const hasNeverSynced = !lastSyncTime && assignments.length === 0

  // Render header
  const renderHeader = () => (
    <header className="app-header">
      <div className="header-container">
        <div className="header-brand">
          <div className="brand-logo">C</div>
          <div className="brand-text">
            <span className="brand-name">CampusAI</span>
            <span className="brand-tagline">Assignment Manager</span>
          </div>
        </div>
        <SyncButton
          onSyncComplete={handleSyncComplete}
          triggerSync={triggerSync}
          onSyncStarted={handleSyncStarted}
        />
      </div>
    </header>
  )

  // Loading state with skeleton
  if (loading) {
    return (
      <div className="dashboard">
        {renderHeader()}
        <main className="dashboard-main">
          <div className="command-center">
            <div className="stats-bar skeleton-stats">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="stat-card skeleton" />
              ))}
            </div>
            <div className="today-panel">
              <div className="panel-header">
                <div className="skeleton skeleton-text" style={{ width: '120px' }} />
              </div>
              <div className="panel-content">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="skeleton skeleton-card" />
                ))}
              </div>
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
        {renderHeader()}
        <main className="dashboard-main">
          <div className="error-state">
            <div className="error-icon">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <h2 className="error-title">Connection Error</h2>
            <p className="error-message">{error}</p>
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
      {renderHeader()}

      <main className="dashboard-main">
        {/* Sync Banner */}
        {hasNeverSynced && (
          <div className="sync-banner">
            <div className="sync-banner-icon">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="16" x2="12" y2="12" />
                <line x1="12" y1="8" x2="12.01" y2="8" />
              </svg>
            </div>
            <div className="sync-banner-content">
              <strong>Sync to load Learning Suite data</strong>
              <span>Click the Sync button above to import your assignments</span>
            </div>
          </div>
        )}

        {/* Stats Bar with Analytics */}
        <div className="stats-bar">
          <div className={`stat-card ${stats.overdue > 0 ? 'stat-alert' : ''}`}>
            <span className="stat-value">{stats.overdue}</span>
            <span className="stat-label">Overdue</span>
          </div>
          <div className="stat-card stat-highlight">
            <span className="stat-value">{stats.dueThisWeek}</span>
            <span className="stat-label">Due This Week</span>
          </div>
          <div className="stat-card">
            <span className="stat-value">{stats.inProgress}</span>
            <span className="stat-label">In Progress</span>
          </div>
          <div className="stat-card stat-success">
            <span className="stat-value">{stats.completionRate}%</span>
            <span className="stat-label">Submitted</span>
          </div>
        </div>

        {/* Filters */}
        <div className="filters-bar">
          <div className="filter-group">
            <label className="filter-label">Course</label>
            <select
              className="filter-select"
              value={selectedCourse}
              onChange={(e) => setSelectedCourse(e.target.value)}
            >
              <option value="all">All Courses</option>
              {courses.filter((c) => c !== 'all').map((course) => (
                <option key={course} value={course}>
                  {course}
                </option>
              ))}
            </select>
          </div>

          <div className="filter-group status-chips">
            <label className="filter-label">Status</label>
            <div className="chip-group">
              {STATUS_OPTIONS.map((status) => (
                <button
                  key={status.value}
                  className={`status-chip ${selectedStatus === status.value ? 'active' : ''} chip-${status.color || 'default'}`}
                  onClick={() => setSelectedStatus(status.value)}
                >
                  {status.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Command Center Layout */}
        <div className="command-center">
          {/* Today Panel */}
          <section className="today-panel">
            <div className="panel-header">
              <h2 className="panel-title">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
                Focus
              </h2>
              <span className="panel-count">{todayPanelItems.length}</span>
            </div>

            {todayPanelItems.length === 0 ? (
              <div className="panel-empty">
                <div className="empty-icon-small">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                    <polyline points="22 4 12 14.01 9 11.01" />
                  </svg>
                </div>
                <p>Nothing urgent right now</p>
                <span className="empty-hint">You're all caught up!</span>
              </div>
            ) : (
              <div className="panel-content">
                {/* Overdue Section */}
                {groupedAssignments.overdue.length > 0 && (
                  <div className="focus-section focus-overdue">
                    <h3 className="focus-section-title">
                      <span className="focus-dot overdue" />
                      Overdue
                    </h3>
                    <div className="focus-items">
                      {groupedAssignments.overdue.map((assignment) => (
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
                      ))}
                    </div>
                  </div>
                )}

                {/* Today Section */}
                {groupedAssignments.today.length > 0 && (
                  <div className="focus-section focus-today">
                    <h3 className="focus-section-title">
                      <span className="focus-dot today" />
                      Today
                    </h3>
                    <div className="focus-items">
                      {groupedAssignments.today.map((assignment) => (
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
                      ))}
                    </div>
                  </div>
                )}

                {/* Tomorrow Section */}
                {groupedAssignments.tomorrow.length > 0 && (
                  <div className="focus-section focus-tomorrow">
                    <h3 className="focus-section-title">
                      <span className="focus-dot tomorrow" />
                      Tomorrow
                    </h3>
                    <div className="focus-items">
                      {groupedAssignments.tomorrow.map((assignment) => (
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
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>

          {/* Upcoming Panel */}
          <section className="upcoming-panel">
            <div className="panel-header">
              <h2 className="panel-title">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                  <line x1="16" y1="2" x2="16" y2="6" />
                  <line x1="8" y1="2" x2="8" y2="6" />
                  <line x1="3" y1="10" x2="21" y2="10" />
                </svg>
                Upcoming
              </h2>
              <span className="panel-count">{upcomingItems.length}</span>
            </div>

            {upcomingItems.length === 0 ? (
              <div className="panel-empty">
                <div className="empty-icon-small">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                    <line x1="16" y1="2" x2="16" y2="6" />
                    <line x1="8" y1="2" x2="8" y2="6" />
                    <line x1="3" y1="10" x2="21" y2="10" />
                  </svg>
                </div>
                <p>No upcoming assignments</p>
                <span className="empty-hint">Sync to check for new ones</span>
              </div>
            ) : (
              <div className="panel-content upcoming-list">
                {/* This Week */}
                {groupedAssignments.thisWeek.length > 0 && (
                  <div className="upcoming-section">
                    <h3 className="upcoming-section-title">This Week</h3>
                    <div className="upcoming-items">
                      {groupedAssignments.thisWeek.map((assignment) => (
                        <AssignmentCard
                          key={assignment.id}
                          assignment={assignment}
                          onStatusChange={handleStatusChange}
                          onMarkStarted={handleMarkStarted}
                          onMarkDone={handleMarkDone}
                          onOpenDetail={handleOpenDetail}
                          isUpdating={updatingIds.has(assignment.id)}
                        />
                      ))}
                    </div>
                  </div>
                )}

                {/* Later */}
                {groupedAssignments.later.length > 0 && (
                  <div className="upcoming-section">
                    <h3 className="upcoming-section-title">Later</h3>
                    <div className="upcoming-items">
                      {groupedAssignments.later.map((assignment) => (
                        <AssignmentCard
                          key={assignment.id}
                          assignment={assignment}
                          onStatusChange={handleStatusChange}
                          onMarkStarted={handleMarkStarted}
                          onMarkDone={handleMarkDone}
                          onOpenDetail={handleOpenDetail}
                          isUpdating={updatingIds.has(assignment.id)}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>

        {/* Empty state when no assignments at all */}
        {assignments.length === 0 && !hasNeverSynced && (
          <div className="empty-state">
            <div className="empty-icon">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
            </div>
            <h3 className="empty-title">No assignments found</h3>
            <p className="empty-description">
              Try syncing again or check your Learning Suite courses.
            </p>
          </div>
        )}

        {/* No results for current filters */}
        {assignments.length > 0 && filteredAssignments.length === 0 && (
          <div className="no-results">
            <p>No assignments match your filters</p>
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
