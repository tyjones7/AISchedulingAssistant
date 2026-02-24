import { useState, useEffect, Component } from 'react'
import Dashboard from './components/Dashboard'
import LoginPage from './components/LoginPage'
import OnboardingSurvey from './components/OnboardingSurvey'
import { registerPushNotifications, isPushSupported, getPushPermission } from './utils/pushNotifications'
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
  const [preferences, setPreferences] = useState(null)   // null = not yet loaded
  const [showSurvey, setShowSurvey] = useState(false)

  // Check auth status on mount
  useEffect(() => {
    checkAuthStatus()
  }, [])

  const checkAuthStatus = async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/status`)
      if (response.ok) {
        const data = await response.json()
        const authed = data.authenticated || data.canvas_connected
        setIsAuthenticated(authed)
        if (authed) loadPreferences()
      } else {
        setIsAuthenticated(false)
      }
    } catch (err) {
      console.error('[App] Error checking auth status:', err)
      setIsAuthenticated(false)
    }
  }

  const loadPreferences = async () => {
    try {
      const res = await fetch(`${API_BASE}/preferences`)
      if (res.ok) {
        const data = await res.json()
        setPreferences(data)
        if (!data.id) {
          // First time — show the onboarding survey
          setShowSurvey(true)
        } else {
          // Returning user — re-register push if they already granted permission
          if (getPushPermission() === 'granted') maybeRegisterPush(data)
        }
      }
    } catch {
      setPreferences({}) // fall back to defaults silently
    }
  }

  const maybeRegisterPush = (prefs) => {
    if (!prefs) return
    if (!isPushSupported()) return
    if (getPushPermission() === 'denied') return
    const level = prefs.involvement_level ?? 'balanced'
    if (level === 'prompt_only') return
    // Request push permission for proactive/balanced users
    registerPushNotifications()
  }

  const handleSurveyComplete = (prefs) => {
    setShowSurvey(false)
    if (prefs) {
      setPreferences(prefs)
      maybeRegisterPush(prefs)
    }
  }

  const handleLoginSuccess = async () => {
    setIsAuthenticated(true)
    loadPreferences()
    // Only auto-sync if there hasn't been a successful sync in the past 12 hours
    try {
      const res = await fetch(`${API_BASE}/sync/last`)
      if (res.ok) {
        const data = await res.json()
        const lastSync = data.last_sync
        // Only skip if last sync was successful AND recent
        if (lastSync?.last_sync_status === 'completed' && lastSync?.last_sync_at) {
          const diffHours = (Date.now() - new Date(lastSync.last_sync_at).getTime()) / 3600000
          if (diffHours < 12) return // Recent successful sync — skip auto-sync
        }
      }
    } catch { /* ignore — proceed with sync if check fails */ }
    setShouldSync(true)
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
      {showSurvey && <OnboardingSurvey onComplete={handleSurveyComplete} />}
      <Dashboard
        autoSync={shouldSync}
        onSyncTriggered={handleSyncTriggered}
        onLogout={handleLogout}
        preferences={preferences}
        onPreferencesChange={setPreferences}
      />
    </ErrorBoundary>
  )
}

export default App
