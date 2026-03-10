import { useState } from 'react'
import { authFetch, API_BASE } from '../lib/api'
import './OnboardingSurvey.css'

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

// step = -1 → welcome, 0 → canvas connect, 1-5 → survey questions
export default function OnboardingSurvey({ onComplete, isCanvasConnected }) {
  const [step, setStep] = useState(-1)
  const [answers, setAnswers] = useState({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  // Canvas connect state
  const [canvasToken, setCanvasToken] = useState('')
  const [canvasLoading, setCanvasLoading] = useState(false)
  const [canvasError, setCanvasError] = useState(null)
  const [canvasConnected, setCanvasConnected] = useState(!!isCanvasConnected)
  const [canvasUser, setCanvasUser] = useState(null)

  // ── Welcome ──────────────────────────────────────────────────────────
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
            Your AI-powered assignment dashboard. Connect Canvas, get smart scheduling suggestions, and stay ahead of every deadline.
          </p>
          <ul className="survey-feature-list">
            <li>
              <span className="feature-icon">📋</span>
              <span>Syncs all your Canvas assignments automatically</span>
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

  // ── Canvas Connect ───────────────────────────────────────────────────
  if (step === 0) {
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
            <div className="survey-step-badge">Step 1 of 2</div>
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
            <button className="survey-back" onClick={() => setStep(-1)}>Back</button>
            {!canvasConnected && (
              <button className="survey-skip" onClick={() => setStep(1)}>
                Skip for now
              </button>
            )}
            <button
              className="survey-next"
              onClick={() => setStep(1)}
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

  // ── Survey questions (steps 1–5) ─────────────────────────────────────
  const surveyIndex = step - 1  // 0-based index into SURVEY_STEPS
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
      onComplete(prefs, canvasConnected)
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
          <div className="survey-step-badge" style={{ marginBottom: '0.5rem' }}>Step 2 of 2 — Personalize</div>
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
          <button className="survey-back" onClick={() => setStep((s) => s - 1)}>Back</button>
          <button className="survey-skip" onClick={() => onComplete(null, canvasConnected)}>
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
