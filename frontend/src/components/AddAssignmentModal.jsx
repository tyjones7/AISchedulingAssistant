import { useState, useEffect, useId } from 'react'
import { authFetch, API_BASE } from '../lib/api'
import './AddAssignmentModal.css'

const ASSIGNMENT_TYPES = [
  'Essay/Paper',
  'Quiz',
  'Exam',
  'Project',
  'Homework',
  'Discussion',
  'Reading',
  'Other',
]

function getDefaultDueDate() {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  d.setHours(23, 59, 0, 0)
  // Format for datetime-local input: YYYY-MM-DDTHH:MM
  const offset = d.getTimezoneOffset()
  const local = new Date(d.getTime() - offset * 60 * 1000)
  return local.toISOString().slice(0, 16)
}

function AddAssignmentModal({ onClose, onAdded, existingCourses = [] }) {
  const listId = useId()

  const [title, setTitle] = useState('')
  const [course, setCourse] = useState('')
  const [dueDate, setDueDate] = useState(getDefaultDueDate)
  const [pointValue, setPointValue] = useState('')
  const [assignmentType, setAssignmentType] = useState('')
  const [notes, setNotes] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const handleBackdrop = (e) => {
    if (e.target === e.currentTarget) onClose()
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!title.trim()) { setError('Title is required.'); return }
    if (!course.trim()) { setError('Course name is required.'); return }
    if (!dueDate) { setError('Due date is required.'); return }

    setError(null)
    setSubmitting(true)

    try {
      const payload = {
        title: title.trim(),
        course_name: course.trim(),
        due_date: new Date(dueDate).toISOString(),
      }
      if (pointValue !== '') payload.point_value = parseFloat(pointValue)
      if (assignmentType)    payload.assignment_type = assignmentType
      if (notes.trim())      payload.notes = notes.trim()

      const res = await authFetch(`${API_BASE}/assignments`, {
        method: 'POST',
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || 'Failed to create assignment.')
      }

      onAdded()
      onClose()
    } catch (err) {
      setError(err.message || 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="add-modal-backdrop" onClick={handleBackdrop}>
      <div className="add-modal-container" role="dialog" aria-modal="true" aria-label="Add Assignment">

        {/* Header */}
        <div className="add-modal-header">
          <h2 className="add-modal-title">Add Assignment</h2>
          <button className="add-modal-close" onClick={onClose} aria-label="Close">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Form */}
        <form className="add-modal-form" onSubmit={handleSubmit} noValidate>
          <div className="add-modal-body">

            {/* Title */}
            <div className="add-field">
              <label className="add-label" htmlFor="add-title">
                Title <span className="add-required">*</span>
              </label>
              <input
                id="add-title"
                type="text"
                className="add-input"
                placeholder="e.g. Chapter 5 Reading Quiz"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                autoFocus
                required
              />
            </div>

            {/* Course */}
            <div className="add-field">
              <label className="add-label" htmlFor="add-course">
                Course <span className="add-required">*</span>
              </label>
              <input
                id="add-course"
                type="text"
                className="add-input"
                placeholder="e.g. STRAT 490R"
                value={course}
                onChange={(e) => setCourse(e.target.value)}
                list={listId}
                required
              />
              <datalist id={listId}>
                {existingCourses.map((c) => (
                  <option key={c} value={c} />
                ))}
              </datalist>
            </div>

            {/* Two-column: Due Date + Point Value */}
            <div className="add-row">
              <div className="add-field">
                <label className="add-label" htmlFor="add-due">
                  Due Date <span className="add-required">*</span>
                </label>
                <input
                  id="add-due"
                  type="datetime-local"
                  className="add-input"
                  value={dueDate}
                  onChange={(e) => setDueDate(e.target.value)}
                  required
                />
              </div>

              <div className="add-field">
                <label className="add-label" htmlFor="add-points">
                  Point Value <span className="add-optional">(optional)</span>
                </label>
                <input
                  id="add-points"
                  type="number"
                  className="add-input"
                  placeholder="e.g. 100"
                  value={pointValue}
                  onChange={(e) => setPointValue(e.target.value)}
                  min={0}
                  step="any"
                />
              </div>
            </div>

            {/* Assignment Type */}
            <div className="add-field">
              <label className="add-label" htmlFor="add-type">
                Type <span className="add-optional">(optional)</span>
              </label>
              <div className="add-select-wrapper">
                <select
                  id="add-type"
                  className="add-select"
                  value={assignmentType}
                  onChange={(e) => setAssignmentType(e.target.value)}
                >
                  <option value="">Select a type...</option>
                  {ASSIGNMENT_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
                <svg className="add-select-chevron" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </div>
            </div>

            {/* Notes */}
            <div className="add-field">
              <label className="add-label" htmlFor="add-notes">
                Notes <span className="add-optional">(optional)</span>
              </label>
              <textarea
                id="add-notes"
                className="add-textarea"
                placeholder="Any details about this assignment..."
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
              />
            </div>

          </div>

          {/* Footer */}
          <div className="add-modal-footer">
            {error && <span className="add-error-msg">{error}</span>}
            <button
              type="button"
              className="add-btn add-btn--ghost"
              onClick={onClose}
              disabled={submitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="add-btn add-btn--primary"
              disabled={submitting}
            >
              {submitting ? 'Adding...' : 'Add Assignment'}
            </button>
          </div>
        </form>

      </div>
    </div>
  )
}

export default AddAssignmentModal
