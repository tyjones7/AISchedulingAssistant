import { useState, useEffect } from 'react'
import { supabase } from '../lib/supabase'
import { authFetch, API_BASE } from '../lib/api'
import { registerPushNotifications, unregisterPushNotifications, isPushSupported, getPushPermission } from '../utils/pushNotifications'
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

  // iCal feeds
  const [icalFeeds, setIcalFeeds] = useState([])
  const [icalUrl, setIcalUrl] = useState('')
  const [icalCourse, setIcalCourse] = useState('')
  const [icalAdding, setIcalAdding] = useState(false)
  const [icalError, setIcalError] = useState(null)
  const [icalPreviewing, setIcalPreviewing] = useState(false)
  const [icalPreview, setIcalPreview] = useState(null)
  const [icalSyncing, setIcalSyncing] = useState(false)
  const [icalSyncResult, setIcalSyncResult] = useState(null)
  const [showIcalAdd, setShowIcalAdd] = useState(false)

  // Classification review modal
  const [reviewFeedId, setReviewFeedId] = useState(null)
  const [reviewCourseName, setReviewCourseName] = useState('')
  const [reviewItems, setReviewItems] = useState([])   // [{id, title, content_type, due_date}]
  const [reviewLoading, setReviewLoading] = useState(false)
  const [reviewSaving, setReviewSaving] = useState(false)
  const [feedPendingCounts, setFeedPendingCounts] = useState({})  // {feed_id: count}

  // iCal inline edit
  const [editingFeedId, setEditingFeedId] = useState(null)
  const [editCourse, setEditCourse] = useState('')
  const [editUrl, setEditUrl] = useState('')
  const [editSaving, setEditSaving] = useState(false)
  const [editError, setEditError] = useState(null)

  // Student context
  const [studentContext, setStudentContext] = useState(preferences?.student_context || '')
  const [contextSaving, setContextSaving] = useState(false)
  const [contextSaved, setContextSaved] = useState(false)

  // Push notifications
  const [pushSupported] = useState(() => isPushSupported())
  const [pushPermission, setPushPermission] = useState(() => getPushPermission())
  const [pushLoading, setPushLoading] = useState(false)
  const [pushError, setPushError] = useState(null)

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
    if (preferences.student_context !== undefined) setStudentContext(preferences.student_context || '')
  }, [preferences])

  // Load iCal feeds on mount, then fetch pending review counts for each
  useEffect(() => {
    authFetch(`${API_BASE}/ls-feeds`).then(async (res) => {
      if (!res.ok) return
      const data = await res.json()
      const feeds = data.feeds || []
      setIcalFeeds(feeds)
      // Load pending counts in parallel
      const countEntries = await Promise.all(
        feeds.map(async (feed) => {
          try {
            const r = await authFetch(`${API_BASE}/ls-feeds/${feed.id}/pending-review`)
            if (!r.ok) return null
            const d = await r.json()
            return d.items?.length > 0 ? [feed.id, d.items.length] : null
          } catch { return null }
        })
      )
      const pending = Object.fromEntries(countEntries.filter(Boolean))
      if (Object.keys(pending).length > 0) setFeedPendingCounts(pending)
    }).catch(() => {})
  }, [])

  const handleIcalPreview = async () => {
    const url = icalUrl.trim()
    const course = icalCourse.trim()
    if (!url || !course) return
    setIcalPreviewing(true)
    setIcalError(null)
    setIcalPreview(null)
    try {
      const res = await authFetch(`${API_BASE}/ls-feeds/preview`, {
        method: 'POST',
        body: JSON.stringify({ url, course_name: course }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Preview failed')
      setIcalPreview(data)
    } catch (err) {
      setIcalError(err.message || 'Could not preview feed')
    } finally {
      setIcalPreviewing(false)
    }
  }

  const handleIcalSave = async () => {
    const url = icalUrl.trim()
    const course = icalCourse.trim()
    if (!url || !course) return
    setIcalAdding(true)
    setIcalError(null)
    try {
      const res = await authFetch(`${API_BASE}/ls-feeds`, {
        method: 'POST',
        body: JSON.stringify({ url, course_name: course }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Save failed')
      setIcalFeeds(prev => [...prev, data.feed])
      setIcalUrl('')
      setIcalCourse('')
      setIcalPreview(null)
      setShowIcalAdd(false)
    } catch (err) {
      setIcalError(err.message || 'Could not save feed')
    } finally {
      setIcalAdding(false)
    }
  }

  const handleIcalDelete = async (feedId) => {
    try {
      await authFetch(`${API_BASE}/ls-feeds/${feedId}`, { method: 'DELETE' })
      setIcalFeeds(prev => prev.filter(f => f.id !== feedId))
    } catch {
      // ignore
    }
  }

  const handleIcalSync = async () => {
    setIcalSyncing(true)
    setIcalSyncResult(null)
    try {
      const res = await authFetch(`${API_BASE}/ls-feeds/sync`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Sync failed')
      const added = data.results.reduce((s, r) => s + (r.new || 0), 0)
      const updated = data.results.reduce((s, r) => s + (r.modified || 0), 0)
      setIcalSyncResult(`Synced ${data.synced} course(s): ${added} new, ${updated} updated`)
      setTimeout(() => setIcalSyncResult(null), 4000)
      // Track pending review counts per feed
      const pending = {}
      for (const r of (data.results || [])) {
        if (r.feed_id && r.pending_review > 0) pending[r.feed_id] = r.pending_review
      }
      setFeedPendingCounts(prev => ({ ...prev, ...pending }))
    } catch (err) {
      setIcalError(err.message || 'Sync failed')
    } finally {
      setIcalSyncing(false)
    }
  }

  const openReview = async (feedId, courseName) => {
    setReviewFeedId(feedId)
    setReviewCourseName(courseName)
    setReviewLoading(true)
    try {
      const res = await authFetch(`${API_BASE}/ls-feeds/${feedId}/pending-review`)
      if (res.ok) {
        const data = await res.json()
        setReviewItems(data.items || [])
      }
    } catch { /**/ } finally {
      setReviewLoading(false)
    }
  }

  const toggleReviewItem = (id) => {
    setReviewItems(prev => prev.map(it =>
      it.id === id
        ? { ...it, content_type: it.content_type === 'graded' ? 'course_content' : 'graded' }
        : it
    ))
  }

  const handleConfirmReview = async () => {
    setReviewSaving(true)
    try {
      const res = await authFetch(`${API_BASE}/ls-feeds/${reviewFeedId}/confirm-classifications`, {
        method: 'POST',
        body: JSON.stringify({ items: reviewItems.map(it => ({ id: it.id, content_type: it.content_type })) }),
      })
      if (res.ok) {
        setFeedPendingCounts(prev => { const n = { ...prev }; delete n[reviewFeedId]; return n })
        setReviewFeedId(null)
        setReviewItems([])
      }
    } catch { /**/ } finally {
      setReviewSaving(false)
    }
  }

  const handleIcalEditStart = (feed) => {
    setEditingFeedId(feed.id)
    setEditCourse(feed.course_name || '')
    setEditUrl(feed.url || '')
    setEditError(null)
  }

  const handleIcalEditCancel = () => {
    setEditingFeedId(null)
    setEditCourse('')
    setEditUrl('')
    setEditError(null)
  }

  const handleIcalEditSave = async (feedId) => {
    setEditSaving(true)
    setEditError(null)
    try {
      const res = await authFetch(`${API_BASE}/ls-feeds/${feedId}`, {
        method: 'PATCH',
        body: JSON.stringify({ url: editUrl.trim(), course_name: editCourse.trim() }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Save failed')
      setIcalFeeds(prev => prev.map(f => f.id === feedId ? data.feed : f))
      setEditingFeedId(null)
      setEditCourse('')
      setEditUrl('')
    } catch (err) {
      setEditError(err.message || 'Could not save changes')
    } finally {
      setEditSaving(false)
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

  const handleSaveContext = async () => {
    setContextSaving(true)
    setContextSaved(false)
    try {
      const res = await authFetch(`${API_BASE}/ai/update-context`, {
        method: 'POST',
        body: JSON.stringify({ context: studentContext }),
      })
      if (res.ok) {
        setContextSaved(true)
        setTimeout(() => setContextSaved(false), 2500)
      }
    } catch { /* ignore */ } finally {
      setContextSaving(false)
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

  const handlePushToggle = async () => {
    setPushLoading(true)
    setPushError(null)
    try {
      if (pushPermission === 'granted') {
        await unregisterPushNotifications()
        setPushPermission('default')
      } else {
        const ok = await registerPushNotifications()
        setPushPermission(ok ? 'granted' : getPushPermission())
        if (!ok && getPushPermission() === 'denied') {
          setPushError('Notifications blocked. Enable them in your browser settings.')
        }
      }
    } catch {
      setPushError('Something went wrong. Please try again.')
    } finally {
      setPushLoading(false)
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

          {/* Learning Suite iCal Section */}
          <section className="settings-section">
            <h3 className="settings-section-title">Learning Suite (iCal)</h3>
            <p className="settings-section-desc">
              Add per-course iCal feed URLs from Learning Suite to sync assignments without logging in.
            </p>

            {icalFeeds.length > 0 && (
              <div className="ical-feeds-list">
                {icalFeeds.map(feed => (
                  <div key={feed.id} className="ical-feed-row">
                    {editingFeedId === feed.id ? (
                      <div className="ical-edit-form">
                        <input
                          type="text"
                          className="settings-token-input"
                          placeholder="Course name"
                          value={editCourse}
                          onChange={(e) => setEditCourse(e.target.value)}
                          autoFocus
                        />
                        <input
                          type="url"
                          className="settings-token-input"
                          placeholder="iCal feed URL"
                          value={editUrl}
                          onChange={(e) => setEditUrl(e.target.value)}
                        />
                        {editError && <p className="settings-error">{editError}</p>}
                        <div className="schedule-add-actions">
                          <button className="settings-secondary-btn" onClick={handleIcalEditCancel}>Cancel</button>
                          <button
                            className="settings-primary-btn"
                            onClick={() => handleIcalEditSave(feed.id)}
                            disabled={editSaving || !editCourse.trim() || !editUrl.trim()}
                          >{editSaving ? 'Saving...' : 'Save'}</button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="ical-feed-info">
                          <span className="ical-feed-course">{feed.course_name}</span>
                          {feed.last_synced_at && (
                            <span className="ical-feed-synced">
                              Last synced {new Date(feed.last_synced_at).toLocaleDateString()}
                            </span>
                          )}
                          {feedPendingCounts[feed.id] > 0 && (
                            <span className="ical-review-badge">
                              {feedPendingCounts[feed.id]} need review
                            </span>
                          )}
                        </div>
                        <div className="ical-feed-actions">
                          {feedPendingCounts[feed.id] > 0 && (
                            <button
                              className="settings-review-btn"
                              onClick={() => openReview(feed.id, feed.course_name)}
                            >Review</button>
                          )}
                          <button
                            className="schedule-block-edit"
                            onClick={() => handleIcalEditStart(feed)}
                            aria-label="Edit feed"
                          >Edit</button>
                          <button
                            className="schedule-block-remove"
                            onClick={() => handleIcalDelete(feed.id)}
                            aria-label="Remove feed"
                          >×</button>
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}

            {showIcalAdd ? (
              <div className="ical-add-form">
                <input
                  type="text"
                  className="settings-token-input"
                  placeholder="Course name (e.g. STRAT 490R)"
                  value={icalCourse}
                  onChange={(e) => setIcalCourse(e.target.value)}
                />
                <input
                  type="url"
                  className="settings-token-input"
                  placeholder="iCal feed URL (https://learningsuite.byu.edu/iCalFeed/...)"
                  value={icalUrl}
                  onChange={(e) => { setIcalUrl(e.target.value); setIcalPreview(null) }}
                />
                {icalPreview && (
                  <div className="ical-preview">
                    <span className="ical-preview-count">{icalPreview.total} events found</span>
                    {icalPreview.preview.map((item, i) => (
                      <div key={i} className="ical-preview-item">
                        <span className="ical-preview-date">{item.due_date?.slice(0, 10)}</span>
                        <span className="ical-preview-title">{item.title}</span>
                      </div>
                    ))}
                  </div>
                )}
                {icalError && <p className="settings-error">{icalError}</p>}
                <div className="schedule-add-actions">
                  <button
                    type="button"
                    className="settings-secondary-btn"
                    onClick={() => { setShowIcalAdd(false); setIcalUrl(''); setIcalCourse(''); setIcalPreview(null); setIcalError(null) }}
                  >Cancel</button>
                  <button
                    type="button"
                    className="settings-secondary-btn"
                    onClick={handleIcalPreview}
                    disabled={icalPreviewing || !icalUrl.trim() || !icalCourse.trim()}
                  >{icalPreviewing ? 'Checking...' : 'Preview'}</button>
                  <button
                    type="button"
                    className="settings-primary-btn"
                    onClick={handleIcalSave}
                    disabled={icalAdding || !icalUrl.trim() || !icalCourse.trim()}
                  >{icalAdding ? 'Saving...' : 'Save'}</button>
                </div>
              </div>
            ) : (
              <div className="ical-actions">
                <button className="settings-secondary-btn" onClick={() => { setShowIcalAdd(true); setIcalError(null) }}>
                  + Add iCal feed
                </button>
                {icalFeeds.length > 0 && (
                  <button
                    className="settings-action-btn"
                    onClick={handleIcalSync}
                    disabled={icalSyncing}
                  >{icalSyncing ? 'Syncing...' : 'Sync Now'}</button>
                )}
              </div>
            )}

            {icalSyncResult && <p className="settings-hint" style={{ color: '#1a7a35', marginTop: '8px' }}>{icalSyncResult}</p>}

            <p className="settings-hint">
              In Learning Suite: open a course → <strong>Schedule</strong> → <strong>Get iCalendar Feed</strong> → copy the URL.
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

          {/* Notifications Section */}
          <section className="settings-section">
            <h3 className="settings-section-title">Notifications</h3>
            {!pushSupported ? (
              <p className="settings-hint">Push notifications aren&apos;t supported in this browser.</p>
            ) : (
              <>
                <div className="settings-row">
                  <div className="settings-row-info">
                    <span className="settings-row-label">Deadline reminders</span>
                    <span className="settings-row-value">
                      {pushPermission === 'granted' ? 'Enabled' : pushPermission === 'denied' ? 'Blocked by browser' : 'Disabled'}
                    </span>
                  </div>
                  <button
                    className={pushPermission === 'granted' ? 'settings-danger-btn' : 'settings-action-btn'}
                    onClick={handlePushToggle}
                    disabled={pushLoading || pushPermission === 'denied'}
                  >
                    {pushLoading ? 'Working…' : pushPermission === 'granted' ? 'Turn off' : 'Enable'}
                  </button>
                </div>
                {pushPermission === 'denied' && (
                  <p className="settings-hint settings-hint--warn">
                    Notifications are blocked. Go to your browser&apos;s site settings to allow them for this site.
                  </p>
                )}
                {pushError && <p className="settings-error">{pushError}</p>}
                <p className="settings-hint">
                  Get notified 24 hours before an assignment is due.
                </p>
              </>
            )}
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

          {/* AI Profile Section */}
          <section className="settings-section">
            <h3 className="settings-section-title">AI Profile</h3>
            <p className="settings-section-desc">
              CampusAI saves things it learns about you here — exam dates, how long your courses actually take, recurring commitments. You can edit it directly anytime.
            </p>
            <textarea
              className="settings-context-textarea"
              value={studentContext}
              onChange={e => setStudentContext(e.target.value)}
              placeholder="e.g. Stats 121 midterm is March 20. ECON essays take ~3 hours. I have work every Thursday evening."
              rows={4}
              maxLength={2000}
            />
            <div className="settings-save-row">
              {contextSaved && <span className="settings-saved-msg">Saved!</span>}
              <span className="settings-hint" style={{ flex: 1 }}>
                {studentContext.length}/2000 characters
              </span>
              <button
                className="settings-save-btn"
                onClick={handleSaveContext}
                disabled={contextSaving}
              >
                {contextSaving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </section>
        </div>
      </div>

      {/* Classification Review Modal */}
      {reviewFeedId && (
        <div className="review-backdrop" onClick={(e) => e.target === e.currentTarget && setReviewFeedId(null)}>
          <div className="review-modal">
            <div className="review-modal-header">
              <div>
                <h3 className="review-modal-title">Review assignments</h3>
                <p className="review-modal-subtitle">{reviewCourseName} — We classified these with AI. Move anything that&apos;s wrong.</p>
              </div>
              <button className="settings-close" onClick={() => setReviewFeedId(null)} aria-label="Close">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>

            {reviewLoading ? (
              <div className="review-loading">Classifying with AI…</div>
            ) : reviewItems.length === 0 ? (
              <div className="review-loading">Nothing to review.</div>
            ) : (
              <>
                <div className="review-columns">
                  <div className="review-col">
                    <div className="review-col-header review-col-graded">
                      <span className="review-col-icon">✓</span> Assignments
                      <span className="review-col-count">{reviewItems.filter(i => i.content_type === 'graded').length}</span>
                    </div>
                    <ul className="review-list">
                      {reviewItems.filter(i => i.content_type === 'graded').map(item => (
                        <li key={item.id} className="review-item">
                          <span className="review-item-title">{item.title}</span>
                          {item.due_date && (
                            <span className="review-item-due">
                              {new Date(item.due_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                            </span>
                          )}
                          <button className="review-move-btn" onClick={() => toggleReviewItem(item.id)} title="Move to Class Content">
                            →
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div className="review-col">
                    <div className="review-col-header review-col-content">
                      <span className="review-col-icon">✕</span> Hidden from dashboard
                      <span className="review-col-count">{reviewItems.filter(i => i.content_type === 'course_content').length}</span>
                    </div>
                    <ul className="review-list">
                      {reviewItems.filter(i => i.content_type === 'course_content').map(item => (
                        <li key={item.id} className="review-item review-item-hidden">
                          <span className="review-item-title">{item.title}</span>
                          {item.due_date && (
                            <span className="review-item-due">
                              {new Date(item.due_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                            </span>
                          )}
                          <button className="review-move-btn review-move-back" onClick={() => toggleReviewItem(item.id)} title="Move to Assignments">
                            ←
                          </button>
                        </li>
                      ))}
                      {reviewItems.filter(i => i.content_type === 'course_content').length === 0 && (
                        <li className="review-empty">Nothing hidden</li>
                      )}
                    </ul>
                  </div>
                </div>

                <div className="review-modal-footer">
                  <p className="review-footer-hint">Tap → to hide an item, ← to restore it.</p>
                  <button
                    className="settings-primary-btn"
                    onClick={handleConfirmReview}
                    disabled={reviewSaving}
                  >
                    {reviewSaving ? 'Saving…' : 'Confirm & apply'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default Settings
