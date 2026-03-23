import { useState, useRef, useEffect, useCallback } from 'react'
import { authFetch, API_BASE } from '../lib/api'
import './AIChat.css'

const STORAGE_KEY = 'campus-ai-chat'
const BRIEFING_DATE_KEY = 'campus-ai-briefing-date'

// Chips shown when no schedule exists yet
const CHIPS_NO_PLAN = [
  'Build my study plan for this week',
  "What's most urgent right now?",
  'How long will everything take this week?',
  'What should I work on tonight?',
]

// Chips shown when a schedule already exists
const CHIPS_HAS_PLAN = [
  'How does my week look?',
  "Move tonight's block to tomorrow",
  "I finished early \u2014 what's next?",
  'I need more time for one of my courses',
]

function AIChat({ addToast, involvementLevel = 'balanced', openChatRef, onPlanApplied, hasSchedule = false }) {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      return saved ? JSON.parse(saved) : []
    } catch {
      return []
    }
  })
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [hasPlan, setHasPlan] = useState(false)
  const [isApplying, setIsApplying] = useState(false)
  const [pendingContext, setPendingContext] = useState(null)   // learned insight to save
  const [isSavingContext, setIsSavingContext] = useState(false)

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const briefingLoadedRef = useRef(false)

  // Expose open() to parent via ref so ProactivePlan can open the chat
  useEffect(() => {
    if (openChatRef) openChatRef.current = () => setIsOpen(true)
  }, [openChatRef])

  // Persist conversation to localStorage on every change
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages))
    } catch {
      // Ignore storage errors
    }
  }, [messages])

  // Proactive day overview: inject briefing as first message when chat opens
  // for the first time today (proactive or balanced involvement levels).
  useEffect(() => {
    if (!isOpen) return
    if (involvementLevel === 'prompt_only') return
    if (briefingLoadedRef.current) return
    briefingLoadedRef.current = true

    const today = new Date().toDateString()
    const lastBriefingDate = localStorage.getItem(BRIEFING_DATE_KEY)

    // Only inject once per day, and only when there are no existing messages for today
    const hasMessagesToday = messages.length > 0 && lastBriefingDate === today
    if (hasMessagesToday) return

    const loadBriefing = async () => {
      setIsLoading(true)
      setMessages([{ role: 'assistant', content: '' }])
      try {
        const res = await authFetch(`${API_BASE}/ai/briefing/generate`, { method: 'POST' })
        if (res.ok) {
          const data = await res.json()
          const greeting = data.briefing || "Here's your schedule overview for today."
          setMessages([{ role: 'assistant', content: greeting }])
          localStorage.setItem(BRIEFING_DATE_KEY, today)
        } else {
          setMessages([])
        }
      } catch {
        setMessages([])
      } finally {
        setIsLoading(false)
      }
    }

    loadBriefing()
  }, [isOpen, involvementLevel]) // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll to bottom when messages update or panel opens
  useEffect(() => {
    if (isOpen) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, isOpen])

  // Auto-focus input when panel opens
  useEffect(() => {
    if (isOpen) {
      const timer = setTimeout(() => inputRef.current?.focus(), 150)
      return () => clearTimeout(timer)
    }
  }, [isOpen])

  // Escape key closes panel
  useEffect(() => {
    if (!isOpen) return
    const onKey = (e) => { if (e.key === 'Escape') setIsOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen])

  // Check latest assistant message for <plan> and <context> tags
  useEffect(() => {
    const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant')
    if (!lastAssistant) { setHasPlan(false); return }
    setHasPlan(lastAssistant.content.includes('<plan>'))
    // Extract <context> tag if present and not already pending
    const ctxMatch = lastAssistant.content.match(/<context>([\s\S]*?)<\/context>/)
    if (ctxMatch) {
      const learned = ctxMatch[1].trim()
      if (learned) setPendingContext(learned)
    }
  }, [messages])

  const sendMessage = useCallback(async (userContent) => {
    const trimmed = userContent.trim()
    if (!trimmed || isLoading) return

    const userMessage = { role: 'user', content: trimmed }
    const nextMessages = [...messages, userMessage]

    setMessages(nextMessages)
    setInput('')
    setIsLoading(true)

    // Optimistically add an empty assistant bubble to stream into
    setMessages((prev) => [...prev, { role: 'assistant', content: '' }])

    try {
      const response = await authFetch(`${API_BASE}/ai/chat`, {
        method: 'POST',
        body: JSON.stringify({ messages: nextMessages }),
      })

      if (!response.ok || !response.body) {
        let detail = `HTTP ${response.status}`
        try {
          const data = await response.json()
          detail = data.detail || detail
        } catch { /* not JSON */ }
        setMessages((prev) => {
          const updated = [...prev]
          updated[updated.length - 1] = {
            role: 'assistant',
            content: response.status === 503
              ? 'AI is not configured yet. Add GROQ_API_KEY to the backend .env file.'
              : response.status === 429
              ? "I'm being rate-limited. Please wait a moment and try again."
              : `Something went wrong (${detail}). Please try again.`,
          }
          return updated
        })
        return
      }

      // Stream the SSE response into the last bubble
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() // keep incomplete last line

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6).trim()
          if (payload === '[DONE]') break

          try {
            const parsed = JSON.parse(payload)
            if (parsed.error) {
              setMessages((prev) => {
                const updated = [...prev]
                updated[updated.length - 1] = {
                  role: 'assistant',
                  content: parsed.code === 429
                    ? "I'm being rate-limited. Please wait a moment and try again."
                    : parsed.code === 503
                    ? 'AI is not configured. Add GROQ_API_KEY to backend.'
                    : 'Something went wrong. Please try again.',
                }
                return updated
              })
              return
            }
            if (parsed.delta) {
              setMessages((prev) => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                updated[updated.length - 1] = {
                  ...last,
                  content: last.content + parsed.delta,
                }
                return updated
              })
            }
          } catch { /* malformed SSE line — skip */ }
        }
      }
    } catch (err) {
      console.error('[AIChat] fetch error:', err)
      setMessages((prev) => {
        const updated = [...prev]
        updated[updated.length - 1] = {
          role: 'assistant',
          content: 'Unable to reach the AI service. Make sure the backend is running.',
        }
        return updated
      })
      if (addToast) addToast('AI chat failed. Check your connection.', 'error')
    } finally {
      setIsLoading(false)
    }
  }, [messages, isLoading, addToast])

  const handleSubmit = (e) => {
    e.preventDefault()
    sendMessage(input)
  }

  const handleClear = () => {
    setMessages([])
    setHasPlan(false)
    briefingLoadedRef.current = false
    try {
      localStorage.removeItem(STORAGE_KEY)
      localStorage.removeItem(BRIEFING_DATE_KEY)
    } catch { /* ignore */ }
  }

  const handleApplyPlan = async () => {
    if (isApplying) return
    setIsApplying(true)
    try {
      const response = await authFetch(`${API_BASE}/ai/apply-plan`, {
        method: 'POST',
        body: JSON.stringify({ messages }),
      })
      const data = await response.json()
      if (!response.ok) {
        addToast(data.detail || 'Failed to apply plan.', 'error')
        return
      }
      const blockCount = data.blocks || data.updated
      addToast(
        `Schedule applied! ${blockCount} study block${blockCount !== 1 ? 's' : ''} added to your calendar.`,
        'success'
      )
      onPlanApplied?.()
    } catch (err) {
      console.error('[AIChat] apply-plan error:', err)
      addToast('Failed to apply plan. Check your connection.', 'error')
    } finally {
      setIsApplying(false)
    }
  }

  const handleSaveContext = async () => {
    if (!pendingContext || isSavingContext) return
    setIsSavingContext(true)
    try {
      // Fetch current context first so we append rather than replace
      const prefsRes = await authFetch(`${API_BASE}/preferences`)
      const existingContext = prefsRes.ok ? ((await prefsRes.json()).student_context || '') : ''
      const merged = existingContext
        ? `${existingContext.trim()} ${pendingContext}`
        : pendingContext
      const res = await authFetch(`${API_BASE}/ai/update-context`, {
        method: 'POST',
        body: JSON.stringify({ context: merged }),
      })
      if (res.ok) {
        addToast('Saved to your profile!', 'success')
        setPendingContext(null)
      } else {
        addToast('Failed to save context.', 'error')
      }
    } catch {
      addToast('Failed to save context.', 'error')
    } finally {
      setIsSavingContext(false)
    }
  }

  // Render a single message bubble (with optional streaming cursor)
  const renderBubble = (msg, i) => {
    const isLastAssistant =
      msg.role === 'assistant' && i === messages.length - 1 && isLoading

    // Strip <plan> and <context> tags from displayed text
    const displayContent = msg.content
      .replace(/<plan>[\s\S]*?<\/plan>/g, '')
      .replace(/<context>[\s\S]*?<\/context>/g, '')
      .trim()

    return (
      <div key={i} className={`ai-chat-bubble ai-bubble-${msg.role}`}>
        {displayContent}
        {isLastAssistant && displayContent.length === 0 && (
          // Still empty — show typing dots instead of cursor
          <span className="ai-typing-dots">
            <span className="ai-typing-dot" />
            <span className="ai-typing-dot" />
            <span className="ai-typing-dot" />
          </span>
        )}
        {isLastAssistant && displayContent.length > 0 && (
          <span className="ai-streaming-cursor" aria-hidden="true" />
        )}
      </div>
    )
  }

  return (
    <>
      {/* Floating trigger button */}
      <button
        className={`ai-chat-trigger ${isOpen ? 'is-open' : ''}`}
        onClick={() => setIsOpen((o) => !o)}
        aria-label={isOpen ? 'Close AI assistant' : 'Open AI assistant'}
        title="CampusAI Assistant"
      >
        {isOpen ? (
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        ) : (
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3l1.88 5.76a1 1 0 0 0 .95.69h6.06l-4.9 3.56a1 1 0 0 0-.36 1.12L17.5 20l-4.9-3.56a1 1 0 0 0-1.18 0L6.5 20l1.87-5.87a1 1 0 0 0-.36-1.12L3.11 9.45h6.06a1 1 0 0 0 .95-.69L12 3z" />
          </svg>
        )}
      </button>

      {/* Chat panel */}
      {isOpen && (
        <div className="ai-chat-panel" role="dialog" aria-label="CampusAI scheduling assistant">
          {/* Header */}
          <div className="ai-chat-header">
            <div className="ai-chat-header-left">
              <div className="ai-chat-avatar" aria-hidden="true">AI</div>
              <div className="ai-chat-title-group">
                <span className="ai-chat-title">CampusAI</span>
                <span className="ai-chat-subtitle">Scheduling Assistant</span>
              </div>
            </div>
            <div className="ai-chat-header-right">
              {messages.length > 0 && (
                <button
                  className="ai-chat-icon-btn"
                  onClick={handleClear}
                  title="Clear conversation"
                  aria-label="Clear conversation"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="1 4 1 10 7 10" />
                    <path d="M3.51 15a9 9 0 1 0 .49-3.69" />
                  </svg>
                </button>
              )}
              <button
                className="ai-chat-icon-btn"
                onClick={() => setIsOpen(false)}
                aria-label="Close AI assistant"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          </div>

          {/* Message list */}
          <div className="ai-chat-messages" role="log" aria-live="polite">
            {messages.length === 0 && (
              <div className="ai-chat-empty">
                <div className="ai-chat-empty-icon" aria-hidden="true">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" strokeWidth="1.5">
                    <path d="M12 3l1.88 5.76a1 1 0 0 0 .95.69h6.06l-4.9 3.56a1 1 0 0 0-.36 1.12L17.5 20l-4.9-3.56a1 1 0 0 0-1.18 0L6.5 20l1.87-5.87a1 1 0 0 0-.36-1.12L3.11 9.45h6.06a1 1 0 0 0 .95-.69L12 3z" />
                  </svg>
                </div>
                <p className="ai-chat-empty-text">
                  Ask me anything about your assignments, or try a quick start:
                </p>
              </div>
            )}

            {messages.map(renderBubble)}

            {/* Context save banner — shown when AI learned something worth remembering */}
            {pendingContext && !isLoading && (
              <div className="ai-context-banner">
                <div className="ai-context-icon">💡</div>
                <div className="ai-context-text">
                  <span className="ai-context-label">Learned something new</span>
                  <span className="ai-context-value">&ldquo;{pendingContext}&rdquo;</span>
                </div>
                <div className="ai-context-actions">
                  <button
                    className="ai-context-save"
                    onClick={handleSaveContext}
                    disabled={isSavingContext}
                  >
                    {isSavingContext ? 'Saving…' : 'Save to profile'}
                  </button>
                  <button
                    className="ai-context-dismiss"
                    onClick={() => setPendingContext(null)}
                    aria-label="Dismiss"
                  >✕</button>
                </div>
              </div>
            )}

            {/* Apply plan button — shown after the last AI bubble when a plan is detected */}
            {hasPlan && !isLoading && (
              <div className="ai-apply-row">
                <button
                  className={`ai-apply-btn ${isApplying ? 'is-applying' : ''}`}
                  onClick={handleApplyPlan}
                  disabled={isApplying}
                >
                  {isApplying ? (
                    <>
                      <span className="ai-apply-spinner" aria-hidden="true" />
                      Applying schedule…
                    </>
                  ) : (
                    <>
                      Apply as my schedule
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
                        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="5" y1="12" x2="19" y2="12" />
                        <polyline points="12 5 19 12 12 19" />
                      </svg>
                    </>
                  )}
                </button>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Quick-action chips — only when no conversation yet */}
          {messages.length === 0 && (
            <div className="ai-chat-chips">
              {(hasSchedule ? CHIPS_HAS_PLAN : CHIPS_NO_PLAN).map((chip) => (
                <button
                  key={chip}
                  className="ai-chip"
                  onClick={() => sendMessage(chip)}
                  disabled={isLoading}
                >
                  {chip}
                </button>
              ))}
            </div>
          )}

          {/* Input row */}
          <form className="ai-chat-input-row" onSubmit={handleSubmit}>
            <input
              ref={inputRef}
              type="text"
              className="ai-chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about your assignments…"
              disabled={isLoading}
              aria-label="Chat message"
              maxLength={500}
            />
            <button
              type="submit"
              className="ai-chat-send-btn"
              disabled={isLoading || !input.trim()}
              aria-label="Send message"
            >
              {isLoading ? (
                <span className="ai-send-spinner" aria-hidden="true" />
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              )}
            </button>
          </form>
        </div>
      )}
    </>
  )
}

export default AIChat
