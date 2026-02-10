import { useState, useEffect } from 'react'
import Dashboard from './components/Dashboard'
import LoginPage from './components/LoginPage'
import { API_BASE } from './config/api'
import './App.css'

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
        setIsAuthenticated(data.authenticated)
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

  // Loading state
  if (isAuthenticated === null) {
    return (
      <div className="app-loading">
        <div className="loading-spinner" />
      </div>
    )
  }

  // Show login page if not authenticated
  if (!isAuthenticated) {
    return <LoginPage onLoginSuccess={handleLoginSuccess} />
  }

  // Show dashboard if authenticated
  return <Dashboard autoSync={shouldSync} onSyncTriggered={handleSyncTriggered} />
}

export default App
