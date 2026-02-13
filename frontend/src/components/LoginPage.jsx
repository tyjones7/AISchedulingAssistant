import { useState, useEffect } from 'react'
import { API_BASE } from '../config/api'
import './LoginPage.css'

const POLL_INTERVAL = 2000

function LoginPage({ onLoginSuccess }) {
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const [taskId, setTaskId] = useState(null)

  // Poll for login status when we have a task
  useEffect(() => {
    if (!taskId || !loading) return

    const pollStatus = async () => {
      try {
        const response = await fetch(`${API_BASE}/auth/browser-status/${taskId}`)
        if (!response.ok) {
          throw new Error('Failed to check login status')
        }
        const data = await response.json()
        setStatus(data.status)

        if (data.status === 'authenticated') {
          setTaskId(null)
          // Brief delay for a smooth "Login successful!" transition
          setTimeout(() => {
            setLoading(false)
            onLoginSuccess()
          }, 800)
        } else if (data.status === 'failed') {
          setLoading(false)
          setTaskId(null)
          setError(data.error || 'Login failed. Please try again.')
        }
      } catch (err) {
        console.error('[LoginPage] Error polling status:', err)
      }
    }

    const interval = setInterval(pollStatus, POLL_INTERVAL)
    pollStatus()

    return () => clearInterval(interval)
  }, [taskId, loading, onLoginSuccess])

  const handleBYULogin = async () => {
    setLoading(true)
    setError(null)
    setStatus('opening')

    try {
      const response = await fetch(`${API_BASE}/auth/browser-login`, {
        method: 'POST',
      })

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.detail || 'Failed to open login')
      }

      const data = await response.json()
      setTaskId(data.task_id)
      setStatus('waiting_for_login')
    } catch (err) {
      console.error('[LoginPage] Login error:', err)
      setError(err.message || 'Failed to connect to server')
      setLoading(false)
    }
  }

  const getStatusMessage = () => {
    switch (status) {
      case 'opening':
        return 'Opening browser...'
      case 'waiting_for_login':
        return 'Complete login in the browser window...'
      case 'waiting_for_mfa':
        return 'Complete Duo MFA in the browser...'
      case 'authenticated':
        return 'Login successful! Loading assignments...'
      default:
        return 'Connecting...'
    }
  }

  return (
    <div className="login-page">
      <div className="login-container">
        <div className="login-header">
          <div className="login-logo">C</div>
          <h1 className="login-title">CampusAI</h1>
          <p className="login-subtitle">Connect your BYU Learning Suite to manage assignments</p>
        </div>

        <div className="login-content">
          {error && (
            <div className="login-error">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              {error}
            </div>
          )}

          {loading && status && (
            <div className={`login-status ${status === 'authenticated' ? 'login-success' : ''}`}>
              {status === 'authenticated' ? (
                <span className="success-check-wrap">
                  <svg className="success-check" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                </span>
              ) : (
                <span className="status-spinner" />
              )}
              <span className="status-message">{getStatusMessage()}</span>
            </div>
          )}

          <button
            type="button"
            className={`byu-login-button ${loading ? 'is-loading' : ''}`}
            onClick={handleBYULogin}
            disabled={loading}
          >
            <svg className="byu-logo" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
            </svg>
            {loading ? 'Opening BYU Login...' : 'Sign in with BYU'}
          </button>

          <p className="login-instructions">
            A browser window will open to BYU's official login page.
            Sign in there with your NetID and complete Duo authentication.
          </p>
        </div>

        <div className="login-footer">
          <p className="login-note">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
            You'll log in directly on BYU's website. We never see your password.
          </p>
        </div>
      </div>
    </div>
  )
}

export default LoginPage
