import { useState, useEffect } from 'react'
import { supabase } from '../lib/supabase'
import { authFetch, API_BASE } from '../lib/api'
import './Settings.css'

const STUDY_TIME_OPTIONS = [
  { value: 'morning',   label: 'Morning',   sub: 'Before noon' },
  { value: 'afternoon', label: 'Afternoon',  sub: 'Noon – 5 pm' },
  { value: 'evening',   label: 'Evening',    sub: '5 – 9 pm' },
  { value: 'night',     label: 'Late night', sub: '9 pm or later' },
]

const WORK_STYLE_OPTIONS = [
  { value: 'spread_out', label: 'Spread it out', sub: 'Multiple shorter sessions' },
  { value: 'batch',      label: 'Knock it out',  sub: 'One long sitting' },
]

const INVOLVEMENT_OPTIONS = [
  { value: 'proactive',   label: 'Proactive',   sub: 'Suggests plans automatically' },
  { value: 'balanced',    label: 'Balanced',     sub: 'Nudges near deadlines' },
  { value: 'prompt_only', label: 'On demand',    sub: 'Only when I ask' },
]

function Settings({ onLogout, preferences, onPreferencesChange, onClose }) {
  const [userEmail, setUserEmail] = useState(null)
  const [canvasConnected, setCanvasConnected] = useState(false)
  const [canvasUser, setCanvasUser] = useState(null)

  // Canvas reconnect state
  const [canvasToken, setCanvasToken] = useState('')
  const [canvasLoading, setCanvasLoading] = useState(false)
  const [canvasError, setCanvasError] = useState(null)

  // Preferences form state (initialized from props)
  const [studyTime, setStudyTime] = useState(preferences?.study_time || 'evening')
  const [sessionLength, setSessionLength] = useState(preferences?.session_length_minutes || 60)
  const [advanceDays, setAdvanceDays] = useState(preferences?.advance_days ?? 1)
  const [workStyle, setWorkStyle] = useState(preferences?.work_style || 'spread_out')
  const [involvementLevel, setInvolvementLevel] = useState(preferences?.involvement_level || 'balanced')
  const [prefSaving, setPrefSaving] = useState(false)
  const [prefSaved, setPrefSaved] = useState(false)
  const [prefError, setPrefError] = useState(null)

  // Weekly schedule state
  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  const [schedule, setSchedule] = useState(() => {
    return preferences?.weekly_schedule || []
  })
  const [newBlock, setNewBlock] = useState({ days: [], label: '', start: '08:00', end: '09:00' })
  const [showAddBlock, setShowAddBlock] = useState(false)

  // Load user info on mount
  useEffect(() => {
    supabase.auth.getUser().then(({ data: { user } }) => {
      if (user) setUserEmail(user.email)
    })

    authFetch(`${API_BASE}/auth/canvas-status`).then(async (res) => {
      if (!res.ok) return
      const data = await res.json()
      setCanvasConnected(!!data.connected)
      if (data.user_name) setCanvasUser(data.user_name)
    }).catch(() => {})
  }, [])

  // Sync prefs state when preferences prop changes
  useEffect(() => {
    if (!preferences) return
    if (preferences.study_time) setStudyTime(preferences.study_time)
    if (preferences.session_length_minutes) setSessionLength(preferences.session_length_minutes)
    if (preferences.advance_days !== undefined) setAdvanceDays(preferences.advance_days)
    if (preferences.work_style) setWorkStyle(preferences.work_style)
    if (preferences.involvement_level) setInvolvementLevel(preferences.involvement_level)
    if (preferences.weekly_schedule !== undefined) setSchedule(preferences.weekly_schedule || [])
  }, [preferences])

  const handleCanvasConnect = async () => {
    const token = canvasToken.trim()
    if (!token) return
    setCanvasLoading(true)
    setCanvasError(null)
    try {
      const res = await authFetch(`${API_BASE}/auth/canvas-token`, {
        method: 'POST',
        body: JSON.stringify({ token }),
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Failed to connect')
      }
      const data = await res.json()
      setCanvasConnected(true)
      setCanvasUser(data.user_name)
      setCanvasToken('')
    } catch (err) {
      setCanvasError(err.message || 'Failed to validate token')
    } finally {
      setCanvasLoading(false)
    }
  }

  const handleSavePrefs = async () => {
    setPrefSaving(true)
    setPrefError(null)
    setPrefSaved(false)
    try {
      const updates = {
        study_time: studyTime,
        session_length_minutes: Number(sessionLength),
        advance_days: Number(advanceDays),
        work_style: workStyle,
        involvement_level: involvementLevel,
        weekly_schedule: schedule,
      }
      const res = await authFetch(`${API_BASE}/preferences`, {
        method: 'POST',
        body: JSON.stringify(updates),
      })
      if (!res.ok) throw new Error('Failed to save')
      const updated = await res.json()
      onPreferencesChange?.(updated)
      setPrefSaved(true)
      setTimeout(() => setPrefSaved(false), 2500)
    } catch {
      setPrefError('Failed to save. Please try again.')
    } finally {
      setPrefSaving(false)
    }
  }

  // Close on escape key
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const handleBackdrop = (e) => {
    if (e.target === e.currentTarget) onClose?.()
  }

  return (
    <div className="settings-backdrop" onClick={handleBackdrop}>
      <div className="settings-panel" role="dialog" aria-label="Settings" aria-modal="true">
        {/* Header */}
        <div className="settings-header">
          <h2 className="settings-title">Settings</h2>
          <button className="settings-close" onClick={onClose} aria-label="Close settings">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="settings-body">

          {/* Account Section */}
          <section className="settings-section">
            <h3 className="settings-section-title">Account</h3>
            <div className="settings-row">
              <div className="settings-row-info">
                <span className="settings-row-label">Email</span>
                <span className="settings-row-value">{userEmail || '—'}</span>
              </div>
              <button className="settings-danger-btn" onClick={onLogout}>
                Sign Out
              </button>
            </div>
          </section>

          {/* Canvas Section */}
          <section className="settings-section">
            <h3 className="settings-section-title">Canvas LMS</h3>
            <div className="settings-row">
              <div className="settings-row-info">
                <span className="settings-row-label">Status</span>
                <span className={`settings-connection-badge ${canvasConnected ? 'is-connected' : 'is-disconnected'}`}>
                  {canvasConnected ? (canvasUser ? `Connected as ${canvasUser}` : 'Connected') : 'Not connected'}
                </span>
              </div>
            </div>
            <div className="settings-canvas-row">
              <input
                type="password"
                className="settings-token-input"
                placeholder="Paste new Canvas API token to reconnect"
                value={canvasToken}
                onChange={(e) => setCanvasToken(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCanvasConnect()}
                disabled={canvasLoading}
              />
              <button
                className="settings-action-btn"
                onClick={handleCanvasConnect}
                disabled={canvasLoading || !canvasToken.trim()}
              >
                {canvasLoading ? 'Checking...' : 'Connect'}
              </button>
            </div>
            {canvasError && <p className="settings-error">{canvasError}</p>}
            <p className="settings-hint">
              Generate a token in{' '}
              <a href="https://byu.instructure.com/profile/settings" target="_blank" rel="noopener noreferrer">
                Canvas Settings
              </a>
              {' '}under &quot;Approved Integrations.&quot;
            </p>
          </section>

          {/* Preferences Section */}
          <section className="settings-section">
            <h3 className="settings-section-title">Study Preferences</h3>

            <div className="settings-pref-group">
              <label className="settings-pref-label">Best study time</label>
              <div className="settings-radio-row">
                {STUDY_TIME_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    className={`settings-radio-btn ${studyTime === opt.value ? 'active' : ''}`}
                    onClick={() => setStudyTime(opt.value)}
                  >
                    <span className="settings-radio-main">{opt.label}</span>
                    <span className="settings-radio-sub">{opt.sub}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="settings-pref-group">
              <label className="settings-pref-label">Preferred session length (minutes)</label>
              <input
                type="number"
                className="settings-number-input"
                value={sessionLength}
                onChange={(e) => setSessionLength(e.target.value)}
                min={15}
                max={480}
                step={15}
              />
            </div>

            <div className="settings-pref-group">
              <label className="settings-pref-label">Days before due date to start</label>
              <input
                type="number"
                className="settings-number-input"
                value={advanceDays}
                onChange={(e) => setAdvanceDays(e.target.value)}
                min={0}
                max={30}
                step={1}
              />
            </div>

            <div className="settings-pref-group">
              <label className="settings-pref-label">Work style</label>
              <div className="settings-radio-row">
                {WORK_STYLE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    className={`settings-radio-btn ${workStyle === opt.value ? 'active' : ''}`}
                    onClick={() => setWorkStyle(opt.value)}
                  >
                    <span className="settings-radio-main">{opt.label}</span>
                    <span className="settings-radio-sub">{opt.sub}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="settings-pref-group">
              <label className="settings-pref-label">AI involvement</label>
              <div className="settings-radio-row">
                {INVOLVEMENT_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    className={`settings-radio-btn ${involvementLevel === opt.value ? 'active' : ''}`}
                    onClick={() => setInvolvementLevel(opt.value)}
                  >
                    <span className="settings-radio-main">{opt.label}</span>
                    <span className="settings-radio-sub">{opt.sub}</span>
                  </button>
                ))}
              </div>
            </div>

            {prefError && <p className="settings-error">{prefError}</p>}

            <div className="settings-save-row">
              {prefSaved && <span className="settings-saved-msg">Saved!</span>}
              <button
                className="settings-save-btn"
                onClick={handleSavePrefs}
                disabled={prefSaving}
              >
                {prefSaving ? 'Saving...' : 'Save Preferences'}
              </button>
            </div>
          </section>

          {/* Weekly Schedule Section */}
          <section className="settings-section">
            <h3 className="settings-section-title">Weekly Schedule</h3>
            <p className="settings-section-desc">Add your recurring class times and commitments so the AI schedules study time around them.</p>

            {schedule.length > 0 && (
              <div className="schedule-blocks">
                {schedule.map((block, i) => (
                  <div key={i} className="schedule-block">
                    <span className="schedule-block-days">{block.day}</span>
                    <span className="schedule-block-time">{block.start}–{block.end}</span>
                    {block.label && <span className="schedule-block-label">{block.label}</span>}
                    <button
                      className="schedule-block-remove"
                      onClick={() => setSchedule(s => s.filter((_, idx) => idx !== i))}
                      aria-label="Remove"
                    >×</button>
                  </div>
                ))}
              </div>
            )}

            {showAddBlock ? (
              <div className="schedule-add-form">
                <div className="schedule-days-row">
                  {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(d => (
                    <button
                      key={d}
                      type="button"
                      className={`schedule-day-btn ${newBlock.days.includes(d) ? 'active' : ''}`}
                      onClick={() => setNewBlock(b => ({
                        ...b,
                        days: b.days.includes(d) ? b.days.filter(x => x !== d) : [...b.days, d]
                      }))}
                    >{d}</button>
                  ))}
                </div>
                <input
                  type="text"
                  className="schedule-label-input"
                  placeholder="Label (e.g. STRAT 490R)"
                  value={newBlock.label}
                  onChange={(e) => setNewBlock(b => ({ ...b, label: e.target.value }))}
                />
                <div className="schedule-time-row">
                  <input type="time" className="schedule-time-input" value={newBlock.start}
                    onChange={(e) => setNewBlock(b => ({ ...b, start: e.target.value }))} />
                  <span>to</span>
                  <input type="time" className="schedule-time-input" value={newBlock.end}
                    onChange={(e) => setNewBlock(b => ({ ...b, end: e.target.value }))} />
                </div>
                <div className="schedule-add-actions">
                  <button type="button" className="settings-secondary-btn" onClick={() => { setShowAddBlock(false); setNewBlock({ days: [], label: '', start: '08:00', end: '09:00' }) }}>Cancel</button>
                  <button
                    type="button"
                    className="settings-primary-btn"
                    disabled={newBlock.days.length === 0}
                    onClick={() => {
                      const newEntries = newBlock.days.map(d => ({ day: d, label: newBlock.label, start: newBlock.start, end: newBlock.end }))
                      setSchedule(s => [...s, ...newEntries])
                      setShowAddBlock(false)
                      setNewBlock({ days: [], label: '', start: '08:00', end: '09:00' })
                    }}
                  >Add</button>
                </div>
              </div>
            ) : (
              <button className="settings-secondary-btn" onClick={() => setShowAddBlock(true)}>
                + Add time block
              </button>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

export default Settings
