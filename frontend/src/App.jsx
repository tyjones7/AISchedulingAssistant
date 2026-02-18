import { useState, useEffect, Component } from 'react'
import Dashboard from './components/Dashboard'
import LoginPage from './components/LoginPage'
import { API_BASE } from './config/api'
import './App.css'

class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', gap: '16px', padding: '24px', textAlign: 'center' }}>
          <h1 style={{ fontSize: '1.25rem', fontWeight: 600 }}>Something went wrong</h1>
          <button
            onClick={() => window.location.reload()}
            style={{ padding: '8px 20px', background: '#0071e3', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '0.875rem', fontWeight: 500 }}
          >
            Reload page
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(null) // null = loading
  const [shouldSync, setShouldSync] = useState(false)

  // Check auth status on mount
  useEffect(() => {
    checkAuthStatus()
  }, [])

  const checkAuthStatus = async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/status`)
      if (response.ok) {
        const data = await response.json()
        setIsAuthenticated(data.authenticated || data.canvas_connected)
      } else {
        setIsAuthenticated(false)
      }
    } catch (err) {
      console.error('[App] Error checking auth status:', err)
      // If backend is not running, show login page
      setIsAuthenticated(false)
    }
  }

  const handleLoginSuccess = () => {
    setIsAuthenticated(true)
    setShouldSync(true) // Trigger sync after login
  }

  const handleSyncTriggered = () => {
    setShouldSync(false) // Reset after sync is triggered
  }

  const handleLogout = async () => {
    try {
      await fetch(`${API_BASE}/auth/logout`, { method: 'POST' })
    } catch {
      // Proceed with local logout even if request fails
    }
    setIsAuthenticated(false)
  }

  // Loading state
  if (isAuthenticated === null) {
    return (
      <ErrorBoundary>
        <div className="app-loading">
          <div className="loading-spinner" />
        </div>
      </ErrorBoundary>
    )
  }

  // Show login page if not authenticated
  if (!isAuthenticated) {
    return (
      <ErrorBoundary>
        <LoginPage onLoginSuccess={handleLoginSuccess} />
      </ErrorBoundary>
    )
  }

  // Show dashboard if authenticated
  return (
    <ErrorBoundary>
      <Dashboard autoSync={shouldSync} onSyncTriggered={handleSyncTriggered} onLogout={handleLogout} />
    </ErrorBoundary>
  )
}

export default App
