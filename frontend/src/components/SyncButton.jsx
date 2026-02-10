import { useState, useEffect, useCallback } from 'react'
import { API_BASE } from '../config/api'
import './SyncButton.css'

const POLL_INTERVAL = 3000
const STALE_THRESHOLD = 24 * 60 * 60 * 1000

const STATUS_MESSAGES = {
  pending: 'Starting...',
  checking_session: 'Checking login...',
  waiting_for_mfa: 'Waiting for MFA...',
  scraping: 'Fetching assignments...',
  updating_db: 'Saving...',
  completed: 'Done!',
  failed: 'Failed',
}

// Log API_BASE on load for debugging
console.log('[SyncButton] API_BASE configured as:', API_BASE)

function SyncButton({ onSyncComplete, triggerSync, onSyncStarted }) {
  const [syncing, setSyncing] = useState(false)
  const [taskId, setTaskId] = useState(null)
  const [status, setStatus] = useState(null)
  const [lastSync, setLastSync] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchLastSync()
  }, [])

  // Handle external trigger to start sync (e.g., after login)
  useEffect(() => {
    if (triggerSync && !syncing) {
      console.log('[SyncButton] Auto-sync triggered')
      handleSync()
      if (onSyncStarted) {
        onSyncStarted()
      }
    }
  }, [triggerSync, syncing, onSyncStarted])

  useEffect(() => {
    if (!taskId || !syncing) return

    let pollFailCount = 0
    const MAX_POLL_FAILURES = 3

    const pollStatus = async () => {
      const url = `${API_BASE}/sync/status/${taskId}`
      try {
        console.log('[SyncButton] Polling status:', url)
        const response = await fetch(url)

        if (!response.ok) {
          let errorDetail = `HTTP ${response.status}`
          try {
            const data = await response.json()
            errorDetail = data.detail || errorDetail
          } catch {
            // Not JSON
          }
          console.error(`[SyncButton] Status poll failed: ${errorDetail}`, 'URL:', url)

          pollFailCount++
          if (pollFailCount >= MAX_POLL_FAILURES) {
            // Stop polling after multiple failures
            setError(`Status check failed: ${errorDetail}`)
            setSyncing(false)
            setTaskId(null)
            if (onSyncComplete) {
              onSyncComplete()
            }
          }
          return
        }

        // Reset failure count on success
        pollFailCount = 0

        const data = await response.json()
        console.log('[SyncButton] Status response:', data)
        setStatus(data)

        if (data.status === 'completed') {
          setSyncing(false)
          setTaskId(null)
          fetchLastSync()
          if (onSyncComplete) {
            onSyncComplete()
          }
        } else if (data.status === 'failed') {
          setSyncing(false)
          setTaskId(null)
          setError(data.error || 'Sync failed')
          if (onSyncComplete) {
            onSyncComplete()
          }
        }
      } catch (err) {
        console.error('[SyncButton] Error polling status:', err.message, 'URL:', url)
        pollFailCount++
        if (pollFailCount >= MAX_POLL_FAILURES) {
          setError(`Cannot reach backend: ${err.message}`)
          setSyncing(false)
          setTaskId(null)
          if (onSyncComplete) {
            onSyncComplete()
          }
        }
      }
    }

    const interval = setInterval(pollStatus, POLL_INTERVAL)
    pollStatus()

    return () => clearInterval(interval)
  }, [taskId, syncing, onSyncComplete])

  const fetchLastSync = async () => {
    const url = `${API_BASE}/sync/last`
    try {
      console.log('[SyncButton] Fetching last sync from:', url)
      const response = await fetch(url)
      if (!response.ok) {
        console.error(`[SyncButton] Last sync fetch failed: HTTP ${response.status}`, 'URL:', url)
        return
      }
      const data = await response.json()
      console.log('[SyncButton] Last sync response:', data)
      if (data.last_sync) {
        setLastSync(data.last_sync)
      }
    } catch (err) {
      console.error('[SyncButton] Error fetching last sync:', err.message)
      console.error('[SyncButton] Attempted URL:', url)
    }
  }

  const handleSync = async () => {
    if (syncing) return

    setError(null)
    setSyncing(true)
    setStatus({ status: 'pending', message: 'Starting sync...' })

    if (onSyncStarted) {
      onSyncStarted()
    }

    const url = `${API_BASE}/sync/start`
    try {
      console.log('[SyncButton] Starting sync POST to:', url)
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      })

      console.log('[SyncButton] Sync start response:', response.status, response.statusText, 'URL:', response.url)

      if (!response.ok) {
        let errorMessage = `HTTP ${response.status}: ${response.statusText}`
        let responseBody = ''
        try {
          responseBody = await response.text()
          console.error('[SyncButton] Response body:', responseBody)
          // Try to parse as JSON for better error message
          const data = JSON.parse(responseBody)
          errorMessage = data.detail || errorMessage
        } catch {
          // Response wasn't JSON - might be HTML from frontend dev server
          if (responseBody.includes('<!DOCTYPE') || responseBody.includes('<html')) {
            errorMessage = `Backend not reachable at ${url}. Make sure uvicorn is running on port 8000.`
          }
        }
        console.error('[SyncButton] Sync start error:', errorMessage)
        console.error('[SyncButton] Request URL:', url)
        console.error('[SyncButton] Response URL:', response.url)
        throw new Error(errorMessage)
      }

      const data = await response.json()
      console.log('[SyncButton] Sync started successfully, task_id:', data.task_id)
      setTaskId(data.task_id)
    } catch (err) {
      console.error('[SyncButton] Error starting sync:', err.message)
      console.error('[SyncButton] Attempted URL:', url)
      // Provide helpful error message
      let displayError = err.message || 'Failed to connect to backend'
      if (err.name === 'TypeError' && err.message.includes('Failed to fetch')) {
        displayError = `Cannot connect to backend at ${API_BASE}. Is the server running?`
      }
      setError(displayError)
      setSyncing(false)
      setStatus(null)
      if (onSyncComplete) {
        onSyncComplete()
      }
    }
  }

  const formatLastSync = useCallback(() => {
    if (!lastSync?.last_sync_at) return null

    const syncDate = new Date(lastSync.last_sync_at)
    const now = new Date()
    const diffMs = now - syncDate

    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    return `${diffDays}d ago`
  }, [lastSync])

  const isStale = useCallback(() => {
    if (!lastSync?.last_sync_at) return true

    const syncDate = new Date(lastSync.last_sync_at)
    const now = new Date()
    return now - syncDate > STALE_THRESHOLD
  }, [lastSync])

  const getStatusMessage = () => {
    if (!status) return null
    return STATUS_MESSAGES[status.status] || status.message
  }

  const buttonClasses = [
    'sync-btn',
    syncing && 'is-syncing',
    isStale() && !syncing && 'is-stale',
  ].filter(Boolean).join(' ')

  return (
    <div className="sync-container">
      {/* Status info - show either sync progress, error, or last sync time */}
      <div className="sync-info">
        {syncing && status && (
          <span className="sync-status-text">
            <span className="status-dot" />
            {getStatusMessage()}
          </span>
        )}

        {error && !syncing && (
          <span className="sync-error-text">{error}</span>
        )}

        {!syncing && !error && lastSync && (
          <>
            {isStale() && <span className="stale-indicator">Outdated</span>}
            <span className={`last-sync-text ${isStale() ? 'is-stale' : ''}`}>
              Synced {formatLastSync()}
            </span>
          </>
        )}
      </div>

      {/* Sync button */}
      <button
        className={buttonClasses}
        onClick={handleSync}
        disabled={syncing}
        title={syncing ? 'Syncing...' : 'Sync with Learning Suite'}
      >
        <span className={`sync-icon ${syncing ? 'is-spinning' : ''}`}>
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M3 3v5h5" />
            <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
            <path d="M16 21h5v-5" />
          </svg>
        </span>
        <span className="sync-label">
          {syncing ? 'Syncing' : 'Sync'}
        </span>
      </button>
    </div>
  )
}

export default SyncButton
