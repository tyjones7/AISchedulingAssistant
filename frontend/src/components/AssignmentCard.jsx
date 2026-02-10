import './AssignmentCard.css'

const STATUS_OPTIONS = [
  { value: 'newly_assigned', label: 'New' },
  { value: 'not_started', label: 'Not Started' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'submitted', label: 'Submitted' },
  { value: 'unavailable', label: 'Unavailable' },
]

const STATUS_LABELS = {
  newly_assigned: 'New',
  not_started: 'Not Started',
  in_progress: 'In Progress',
  submitted: 'Submitted',
  unavailable: 'Unavailable',
}

function AssignmentCard({
  assignment,
  onStatusChange,
  onMarkStarted,
  onMarkDone,
  onOpenDetail,
  isUpdating,
  compact = false,
}) {
  const formatDueDate = (dateString) => {
    const date = new Date(dateString)
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const tomorrow = new Date(today)
    tomorrow.setDate(tomorrow.getDate() + 1)
    const dueDay = new Date(date.getFullYear(), date.getMonth(), date.getDate())

    const timeStr = date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    })

    if (dueDay.getTime() === today.getTime()) {
      return `Today at ${timeStr}`
    } else if (dueDay.getTime() === tomorrow.getTime()) {
      return `Tomorrow at ${timeStr}`
    }

    return date.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    }).replace(',', ' at')
  }

  const formatPlannedTime = (startStr, endStr) => {
    if (!startStr) return null

    const start = new Date(startStr)
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const tomorrow = new Date(today)
    tomorrow.setDate(tomorrow.getDate() + 1)
    const startDay = new Date(start.getFullYear(), start.getMonth(), start.getDate())

    const startTime = start.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    })

    let dayLabel
    if (startDay.getTime() === today.getTime()) {
      dayLabel = 'Today'
    } else if (startDay.getTime() === tomorrow.getTime()) {
      dayLabel = 'Tomorrow'
    } else {
      dayLabel = start.toLocaleDateString('en-US', { weekday: 'short' })
    }

    if (endStr) {
      const end = new Date(endStr)
      const endTime = end.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        hour12: true,
      })
      return `${dayLabel} ${startTime}–${endTime}`
    }

    return `${dayLabel} ${startTime}`
  }

  const isPastDue = new Date(assignment.due_date) < new Date() && assignment.status !== 'submitted'

  const handleStatusChange = (e) => {
    e.stopPropagation()
    const newStatus = e.target.value
    if (newStatus !== assignment.status) {
      onStatusChange(assignment.id, newStatus)
    }
  }

  const handleCardClick = (e) => {
    // Don't open detail if clicking on interactive elements
    if (
      e.target.closest('.quick-action-btn') ||
      e.target.closest('.status-select') ||
      e.target.closest('a')
    ) {
      return
    }
    if (onOpenDetail) {
      onOpenDetail(assignment)
    }
  }

  const canMarkStarted = ['newly_assigned', 'not_started'].includes(assignment.status)
  const canMarkDone = ['newly_assigned', 'not_started', 'in_progress'].includes(assignment.status)

  const plannedTime = formatPlannedTime(assignment.planned_start, assignment.planned_end)

  const cardClasses = [
    'assignment-card',
    isUpdating && 'is-updating',
    compact && 'is-compact',
    isPastDue && 'is-overdue-card',
    onOpenDetail && 'is-clickable',
  ].filter(Boolean).join(' ')

  return (
    <article className={cardClasses} onClick={handleCardClick}>
      <div className="card-header">
        <div className="card-title-section">
          <h3 className="assignment-title">{assignment.title}</h3>
          <div className="card-meta">
            <span className="course-badge">{assignment.course_name}</span>
            <span className={`status-badge status-${assignment.status}`}>
              <span className="status-dot" />
              {STATUS_LABELS[assignment.status]}
            </span>
          </div>
        </div>
      </div>

      <div className="card-times">
        <p className={`due-date ${isPastDue ? 'is-overdue' : ''}`}>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
          {isPastDue && <span className="overdue-label">Overdue:</span>}
          <span>{formatDueDate(assignment.due_date)}</span>
        </p>

        {plannedTime && (
          <p className="planned-time">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
              <line x1="16" y1="2" x2="16" y2="6" />
              <line x1="8" y1="2" x2="8" y2="6" />
              <line x1="3" y1="10" x2="21" y2="10" />
            </svg>
            <span>Planned: {plannedTime}</span>
          </p>
        )}
      </div>

      {!compact && assignment.description && (
        <p className="assignment-description">{assignment.description}</p>
      )}

      <div className="card-footer">
        {/* Quick Actions */}
        <div className="quick-actions">
          {assignment.link && (
            <a
              href={assignment.link}
              target="_blank"
              rel="noopener noreferrer"
              className="quick-action-btn action-open"
              title="Open assignment"
              onClick={(e) => e.stopPropagation()}
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
              <span>Open</span>
            </a>
          )}

          {canMarkStarted && onMarkStarted && (
            <button
              className="quick-action-btn action-start"
              onClick={(e) => {
                e.stopPropagation()
                onMarkStarted(assignment.id)
              }}
              disabled={isUpdating}
              title="Mark as started"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
              <span>Start</span>
            </button>
          )}

          {canMarkDone && onMarkDone && (
            <button
              className="quick-action-btn action-done"
              onClick={(e) => {
                e.stopPropagation()
                onMarkDone(assignment.id)
              }}
              disabled={isUpdating}
              title="Mark as done"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              <span>Done</span>
            </button>
          )}
        </div>

        {/* Status Dropdown */}
        <div className="status-controls">
          <select
            className="status-select"
            value={assignment.status}
            onChange={handleStatusChange}
            disabled={isUpdating}
            aria-label="Change status"
            onClick={(e) => e.stopPropagation()}
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          {isUpdating && <span className="update-spinner" />}
        </div>
      </div>
    </article>
  )
}

export default AssignmentCard
