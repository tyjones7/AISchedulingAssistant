import { useState, useEffect } from 'react'
import { authFetch, API_BASE } from '../lib/api'
import './LoginPage.css'

function LoginPage({ onLoginSuccess }) {
  const [canvasToken, setCanvasToken] = useState('')
  const [canvasLoading, setCanvasLoading] = useState(false)
  const [canvasConnected, setCanvasConnected] = useState(false)
  const [canvasUser, setCanvasUser] = useState(null)
  const [canvasError, setCanvasError] = useState(null)

  // Check existing connection status on mount
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const resp = await authFetch(`${API_BASE}/auth/canvas-status`)
        if (resp.ok) {
          const data = await resp.json()
          if (data.connected) {
            setCanvasConnected(true)
            if (data.user_name) setCanvasUser(data.user_name)
          }
        }
      } catch {
        // Backend not running
      }
    }
    checkStatus()
  }, [])

  const handleCanvasConnect = async () => {
    const token = canvasToken.trim()
    if (!token) return

    setCanvasLoading(true)
    setCanvasError(null)

    try {
      const response = await authFetch(`${API_BASE}/auth/canvas-token`, {
        method: 'POST',
        body: JSON.stringify({ token }),
      })

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.detail || 'Failed to connect')
      }

      const data = await response.json()
      setCanvasConnected(true)
      setCanvasUser(data.user_name)
      setCanvasToken('')
    } catch (err) {
      setCanvasError(err.message || 'Failed to validate token')
    } finally {
      setCanvasLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-container">
        <div className="login-header">
          <div className="login-logo">C</div>
          <h1 className="login-title">CampusAI</h1>
          <p className="login-subtitle">Connect your Canvas account to get started</p>
        </div>

        <div className="login-content">
          {/* Canvas LMS Card */}
          <div className={`connection-card ${canvasConnected ? 'is-connected' : ''}`}>
            <div className="connection-card-header">
              <span className="connection-label">Canvas LMS</span>
              {canvasConnected && <span className="connected-badge">Connected</span>}
            </div>

            {canvasConnected ? (
              <>
                <p className="canvas-connected-info">
                  {canvasUser ? `Signed in as ${canvasUser}` : 'Token validated'}
                </p>
                <button
                  type="button"
                  className="continue-button"
                  onClick={onLoginSuccess}
                >
                  Continue to Dashboard
                </button>
              </>
            ) : (
              <>
                {canvasError && (
                  <div className="canvas-error">{canvasError}</div>
                )}
                <div className="canvas-token-row">
                  <input
                    type="password"
                    className="canvas-token-input"
                    placeholder="Paste your Canvas API token"
                    value={canvasToken}
                    onChange={(e) => setCanvasToken(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleCanvasConnect()}
                    disabled={canvasLoading}
                    autoFocus
                  />
                  <button
                    className="canvas-connect-btn"
                    onClick={handleCanvasConnect}
                    disabled={canvasLoading || !canvasToken.trim()}
                  >
                    {canvasLoading ? 'Checking...' : 'Connect'}
                  </button>
                </div>
                <p className="canvas-help-text">
                  Generate a token in{' '}
                  <a
                    href="https://byu.instructure.com/profile/settings"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Canvas Settings
                  </a>
                  {' '}under &quot;Approved Integrations&quot; → &quot;New Access Token.&quot;
                </p>
              </>
            )}
          </div>
        </div>

        <div className="login-footer">
          <p className="login-note">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
            Your token is encrypted and never shared. It only reads your assignments.
          </p>
        </div>
      </div>
    </div>
  )
}

export default LoginPage
