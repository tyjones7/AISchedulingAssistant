import { useState, useEffect } from 'react'
import { authFetch, API_BASE } from '../lib/api'
import './TodayView.css'

const COURSE_COLORS = [
  '#6366f1', '#0ea5e9', '#10b981', '#f59e0b',
  '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6',
]

function getCourseColor(name) {
  if (!name) return COURSE_COLORS[0]
  const h = [...name].reduce((a, c) => a + c.charCodeAt(0), 0)
  return COURSE_COLORS[h % COURSE_COLORS.length]
}

function getMtDateStr(d) {
  const p = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Denver', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(d)
  return `${p.find(x => x.type === 'year').value}-${p.find(x => x.type === 'month').value}-${p.find(x => x.type === 'day').value}`
}

function formatTime(isoStr) {
  return new Date(isoStr).toLocaleString('en-US', {
    timeZone: 'America/Denver', hour: 'numeric', minute: '2-digit', hour12: true,
  })
}

export default function TodayView({ assignments = [], addToast }) {
  const [blocks, setBlocks] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchToday()
  }, [])

  const fetchToday = async () => {
    try {
      const res = await authFetch(`${API_BASE}/schedule/week`)
      if (res.ok) {
        const data = await res.json()
        const todayStr = getMtDateStr(new Date())
        const todayBlocks = (data.blocks || [])
          .filter(b => b.date === todayStr)
          .sort((a, b) => new Date(a.start_time) - new Date(b.start_time))
        setBlocks(todayBlocks)
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const updateStatus = async (blockId, status) => {
    try {
      const res = await authFetch(`${API_BASE}/time-blocks/${blockId}`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      })
      if (res.ok) {
        setBlocks(prev => prev.map(b => b.id === blockId ? { ...b, status } : b))
        addToast(status === 'completed' ? 'Block completed!' : 'Block skipped', 'success')
      }
    } catch {
      addToast('Failed to update block', 'error')
    }
  }

  const overdueAssignments = assignments.filter(a => {
    if (['submitted', 'unavailable'].includes(a.status)) return false
    if (!a.due_date) return false
    return new Date(a.due_date) < new Date()
  })

  const todayLabel = new Date().toLocaleDateString('en-US', {
    timeZone: 'America/Denver', weekday: 'long', month: 'long', day: 'numeric',
  })

  const remaining = blocks.filter(b => !['completed', 'skipped'].includes(b.status)).length

  return (
    <div className="today-view">
      <div className="today-header">
        <div>
          <h2 className="today-title">{todayLabel}</h2>
          <p className="today-subtitle">
            {loading ? 'Loading…' : `${remaining} block${remaining !== 1 ? 's' : ''} remaining today`}
          </p>
        </div>
      </div>

      {/* Overdue */}
      {overdueAssignments.length > 0 && (
        <section className="today-section">
          <h3 className="today-section-label today-section-label--overdue">
            <span className="today-dot" />
            Overdue ({overdueAssignments.length})
          </h3>
          <div className="today-overdue-list">
            {overdueAssignments.map(a => (
              <div key={a.id} className="today-overdue-item">
                <span className="today-overdue-name">{a.title}</span>
                <span className="today-overdue-course">{a.course_name}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Today's blocks */}
      <section className="today-section">
        <h3 className="today-section-label">Study Blocks</h3>
        {loading ? (
          <div className="today-loading">Loading…</div>
        ) : blocks.length === 0 ? (
          <div className="today-empty">
            <p>No study blocks scheduled for today.</p>
            <p className="today-empty-hint">Switch to the Weekly view to generate a plan.</p>
          </div>
        ) : (
          <div className="today-block-list">
            {blocks.map(block => {
              const asgn = block.assignments || {}
              const color = getCourseColor(asgn.course_name)
              const isDone = block.status === 'completed'
              const isSkipped = block.status === 'skipped'
              const durMin = Math.round((new Date(block.end_time) - new Date(block.start_time)) / 60000)

              return (
                <div
                  key={block.id}
                  className={`today-block ${isDone ? 'is-done' : ''} ${isSkipped ? 'is-skipped' : ''}`}
                >
                  <div className="today-block-accent" style={{ background: color }} />
                  <div className="today-block-body">
                    <div className="today-block-time">
                      {formatTime(block.start_time)} – {formatTime(block.end_time)}
                      <span className="today-block-dur">{durMin} min</span>
                    </div>
                    <div className="today-block-title">{asgn.title || 'Study block'}</div>
                    <div className="today-block-course">{asgn.course_name}</div>
                  </div>

                  {!isDone && !isSkipped ? (
                    <div className="today-block-actions">
                      <button
                        className="today-action today-action--done"
                        onClick={() => updateStatus(block.id, 'completed')}
                        title="Mark done"
                      >✓</button>
                      <button
                        className="today-action today-action--skip"
                        onClick={() => updateStatus(block.id, 'skipped')}
                        title="Skip"
                      >→</button>
                    </div>
                  ) : (
                    <span className={`today-badge ${isDone ? 'today-badge--done' : 'today-badge--skip'}`}>
                      {isDone ? 'Done' : 'Skipped'}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}
