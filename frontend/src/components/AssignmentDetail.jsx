import { useState, useEffect } from 'react'
import { API_BASE } from '../config/api'
import { downloadICS, getGoogleCalendarUrl } from '../utils/calendar'
import './AssignmentDetail.css'

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

const TIME_ESTIMATES = [
  { value: 15, label: '15 min' },
  { value: 30, label: '30 min' },
  { value: 45, label: '45 min' },
  { value: 60, label: '1 hour' },
  { value: 90, label: '1.5 hours' },
  { value: 120, label: '2 hours' },
  { value: 180, label: '3 hours' },
  { value: 240, label: '4+ hours' },
]

function AssignmentDetail({ assignment, onClose, onUpdate }) {
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)

  // Form state
  const [status, setStatus] = useState(assignment?.status || 'not_started')
  const [estimatedMinutes, setEstimatedMinutes] = useState(assignment?.estimated_minutes || '')
  const [plannedStart, setPlannedStart] = useState('')
  const [plannedEnd, setPlannedEnd] = useState('')
  const [notes, setNotes] = useState(assignment?.notes || '')

  // Initialize dates
  useEffect(() => {
    if (assignment?.planned_start) {
      const date = new Date(assignment.planned_start)
      setPlannedStart(formatDateTimeLocal(date))
    }
    if (assignment?.planned_end) {
      const date = new Date(assignment.planned_end)
      setPlannedEnd(formatDateTimeLocal(date))
    }
  }, [assignment])

  const formatDateTimeLocal = (date) => {
    const offset = date.getTimezoneOffset()
    const localDate = new Date(date.getTime() - offset * 60 * 1000)
    return localDate.toISOString().slice(0, 16)
  }

  const formatDueDate = (dateString) => {
    const date = new Date(dateString)
    return date.toLocaleDateString('en-US', {
      timeZone: 'America/Denver',
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    })
  }

  const isPastDue = assignment.due_date && new Date(assignment.due_date) < new Date() && assignment.status !== 'submitted'

  const handleSave = async () => {
    setSaveError(null)
    setSaving(true)

    try {
      const updateData = {
        status,
        estimated_minutes: estimatedMinutes ? parseInt(estimatedMinutes) : null,
        planned_start: plannedStart ? new Date(plannedStart).toISOString() : '',
        planned_end: plannedEnd ? new Date(plannedEnd).toISOString() : '',
        notes: notes || '',
      }

      const response = await fetch(
        `${API_BASE}/assignments/${assignment.id}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updateData),
        }
      )

      if (!response.ok) throw new Error('Failed to save')

      const data = await response.json()
      onUpdate(data.assignment)
      onClose()
    } catch (err) {
      console.error('Failed to save assignment:', err)
      setSaveError('Failed to save. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose()
    }
  }

  // Handle escape key
  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [onClose])

  if (!assignment) return null

  return (
    <div className="modal-backdrop" onClick={handleBackdropClick}>
      <div className="modal-container" role="dialog" aria-modal="true">
        {/* Header */}
        <div className="modal-header">
          <div className="modal-title-section">
            <span className="course-badge-lg">{assignment.course_name}</span>
            <h2 className="modal-title">{assignment.title}</h2>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="modal-content">
          {/* Assignment Info */}
          <section className="detail-section">
            <h3 className="section-title">Assignment Details</h3>

            <div className="detail-grid">
              <div className="detail-item">
                <label className="detail-label">Due Date</label>
                {assignment.due_date ? (
                  <p className={`detail-value ${isPastDue ? 'is-overdue' : ''}`}>
                    {formatDueDate(assignment.due_date)}
                    {isPastDue && <span className="overdue-tag">Overdue</span>}
                  </p>
                ) : (
                  <p className="detail-value no-date">No due date</p>
                )}
              </div>

              <div className="detail-item">
                <label className="detail-label">Status</label>
                <select
                  className="status-select-lg"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  {STATUS_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              {assignment.assignment_type && (
                <div className="detail-item">
                  <label className="detail-label">Type</label>
                  <p className="detail-value">{assignment.assignment_type}</p>
                </div>
              )}

              {assignment.link && (
                <div className="detail-item detail-item-full">
                  <label className="detail-label">Assignment Link</label>
                  <a
                    href={assignment.link}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="open-link-btn"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                      <polyline points="15 3 21 3 21 9" />
                      <line x1="10" y1="14" x2="21" y2="3" />
                    </svg>
                    Open in Learning Suite
                  </a>
                </div>
              )}
            </div>

            <div className="description-block">
              <label className="detail-label">Description</label>
              {assignment.description ? (
                <p className="description-text">{assignment.description}</p>
              ) : (
                <p className="description-text no-description">No description available</p>
              )}
            </div>
          </section>

          {/* Plan Work Section */}
          <section className="detail-section plan-section">
            <h3 className="section-title">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                <line x1="16" y1="2" x2="16" y2="6" />
                <line x1="8" y1="2" x2="8" y2="6" />
                <line x1="3" y1="10" x2="21" y2="10" />
              </svg>
              Plan Your Work
            </h3>

            <div className="plan-grid">
              <div className="plan-item">
                <label className="detail-label">Estimated Time</label>
                <select
                  className="plan-select"
                  value={estimatedMinutes}
                  onChange={(e) => setEstimatedMinutes(e.target.value)}
                >
                  <option value="">Select estimate...</option>
                  {TIME_ESTIMATES.map((est) => (
                    <option key={est.value} value={est.value}>
                      {est.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="plan-item">
                <label className="detail-label">Planned Start</label>
                <input
                  type="datetime-local"
                  className="plan-input"
                  value={plannedStart}
                  onChange={(e) => setPlannedStart(e.target.value)}
                />
              </div>

              <div className="plan-item">
                <label className="detail-label">Planned End</label>
                <input
                  type="datetime-local"
                  className="plan-input"
                  value={plannedEnd}
                  onChange={(e) => setPlannedEnd(e.target.value)}
                />
              </div>
            </div>

            <div className="notes-block">
              <label className="detail-label">Notes</label>
              <textarea
                className="notes-textarea"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Add notes about this assignment..."
                rows={3}
              />
            </div>
          </section>

          {/* Add to Calendar Section */}
          <section className="detail-section calendar-section">
            <h3 className="section-title">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 13V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8" />
                <line x1="16" y1="2" x2="16" y2="6" />
                <line x1="8" y1="2" x2="8" y2="6" />
                <line x1="3" y1="10" x2="21" y2="10" />
                <path d="M16 19l2 2 4-4" />
              </svg>
              Add to Calendar
            </h3>
            <div className="calendar-buttons">
              <a
                href={getGoogleCalendarUrl({
                  ...assignment,
                  planned_start: plannedStart ? new Date(plannedStart).toISOString() : '',
                  planned_end: plannedEnd ? new Date(plannedEnd).toISOString() : '',
                  estimated_minutes: estimatedMinutes ? parseInt(estimatedMinutes) : null,
                })}
                target="_blank"
                rel="noopener noreferrer"
                className="calendar-btn"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                  <polyline points="15 3 21 3 21 9" />
                  <line x1="10" y1="14" x2="21" y2="3" />
                </svg>
                Google Calendar
              </a>
              <button
                type="button"
                className="calendar-btn"
                onClick={() => downloadICS({
                  ...assignment,
                  planned_start: plannedStart ? new Date(plannedStart).toISOString() : '',
                  planned_end: plannedEnd ? new Date(plannedEnd).toISOString() : '',
                  estimated_minutes: estimatedMinutes ? parseInt(estimatedMinutes) : null,
                })}
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                Apple / Outlook (.ics)
              </button>
            </div>
            <p className="calendar-hint">
              {plannedStart && plannedEnd
                ? 'Exports your planned study block as a calendar event.'
                : 'Exports a reminder before the due date (set planned times above for a study block instead).'}
            </p>
          </section>
        </div>

        {/* Footer */}
        <div className="modal-footer">
          {saveError && (
            <span className="modal-save-error">{saveError}</span>
          )}
          <button className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default AssignmentDetail
