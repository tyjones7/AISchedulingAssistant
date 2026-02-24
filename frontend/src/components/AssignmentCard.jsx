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
  suggestion = null,
}) {
  const tz = 'America/Denver'

  const getMtDateStr = (d) => {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit'
    }).formatToParts(d)
    return `${parts.find(p => p.type === 'year').value}-${parts.find(p => p.type === 'month').value}-${parts.find(p => p.type === 'day').value}`
  }

  // Time remaining calculation
  const getTimeRemaining = (dateString) => {
    const due = new Date(dateString)
    const now = new Date()
    const diff = due - now

    if (diff < 0) {
      // Overdue
      const absDiff = Math.abs(diff)
      const hours = Math.floor(absDiff / 3600000)
      const days = Math.floor(hours / 24)
      if (days > 0) return `${days}d overdue`
      if (hours > 0) return `${hours}h overdue`
      return 'Just passed'
    }

    const minutes = Math.floor(diff / 60000)
    const hours = Math.floor(diff / 3600000)
    const days = Math.floor(hours / 24)

    if (days > 7) return `${Math.floor(days / 7)}w ${days % 7}d left`
    if (days > 0) return `${days}d ${hours % 24}h left`
    if (hours > 0) return `${hours}h ${minutes % 60}m left`
    return `${minutes}m left`
  }

  // Urgency level for visual indicators
  const getUrgencyLevel = (dateString) => {
    const due = new Date(dateString)
    const now = new Date()
    const diff = due - now

    if (diff < 0) return 'overdue'

    const todayStr = getMtDateStr(now)
    const dueDateStr = getMtDateStr(due)

    if (dueDateStr === todayStr) return 'today'

    const tomorrowStr = getMtDateStr(new Date(now.getTime() + 86400000))
    if (dueDateStr === tomorrowStr) return 'tomorrow'

    const hours = diff / 3600000
    if (hours < 72) return 'soon'

    return 'later'
  }

  const formatDueTime = (dateString) => {
    const date = new Date(dateString)
    return date.toLocaleTimeString('en-US', {
      timeZone: tz,
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    })
  }

  const formatDueDate = (dateString) => {
    const date = new Date(dateString)
    const now = new Date()

    const dueDateStr = getMtDateStr(date)
    const todayStr = getMtDateStr(now)
    const tomorrowStr = getMtDateStr(new Date(now.getTime() + 86400000))

    const timeStr = formatDueTime(dateString)

    if (dueDateStr === todayStr) {
      return `Today at ${timeStr}`
    } else if (dueDateStr === tomorrowStr) {
      return `Tomorrow at ${timeStr}`
    }

    return date.toLocaleDateString('en-US', {
      timeZone: tz,
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    }) + ` at ${timeStr}`
  }

  const isPastDue = assignment.due_date && new Date(assignment.due_date) < new Date() && assignment.status !== 'submitted'
  const urgency = assignment.due_date ? getUrgencyLevel(assignment.due_date) : 'later'
  const timeRemaining = assignment.due_date ? getTimeRemaining(assignment.due_date) : null

  const handleStatusChange = (e) => {
    e.stopPropagation()
    const newStatus = e.target.value
    if (newStatus !== assignment.status) {
      onStatusChange(assignment.id, newStatus)
    }
  }

  const handleCardClick = (e) => {
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

  const handleCardKeyDown = (e) => {
    if ((e.key === 'Enter' || e.key === ' ') && onOpenDetail) {
      e.preventDefault()
      onOpenDetail(assignment)
    }
  }

  const canMarkStarted = ['newly_assigned', 'not_started'].includes(assignment.status)
  const canMarkDone = ['newly_assigned', 'not_started', 'in_progress'].includes(assignment.status)

  // AI suggested start pill
  const getSuggestedStartInfo = (s) => {
    if (!s?.suggested_start) return null
    const start = new Date(s.suggested_start + 'T00:00:00')
    const today = new Date(); today.setHours(0, 0, 0, 0)
    const diff = Math.round((start - today) / 86400000)
    if (diff < 0) return { label: 'Start now', urgency: 'high' }
    if (diff === 0) return { label: 'Start today', urgency: 'high' }
    if (diff === 1) return { label: 'Start tomorrow', urgency: 'medium' }
    return {
      label: `Start ${start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`,
      urgency: 'low',
    }
  }
  const startInfo = getSuggestedStartInfo(suggestion)

  const cardClasses = [
    'assignment-card',
    isUpdating && 'is-updating',
    compact && 'is-compact',
    onOpenDetail && 'is-clickable',
    `urgency-${urgency}`,
  ].filter(Boolean).join(' ')

  return (
    <article
      className={cardClasses}
      onClick={handleCardClick}
      onKeyDown={onOpenDetail ? handleCardKeyDown : undefined}
      tabIndex={onOpenDetail ? 0 : undefined}
      role={onOpenDetail ? 'button' : undefined}
      aria-label={onOpenDetail ? `View details for ${assignment.title}` : undefined}
    >
      {/* Top row: title + time remaining */}
      <div className="card-top">
        <h3 className="card-title">{assignment.title}</h3>
        {timeRemaining && (
          <span className={`time-remaining time-${urgency}`}>
            {timeRemaining}
          </span>
        )}
      </div>

      {/* Meta row: course + status + estimated time */}
      <div className="card-meta">
        <span className="card-course">{assignment.course_name}</span>
        {assignment.source && (
          <span className={`source-badge source-${assignment.source === 'canvas' ? 'canvas' : 'ls'}`}>
            {assignment.source === 'canvas' ? 'Canvas' : 'LS'}
          </span>
        )}
        <span className={`card-status status-${assignment.status}`}>
          {STATUS_LABELS[assignment.status]}
        </span>
        {assignment.estimated_minutes && (
          <span className="card-estimate">
            ~{assignment.estimated_minutes >= 60
              ? `${Math.floor(assignment.estimated_minutes / 60)}h ${assignment.estimated_minutes % 60 > 0 ? (assignment.estimated_minutes % 60) + 'm' : ''}`
              : `${assignment.estimated_minutes}m`
            }
          </span>
        )}
        {!assignment.estimated_minutes && suggestion?.estimated_minutes && (
          <span className="card-estimate card-estimate-ai" title="AI time estimate">
            ~{suggestion.estimated_minutes >= 60
              ? `${Math.floor(suggestion.estimated_minutes / 60)}h ${suggestion.estimated_minutes % 60 > 0 ? (suggestion.estimated_minutes % 60) + 'm' : ''}`
              : `${suggestion.estimated_minutes}m`
            } AI
          </span>
        )}
        {startInfo && (
          <span
            className={`ai-start-pill ai-start-${startInfo.urgency}`}
            title={suggestion.rationale || `AI suggestion: ${startInfo.label}`}
          >
            {startInfo.label}
          </span>
        )}
      </div>

      {/* Due date (non-compact only) */}
      {!compact && (
        <div className="card-due">
          {assignment.due_date ? (
            <span className={`due-text ${isPastDue ? 'is-overdue' : ''}`}>
              {formatDueDate(assignment.due_date)}
            </span>
          ) : (
            <span className="due-text no-date">No due date</span>
          )}
        </div>
      )}

      {/* Description (non-compact only) */}
      {!compact && assignment.description && (
        <p className="card-description">{assignment.description}</p>
      )}

      {/* Actions */}
      <div className="card-actions">
        <div className="action-buttons">
          {assignment.link && (
            <a
              href={assignment.link}
              target="_blank"
              rel="noopener noreferrer"
              className="quick-action-btn action-open"
              title={assignment.source === 'canvas' ? 'Open in Canvas' : 'Open in Learning Suite'}
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
