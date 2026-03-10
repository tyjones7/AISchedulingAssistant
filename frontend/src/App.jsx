import { useState, useEffect, Component } from 'react'
import Dashboard from './components/Dashboard'
import LoginPage from './components/LoginPage'
import AuthPage from './components/AuthPage'
import OnboardingSurvey from './components/OnboardingSurvey'
import { registerPushNotifications, isPushSupported, getPushPermission } from './utils/pushNotifications'
import { supabase } from './lib/supabase'
import { authFetch, API_BASE } from './lib/api'
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
  // null = loading, false = no session, object = session
  const [session, setSession] = useState(null)
  const [isLoading, setIsLoading] = useState(true)

  // Whether BYU Learning Suite or Canvas is connected (backend auth)
  const [isBYUConnected, setIsBYUConnected] = useState(false)

  const [shouldSync, setShouldSync] = useState(false)
  const [preferences, setPreferences] = useState(null)   // null = not yet loaded
  const [showSurvey, setShowSurvey] = useState(false)

  // Keep-alive ping every 14 minutes to prevent Render free tier from sleeping
  useEffect(() => {
    const ping = () => fetch(`${API_BASE}/ping`).catch(() => {})
    ping()
    const interval = setInterval(ping, 14 * 60 * 1000)
    return () => clearInterval(interval)
  }, [])

  // On mount: check existing Supabase session and subscribe to auth changes
  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session: initialSession } }) => {
      setSession(initialSession)
      if (initialSession) {
        checkBYUAuth()
      } else {
        setIsLoading(false)
      }
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession)
      if (newSession) {
        checkBYUAuth()
      } else {
        setIsBYUConnected(false)
        setPreferences(null)
        setShowSurvey(false)
        setIsLoading(false)
      }
    })

    return () => subscription.unsubscribe()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const checkBYUAuth = async () => {
    try {
      const response = await authFetch(`${API_BASE}/auth/canvas-status`)
      if (response.ok) {
        const data = await response.json()
        const connected = !!data.connected
        setIsBYUConnected(connected)
        if (connected) loadPreferences()
      } else {
        setIsBYUConnected(false)
      }
    } catch (err) {
      console.error('[App] Error checking Canvas auth status:', err)
      setIsBYUConnected(false)
    } finally {
      setIsLoading(false)
    }
  }

  const loadPreferences = async () => {
    try {
      const res = await authFetch(`${API_BASE}/preferences`)
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

  const handleAuthSuccess = (newSession) => {
    setSession(newSession)
    // onAuthStateChange will fire and call checkBYUAuth
  }

  const handleSurveyComplete = (prefs) => {
    setShowSurvey(false)
    if (prefs) {
      setPreferences(prefs)
      maybeRegisterPush(prefs)
    }
  }

  const handleLoginSuccess = async () => {
    setIsBYUConnected(true)
    loadPreferences()
    // Only auto-sync if there hasn't been a successful sync in the past 12 hours
    try {
      const res = await authFetch(`${API_BASE}/sync/last`)
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
      await authFetch(`${API_BASE}/auth/logout`, { method: 'POST' })
    } catch {
      // Proceed with logout even if backend call fails
    }
    await supabase.auth.signOut()
    // onAuthStateChange will fire and reset state
  }

  // Loading state
  if (isLoading) {
    return (
      <ErrorBoundary>
        <div className="app-loading">
          <div className="loading-spinner" />
        </div>
      </ErrorBoundary>
    )
  }

  // No Supabase session — show email/password auth page
  if (!session) {
    return (
      <ErrorBoundary>
        <AuthPage onAuthSuccess={handleAuthSuccess} />
      </ErrorBoundary>
    )
  }

  // Supabase session exists but no BYU/Canvas connection — show BYU connect page
  if (!isBYUConnected) {
    return (
      <ErrorBoundary>
        <LoginPage onLoginSuccess={handleLoginSuccess} />
      </ErrorBoundary>
    )
  }

  // Fully authenticated — show dashboard
  return (
    <ErrorBoundary>
      {showSurvey && <OnboardingSurvey onComplete={handleSurveyComplete} />}
      <Dashboard
        autoSync={shouldSync}
        onSyncTriggered={handleSyncTriggered}
        onLogout={handleLogout}
        preferences={preferences}
        onPreferencesChange={setPreferences}
        session={session}
      />
    </ErrorBoundary>
  )
}

export default App
