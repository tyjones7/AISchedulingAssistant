import { useState, useEffect } from 'react'
import './AIBriefing.css'

function AIBriefing({ briefing, isGenerating }) {
  const [collapsed, setCollapsed] = useState(!briefing)

  // Auto-expand when briefing first arrives
  useEffect(() => {
    if (briefing) setCollapsed(false)
  }, [briefing])

  const hasBriefing = briefing || isGenerating

  return (
    <div className={`ai-briefing ${hasBriefing ? 'has-content' : 'is-empty'}`}>
      <button
        className="ai-briefing-header"
        onClick={() => setCollapsed((c) => !c)}
        aria-expanded={!collapsed}
        aria-controls="ai-briefing-content"
      >
        <div className="ai-briefing-left">
          <span className="ai-briefing-icon" aria-hidden="true">✦</span>
          <span className="ai-briefing-label">Today&apos;s AI Plan</span>
          {!isGenerating && !briefing && (
            <span className="ai-briefing-hint">Click &ldquo;AI Plan&rdquo; to generate</span>
          )}
          {isGenerating && (
            <span className="ai-briefing-hint is-generating">Generating&hellip;</span>
          )}
        </div>
        <svg
          className={`ai-briefing-chevron ${collapsed ? 'is-collapsed' : ''}`}
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {!collapsed && (
        <div id="ai-briefing-content" className="ai-briefing-content">
          {isGenerating ? (
            <div className="ai-briefing-skeleton" aria-label="Generating AI plan…">
              <div className="skeleton-line" />
              <div className="skeleton-line short" />
            </div>
          ) : (
            <p className="ai-briefing-text">{briefing}</p>
          )}
        </div>
      )}
    </div>
  )
}

export default AIBriefing
