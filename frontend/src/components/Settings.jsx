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
  const [lsConnected, setLsConnected] = useState(false)
  const [canvasConnected, setCanvasConnected] = useState(false)
  const [canvasUser, setCanvasUser] = useState(null)

  // BYU reconnect state
  const [lsReconnecting, setLsReconnecting] = useState(false)
  const [lsStatus, setLsStatus] = useState(null)
  const [lsTaskId, setLsTaskId] = useState(null)
  const [lsError, setLsError] = useState(null)

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

  // Load user info on mount
  useEffect(() => {
    supabase.auth.getUser().then(({ data: { user } }) => {
      if (user) setUserEmail(user.email)
    })

    authFetch(`${API_BASE}/auth/status`).then(async (res) => {
      if (!res.ok) return
      const data = await res.json()
      setLsConnected(!!data.authenticated)
      setCanvasConnected(!!data.canvas_connected)
    }).catch(() => {})

    authFetch(`${API_BASE}/auth/canvas-status`).then(async (res) => {
      if (!res.ok) return
      const data = await res.json()
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
  }, [preferences])

  // Poll for BYU login completion
  useEffect(() => {
    if (!lsTaskId || !lsReconnecting) return
    const poll = async () => {
      try {
        const res = await authFetch(`${API_BASE}/auth/browser-status/${lsTaskId}`)
        if (!res.ok) return
        const data = await res.json()
        setLsStatus(data.status)
        if (data.status === 'authenticated') {
          setLsTaskId(null)
          setLsConnected(true)
          setTimeout(() => setLsReconnecting(false), 800)
        } else if (data.status === 'failed') {
          setLsReconnecting(false)
          setLsTaskId(null)
          setLsError(data.error || 'Login failed. Please try again.')
        }
      } catch { /* ignore */ }
    }
    const interval = setInterval(poll, 2000)
    poll()
    return () => clearInterval(interval)
  }, [lsTaskId, lsReconnecting])

  const handleLsReconnect = async () => {
    setLsReconnecting(true)
    setLsError(null)
    setLsStatus('opening')
    try {
      const res = await authFetch(`${API_BASE}/auth/browser-login`, { method: 'POST' })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Failed to open login')
      }
      const data = await res.json()
      setLsTaskId(data.task_id)
      setLsStatus('waiting_for_login')
    } catch (err) {
      setLsError(err.message || 'Failed to connect')
      setLsReconnecting(false)
    }
  }

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

  const getLsStatusMessage = () => {
    switch (lsStatus) {
      case 'opening': return 'Opening browser...'
      case 'waiting_for_login': return 'Complete login in the browser window...'
      case 'waiting_for_mfa': return 'Complete Duo MFA...'
      case 'authenticated': return 'Connected!'
      default: return 'Connecting...'
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

          {/* Learning Suite Section */}
          <section className="settings-section">
            <h3 className="settings-section-title">BYU Learning Suite</h3>
            <div className="settings-row">
              <div className="settings-row-info">
                <span className="settings-row-label">Status</span>
                <span className={`settings-connection-badge ${lsConnected ? 'is-connected' : 'is-disconnected'}`}>
                  {lsConnected ? 'Connected' : 'Not connected'}
                </span>
              </div>
              {!lsReconnecting ? (
                <button className="settings-action-btn" onClick={handleLsReconnect}>
                  {lsConnected ? 'Reconnect' : 'Connect'}
                </button>
              ) : (
                <span className="settings-status-text">
                  <span className="settings-spinner" />
                  {getLsStatusMessage()}
                </span>
              )}
            </div>
            {lsError && <p className="settings-error">{lsError}</p>}
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
        </div>
      </div>
    </div>
  )
}

export default Settings
