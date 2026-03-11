import { useState } from 'react'
import { authFetch, API_BASE } from '../lib/api'
import './OnboardingSurvey.css'

// ── Step numbering ────────────────────────────────────────────────────────────
//  -1  Welcome
//   0  Where are your classes? (classSource)
//   1  Canvas token connect     (skipped when classSource === 'ls')
//   2  Learning Suite iCal      (skipped when classSource === 'canvas')
//  3–7  Survey questions (5 questions, same as before)
// ─────────────────────────────────────────────────────────────────────────────

const SURVEY_STEPS = [
  {
    id: 'study_time',
    question: 'When do you do your best work?',
    options: [
      { value: 'morning',   label: 'Morning',   sub: 'Before noon' },
      { value: 'afternoon', label: 'Afternoon',  sub: 'Noon – 5 pm' },
      { value: 'evening',   label: 'Evening',    sub: '5 – 9 pm' },
      { value: 'night',     label: 'Late night', sub: '9 pm or later' },
    ],
  },
  {
    id: 'session_length_minutes',
    question: 'How long do you like to study in one sitting?',
    options: [
      { value: 30,  label: '30 min',   sub: 'Short bursts' },
      { value: 60,  label: '1 hour',   sub: 'Focused blocks' },
      { value: 90,  label: '90 min',   sub: 'Deep work' },
      { value: 120, label: '2+ hours', sub: 'Marathon sessions' },
    ],
  },
  {
    id: 'advance_days',
    question: 'When do you like to start an assignment?',
    options: [
      { value: 0, label: 'Day it\'s due',   sub: 'Under pressure' },
      { value: 1, label: 'Day before',       sub: 'Last minute' },
      { value: 3, label: 'A few days early', sub: 'Some buffer' },
      { value: 7, label: 'A week ahead',     sub: 'Well planned' },
    ],
  },
  {
    id: 'work_style',
    question: 'How do you prefer to tackle assignments?',
    options: [
      { value: 'spread_out', label: 'Spread it out', sub: 'Multiple shorter sessions' },
      { value: 'batch',      label: 'Knock it out',  sub: 'One long sitting' },
    ],
  },
  {
    id: 'involvement_level',
    question: 'How involved should the AI be?',
    options: [
      { value: 'proactive',   label: 'Proactive',  sub: 'Suggests plans automatically' },
      { value: 'balanced',    label: 'Balanced',   sub: 'Nudges near deadlines' },
      { value: 'prompt_only', label: 'On demand',  sub: 'Only when I ask' },
    ],
  },
]

const CLASS_SOURCE_OPTIONS = [
  { value: 'canvas',   label: 'Canvas only',      sub: 'byu.instructure.com' },
  { value: 'ls',       label: 'Learning Suite',   sub: 'learningsuite.byu.edu' },
  { value: 'both',     label: 'Both',             sub: 'Canvas + Learning Suite' },
  { value: 'not_sure', label: 'Not sure',         sub: "I'll set up both options" },
]

// ── Navigation helpers ────────────────────────────────────────────────────────

function getNextStep(current, classSource) {
  if (current === -1) return 0
  if (current === 0) {
    if (classSource === 'ls') return 2   // skip Canvas
    return 1                              // canvas / both / not_sure → Canvas first
  }
  if (current === 1) {
    if (classSource === 'canvas') return 3  // skip LS
    return 2                                 // both / not_sure → LS step
  }
  if (current === 2) return 3
  return current + 1  // survey steps 3–7
}

function getPrevStep(current, classSource) {
  if (current === 0) return -1
  if (current === 1) return 0
  if (current === 2) {
    if (classSource === 'ls') return 0
    return 1  // both / not_sure came from Canvas step
  }
  if (current === 3) {
    if (classSource === 'canvas') return 1
    return 2  // ls / both / not_sure came from LS step
  }
  return current - 1
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function OnboardingSurvey({ onComplete, isCanvasConnected }) {
  const [step, setStep] = useState(-1)
  const [classSource, setClassSource] = useState(null)
  const [answers, setAnswers] = useState({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  // Canvas connect state
  const [canvasToken, setCanvasToken] = useState('')
  const [canvasLoading, setCanvasLoading] = useState(false)
  const [canvasError, setCanvasError] = useState(null)
  const [canvasConnected, setCanvasConnected] = useState(!!isCanvasConnected)
  const [canvasUser, setCanvasUser] = useState(null)

  // LS iCal state
  const [lsFeeds, setLsFeeds] = useState([])   // feeds saved to backend during onboarding
  const [lsUrl, setLsUrl] = useState('')
  const [lsCourse, setLsCourse] = useState('')
  const [lsAdding, setLsAdding] = useState(false)
  const [lsPreviewing, setLsPreviewing] = useState(false)
  const [lsPreview, setLsPreview] = useState(null)
  const [lsError, setLsError] = useState(null)

  const goNext = () => setStep(s => getNextStep(s, classSource))
  const goBack = () => setStep(s => getPrevStep(s, classSource))

  // ── Step -1: Welcome ──────────────────────────────────────────────────────

  if (step === -1) {
    return (
      <div className="survey-backdrop">
        <div className="survey-card survey-welcome-card">
          <div className="survey-welcome-logo">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="28" height="28">
              <rect x="3" y="4" width="18" height="18" rx="2"/>
              <line x1="3" y1="9" x2="21" y2="9"/>
              <line x1="8" y1="2" x2="8" y2="6"/>
              <line x1="16" y1="2" x2="16" y2="6"/>
              <path d="M12 13l-1 3h2l-1 3"/>
            </svg>
          </div>
          <h1 className="survey-welcome-title">Welcome to CampusAI</h1>
          <p className="survey-welcome-sub">
            Your AI-powered assignment dashboard. Syncs from Canvas and Learning Suite, gives smart scheduling suggestions, and keeps you ahead of every deadline.
          </p>
          <ul className="survey-feature-list">
            <li>
              <span className="feature-icon">📋</span>
              <span>Pulls assignments from Canvas and Learning Suite automatically</span>
            </li>
            <li>
              <span className="feature-icon">🧠</span>
              <span>AI recommends when to start based on your schedule</span>
            </li>
            <li>
              <span className="feature-icon">📅</span>
              <span>Export study blocks to Google Calendar or Apple Calendar</span>
            </li>
            <li>
              <span className="feature-icon">🔔</span>
              <span>Deadline reminders before anything slips through</span>
            </li>
          </ul>
          <button className="survey-next survey-welcome-btn" onClick={() => setStep(0)}>
            Get started
          </button>
        </div>
      </div>
    )
  }

  // ── Step 0: Class source ──────────────────────────────────────────────────

  if (step === 0) {
    return (
      <div className="survey-backdrop">
        <div className="survey-card">
          <div className="survey-header">
            <div className="survey-logo">CampusAI</div>
            <div className="survey-step-badge">Setup</div>
          </div>

          <div className="survey-body">
            <h2 className="survey-question">Where are your BYU classes?</h2>
            <div className="survey-options cols-2">
              {CLASS_SOURCE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  className={`survey-option ${classSource === opt.value ? 'selected' : ''}`}
                  onClick={() => setClassSource(opt.value)}
                >
                  <span className="survey-opt-label">{opt.label}</span>
                  <span className="survey-opt-sub">{opt.sub}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="survey-footer">
            <button className="survey-back" onClick={goBack}>Back</button>
            <button
              className="survey-next"
              style={{ marginLeft: 'auto' }}
              onClick={goNext}
              disabled={!classSource}
            >
              Continue
            </button>
          </div>
        </div>
      </div>
    )
  }

  // ── Step 1: Canvas connect ────────────────────────────────────────────────

  if (step === 1) {
    const handleConnect = async () => {
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
          throw new Error(data.detail || 'Invalid token — check and try again.')
        }
        const data = await res.json()
        setCanvasConnected(true)
        setCanvasUser(data.user_name)
        setCanvasToken('')
      } catch (err) {
        setCanvasError(err.message || 'Failed to connect. Please try again.')
      } finally {
        setCanvasLoading(false)
      }
    }

    return (
      <div className="survey-backdrop">
        <div className="survey-card survey-canvas-card">
          <div className="survey-canvas-header">
            <div className="survey-step-badge">Connect Canvas</div>
            <h2 className="survey-canvas-title">Connect Canvas</h2>
            <p className="survey-canvas-sub">
              CampusAI needs a read-only API token to pull your assignments. It can&apos;t submit or change anything.
            </p>
          </div>

          <div className="survey-canvas-body">
            {canvasConnected ? (
              <div className="survey-canvas-success">
                <div className="canvas-success-icon">✓</div>
                <div>
                  <div className="canvas-success-name">{canvasUser || 'Canvas connected'}</div>
                  <div className="canvas-success-sub">Your courses are ready to sync</div>
                </div>
              </div>
            ) : (
              <>
                <div className="survey-instructions">
                  <p className="survey-instructions-title">How to get your token:</p>
                  <ol className="survey-instructions-list">
                    <li>Go to <strong>Canvas</strong> → click your <strong>Account</strong> (top-left avatar)</li>
                    <li>Click <strong>Settings</strong></li>
                    <li>Scroll to <strong>&quot;Approved Integrations&quot;</strong></li>
                    <li>Click <strong>&quot;+ New Access Token&quot;</strong></li>
                    <li>Name it <em>CampusAI</em>, leave expiry blank, click <strong>Generate</strong></li>
                    <li>Copy the token and paste it below</li>
                  </ol>
                  <a
                    className="survey-canvas-link"
                    href="https://byu.instructure.com/profile/settings"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open Canvas Settings →
                  </a>
                </div>

                <div className="survey-token-row">
                  <input
                    type="password"
                    className="survey-token-input"
                    placeholder="Paste your Canvas API token here"
                    value={canvasToken}
                    onChange={(e) => setCanvasToken(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleConnect()}
                    disabled={canvasLoading}
                    autoFocus
                  />
                  <button
                    className="survey-token-btn"
                    onClick={handleConnect}
                    disabled={canvasLoading || !canvasToken.trim()}
                  >
                    {canvasLoading ? 'Checking…' : 'Connect'}
                  </button>
                </div>

                {canvasError && <p className="survey-error">{canvasError}</p>}

                <p className="survey-security-note">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                  </svg>
                  Token is encrypted and only used to read assignment data — never shared.
                </p>
              </>
            )}
          </div>

          <div className="survey-footer">
            <button className="survey-back" onClick={goBack}>Back</button>
            {!canvasConnected && (
              <button className="survey-skip" onClick={goNext}>
                Skip for now
              </button>
            )}
            <button
              className="survey-next"
              onClick={goNext}
              disabled={!canvasConnected && canvasToken.trim().length > 0 && canvasLoading}
              style={{ marginLeft: canvasConnected ? 'auto' : undefined }}
            >
              {canvasConnected ? 'Continue' : 'Skip'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  // ── Step 2: Learning Suite iCal setup ─────────────────────────────────────

  if (step === 2) {
    const handlePreview = async () => {
      const url = lsUrl.trim()
      const course = lsCourse.trim()
      if (!url || !course) return
      setLsPreviewing(true)
      setLsError(null)
      setLsPreview(null)
      try {
        const res = await authFetch(`${API_BASE}/ls-feeds/preview`, {
          method: 'POST',
          body: JSON.stringify({ url, course_name: course }),
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || 'Could not load feed')
        setLsPreview(data)
      } catch (err) {
        setLsError(err.message || 'Could not preview this URL')
      } finally {
        setLsPreviewing(false)
      }
    }

    const handleAddFeed = async () => {
      const url = lsUrl.trim()
      const course = lsCourse.trim()
      if (!url || !course) return
      setLsAdding(true)
      setLsError(null)
      try {
        const res = await authFetch(`${API_BASE}/ls-feeds`, {
          method: 'POST',
          body: JSON.stringify({ url, course_name: course }),
        })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail || 'Could not save feed')
        setLsFeeds(prev => [...prev, data.feed])
        setLsUrl('')
        setLsCourse('')
        setLsPreview(null)
      } catch (err) {
        setLsError(err.message || 'Could not add course')
      } finally {
        setLsAdding(false)
      }
    }

    const handleRemoveFeed = async (feedId) => {
      try {
        await authFetch(`${API_BASE}/ls-feeds/${feedId}`, { method: 'DELETE' })
        setLsFeeds(prev => prev.filter(f => f.id !== feedId))
      } catch { /* ignore */ }
    }

    return (
      <div className="survey-backdrop">
        <div className="survey-card survey-ls-card">
          <div className="survey-canvas-header">
            <div className="survey-step-badge">Add Learning Suite Courses</div>
            <h2 className="survey-canvas-title">Add Learning Suite Courses</h2>
            <p className="survey-canvas-sub">
              Each LS course has an iCal feed URL — no login needed. Add each course below.
            </p>
          </div>

          <div className="survey-ls-body">
            {/* Added feeds list */}
            {lsFeeds.length > 0 && (
              <div className="survey-ls-feeds">
                {lsFeeds.map((feed) => (
                  <div key={feed.id} className="survey-ls-feed-row">
                    <span className="survey-ls-feed-name">{feed.course_name}</span>
                    <button
                      className="survey-ls-feed-remove"
                      onClick={() => handleRemoveFeed(feed.id)}
                      aria-label={`Remove ${feed.course_name}`}
                    >×</button>
                  </div>
                ))}
              </div>
            )}

            {/* Instructions */}
            <div className="survey-instructions">
              <p className="survey-instructions-title">How to find your iCal URL:</p>
              <ol className="survey-instructions-list">
                <li>Open <strong>Learning Suite</strong> and click into a course</li>
                <li>Click <strong>Schedule</strong> in the left sidebar</li>
                <li>Click <strong>&quot;Get iCalendar Feed&quot;</strong> at the top of the page</li>
                <li>Click the <strong>copy button</strong> next to the URL</li>
                <li>Paste it below — repeat for each course</li>
              </ol>
              <a
                className="survey-canvas-link"
                href="https://learningsuite.byu.edu"
                target="_blank"
                rel="noopener noreferrer"
              >
                Open Learning Suite →
              </a>
            </div>

            {/* Add course form */}
            <div className="survey-ls-form">
              <input
                type="text"
                className="survey-token-input"
                placeholder="Course name (e.g. STRAT 490R)"
                value={lsCourse}
                onChange={(e) => setLsCourse(e.target.value)}
              />
              <div className="survey-ls-input-row">
                <input
                  type="url"
                  className="survey-token-input"
                  placeholder="iCal feed URL"
                  value={lsUrl}
                  onChange={(e) => { setLsUrl(e.target.value); setLsPreview(null) }}
                />
                <button
                  className="survey-token-btn"
                  onClick={handlePreview}
                  disabled={lsPreviewing || !lsUrl.trim() || !lsCourse.trim()}
                  style={{ whiteSpace: 'nowrap' }}
                >
                  {lsPreviewing ? 'Checking…' : 'Preview'}
                </button>
              </div>

              {lsPreview && (
                <div className="survey-ls-preview">
                  <span className="survey-ls-preview-count">{lsPreview.total} assignments found</span>
                  {lsPreview.preview.map((item, i) => (
                    <div key={i} className="survey-ls-preview-item">
                      <span className="survey-ls-preview-date">{item.due_date?.slice(0, 10)}</span>
                      <span className="survey-ls-preview-title">{item.title}</span>
                    </div>
                  ))}
                </div>
              )}

              {lsError && <p className="survey-error" style={{ textAlign: 'left' }}>{lsError}</p>}

              <button
                className="survey-next"
                style={{ alignSelf: 'flex-start' }}
                onClick={handleAddFeed}
                disabled={lsAdding || !lsUrl.trim() || !lsCourse.trim()}
              >
                {lsAdding ? 'Adding…' : '+ Add Course'}
              </button>
            </div>
          </div>

          <div className="survey-footer">
            <button className="survey-back" onClick={goBack}>Back</button>
            <button className="survey-skip" onClick={goNext}>
              {lsFeeds.length > 0 ? 'Done adding' : 'Skip for now'}
            </button>
            {lsFeeds.length > 0 && (
              <button className="survey-next" onClick={goNext}>
                Continue
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  // ── Steps 3–7: Survey questions ───────────────────────────────────────────

  const surveyIndex = step - 3
  const current = SURVEY_STEPS[surveyIndex]
  const selected = answers[current.id]
  const isLast = surveyIndex === SURVEY_STEPS.length - 1

  const choose = (value) => setAnswers((prev) => ({ ...prev, [current.id]: value }))

  const next = async () => {
    if (selected === undefined) return
    if (!isLast) {
      setStep((s) => s + 1)
      return
    }
    setSaving(true)
    setError(null)
    try {
      const res = await authFetch(`${API_BASE}/preferences`, {
        method: 'POST',
        body: JSON.stringify(answers),
      })
      if (!res.ok) throw new Error('Failed to save')
      const prefs = await res.json()
      onComplete(prefs, canvasConnected, lsFeeds.length > 0)
    } catch {
      setError('Something went wrong. Please try again.')
      setSaving(false)
    }
  }

  return (
    <div className="survey-backdrop">
      <div className="survey-card">
        <div className="survey-header">
          <div className="survey-logo">CampusAI</div>
          <div className="survey-step-badge" style={{ marginBottom: '0.5rem' }}>Personalize</div>
          <div className="survey-progress">
            {SURVEY_STEPS.map((_, i) => (
              <div
                key={i}
                className={`survey-dot ${i < surveyIndex ? 'done' : i === surveyIndex ? 'active' : ''}`}
              />
            ))}
          </div>
        </div>

        <div className="survey-body">
          <h2 className="survey-question">{current.question}</h2>
          <div className={`survey-options cols-${current.options.length}`}>
            {current.options.map((opt) => (
              <button
                key={opt.value}
                className={`survey-option ${selected === opt.value ? 'selected' : ''}`}
                onClick={() => choose(opt.value)}
              >
                <span className="survey-opt-label">{opt.label}</span>
                <span className="survey-opt-sub">{opt.sub}</span>
              </button>
            ))}
          </div>
          {error && <p className="survey-error">{error}</p>}
        </div>

        <div className="survey-footer">
          <button className="survey-back" onClick={() => setStep((s) => getPrevStep(s, classSource))}>Back</button>
          <button className="survey-skip" onClick={() => onComplete(null, canvasConnected, lsFeeds.length > 0)}>
            Skip for now
          </button>
          <button
            className="survey-next"
            onClick={next}
            disabled={selected === undefined || saving}
          >
            {saving ? 'Saving…' : isLast ? 'Go to Dashboard' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  )
}
