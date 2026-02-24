import { useState } from 'react'
import { API_BASE } from '../config/api'
import './OnboardingSurvey.css'

const STEPS = [
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
      { value: 30,  label: '30 min',    sub: 'Short bursts' },
      { value: 60,  label: '1 hour',    sub: 'Focused blocks' },
      { value: 90,  label: '90 min',    sub: 'Deep work' },
      { value: 120, label: '2+ hours',  sub: 'Marathon sessions' },
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
      { value: 'proactive',   label: 'Proactive',    sub: 'Suggests plans automatically' },
      { value: 'balanced',    label: 'Balanced',     sub: 'Nudges near deadlines' },
      { value: 'prompt_only', label: 'On demand',    sub: 'Only when I ask' },
    ],
  },
]

export default function OnboardingSurvey({ onComplete }) {
  const [step, setStep] = useState(0)
  const [answers, setAnswers] = useState({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const current = STEPS[step]
  const selected = answers[current.id]
  const isLast = step === STEPS.length - 1

  const choose = (value) => {
    setAnswers((prev) => ({ ...prev, [current.id]: value }))
  }

  const next = async () => {
    if (selected === undefined) return
    if (!isLast) {
      setStep((s) => s + 1)
      return
    }
    setSaving(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/preferences`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(answers),
      })
      if (!res.ok) throw new Error('Failed to save')
      const prefs = await res.json()
      onComplete(prefs)
    } catch {
      setError('Something went wrong. Please try again.')
      setSaving(false)
    }
  }

  const skip = () => onComplete(null)

  return (
    <div className="survey-backdrop">
      <div className="survey-card">
        <div className="survey-header">
          <div className="survey-logo">CampusAI</div>
          <p className="survey-intro">
            Answer 5 quick questions so the AI can personalize your schedule.
          </p>
          <div className="survey-progress">
            {STEPS.map((_, i) => (
              <div
                key={i}
                className={`survey-dot ${i < step ? 'done' : i === step ? 'active' : ''}`}
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
          {step > 0 && (
            <button className="survey-back" onClick={() => setStep((s) => s - 1)}>
              Back
            </button>
          )}
          <button className="survey-skip" onClick={skip}>
            Skip for now
          </button>
          <button
            className="survey-next"
            onClick={next}
            disabled={selected === undefined || saving}
          >
            {saving ? 'Saving…' : isLast ? 'Get started' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  )
}
