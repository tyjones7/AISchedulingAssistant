import { useState, useEffect, Component } from 'react'
import Dashboard from './components/Dashboard'
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
  const [session, setSession] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isCanvasConnected, setIsCanvasConnected] = useState(false)
  const [shouldSync, setShouldSync] = useState(false)
  const [preferences, setPreferences] = useState(null)
  const [showOnboarding, setShowOnboarding] = useState(false)

  // Keep-alive ping every 14 minutes
  useEffect(() => {
    const ping = () => fetch(`${API_BASE}/ping`).catch(() => {})
    ping()
    const interval = setInterval(ping, 14 * 60 * 1000)
    return () => clearInterval(interval)
  }, [])

  // On mount: check session and subscribe to auth changes
  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session: initial } }) => {
      setSession(initial)
      if (initial) {
        initUserState()
      } else {
        setIsLoading(false)
      }
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession)
      if (newSession) {
        initUserState()
      } else {
        setIsCanvasConnected(false)
        setPreferences(null)
        setShowOnboarding(false)
        setIsLoading(false)
      }
    })

    return () => subscription.unsubscribe()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const initUserState = async () => {
    try {
      // Check canvas connection and preferences in parallel
      const [canvasRes, prefsRes] = await Promise.all([
        authFetch(`${API_BASE}/auth/canvas-status`).catch(() => null),
        authFetch(`${API_BASE}/preferences`).catch(() => null),
      ])

      let connected = false
      if (canvasRes?.ok) {
        const data = await canvasRes.json()
        connected = !!data.connected
        setIsCanvasConnected(connected)
      }

      let prefs = null
      if (prefsRes?.ok) {
        prefs = await prefsRes.json()
        setPreferences(prefs)
      }

      // Show onboarding if canvas not connected OR no preferences saved yet
      const hasPrefs = !!(prefs?.id)
      if (!connected || !hasPrefs) {
        setShowOnboarding(true)
      } else {
        // Returning user — re-register push if already granted
        if (getPushPermission() === 'granted') maybeRegisterPush(prefs)
      }
    } catch {
      // Fall through — show dashboard anyway
    } finally {
      setIsLoading(false)
    }
  }

  const maybeRegisterPush = (prefs) => {
    if (!prefs || !isPushSupported()) return
    if (getPushPermission() === 'denied') return
    const level = prefs.involvement_level ?? 'balanced'
    if (level === 'prompt_only') return
    registerPushNotifications()
  }

  const handleAuthSuccess = (newSession) => {
    setSession(newSession)
    // onAuthStateChange fires and calls initUserState
  }

  // Called when onboarding wizard completes
  // prefs = saved preferences or null if skipped, connected = whether canvas was connected
  const handleOnboardingComplete = async (prefs, connected) => {
    setShowOnboarding(false)
    if (prefs) {
      setPreferences(prefs)
      maybeRegisterPush(prefs)
    }
    if (connected) {
      setIsCanvasConnected(true)
      // Auto-sync after connecting Canvas for the first time
      try {
        const res = await authFetch(`${API_BASE}/sync/last`)
        if (res.ok) {
          const data = await res.json()
          const lastSync = data.last_sync
          if (lastSync?.last_sync_status === 'completed' && lastSync?.last_sync_at) {
            const diffHours = (Date.now() - new Date(lastSync.last_sync_at).getTime()) / 3600000
            if (diffHours < 12) return
          }
        }
      } catch { /* proceed with sync */ }
      setShouldSync(true)
    }
  }

  const handleSyncTriggered = () => setShouldSync(false)

  const handleLogout = async () => {
    try {
      await authFetch(`${API_BASE}/auth/logout`, { method: 'POST' })
    } catch { /* proceed */ }
    await supabase.auth.signOut()
  }

  if (isLoading) {
    return (
      <ErrorBoundary>
        <div className="app-loading">
          <div className="loading-spinner" />
        </div>
      </ErrorBoundary>
    )
  }

  if (!session) {
    return (
      <ErrorBoundary>
        <AuthPage onAuthSuccess={handleAuthSuccess} />
      </ErrorBoundary>
    )
  }

  // Logged in — always show dashboard, onboarding modal overlays on top if needed
  return (
    <ErrorBoundary>
      {showOnboarding && (
        <OnboardingSurvey
          onComplete={handleOnboardingComplete}
          isCanvasConnected={isCanvasConnected}
        />
      )}
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
