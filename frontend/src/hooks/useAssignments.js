/**
 * useAssignments — manages assignment state, status updates, and exit animations.
 *
 * Extracted from Dashboard.jsx to keep that component focused on rendering.
 * Owns: assignments list, loading/error state, optimistic status updates,
 * exit animation tracking, and last-sync timestamp.
 */

import { useState, useCallback } from 'react'
import { authFetch, API_BASE } from '../lib/api'

const STATUS_LABELS = {
  newly_assigned: 'New',
  not_started: 'Not Started',
  in_progress: 'In Progress',
  submitted: 'Submitted',
  unavailable: 'Unavailable',
}

export function useAssignments(addToast) {
  const [assignments, setAssignments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [updatingIds, setUpdatingIds] = useState(new Set())
  const [exitingIds, setExitingIds] = useState(new Set())
  const [lastSyncTime, setLastSyncTime] = useState(null)

  const fetchAssignments = useCallback(async () => {
    try {
      const response = await authFetch(`${API_BASE}/assignments?exclude_past_submitted=true`)
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      const data = await response.json()
      setAssignments(data.assignments || [])
      setError(null)
    } catch (err) {
      console.error('[useAssignments] Failed to fetch:', err)
      setError(`Failed to load assignments. Make sure the backend is running on ${API_BASE}`)
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchLastSync = useCallback(async () => {
    try {
      const response = await authFetch(`${API_BASE}/sync/last`)
      if (!response.ok) return
      const data = await response.json()
      if (data.last_sync?.last_sync_at) setLastSyncTime(data.last_sync.last_sync_at)
    } catch (err) {
      console.error('[useAssignments] Error fetching last sync:', err)
    }
  }, [])

  const handleStatusChange = useCallback(async (assignmentId, newStatus) => {
    const original = assignments.find((a) => a.id === assignmentId)
    if (!original) return

    // Optimistic update
    setAssignments((prev) => prev.map((a) => a.id === assignmentId ? { ...a, status: newStatus } : a))
    setUpdatingIds((prev) => new Set([...prev, assignmentId]))

    try {
      const response = await authFetch(`${API_BASE}/assignments/${assignmentId}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: newStatus }),
      })
      if (!response.ok) throw new Error('Failed to update status')

      const data = await response.json()
      setAssignments((prev) => prev.map((a) => a.id === assignmentId ? data.assignment : a))
      addToast(`Moved to "${STATUS_LABELS[newStatus]}"`, 'success')

      // Play exit animation when card is about to leave the list
      if (newStatus === 'submitted') {
        setExitingIds((prev) => new Set([...prev, assignmentId]))
        setTimeout(() => {
          setExitingIds((prev) => { const n = new Set(prev); n.delete(assignmentId); return n })
        }, 450)
      }
    } catch (err) {
      console.error('[useAssignments] Failed to update status:', err)
      setAssignments((prev) => prev.map((a) => a.id === assignmentId ? { ...a, status: original.status } : a))
      addToast('Failed to update status. Please try again.', 'error')
    } finally {
      setUpdatingIds((prev) => { const n = new Set(prev); n.delete(assignmentId); return n })
    }
  }, [assignments, addToast])

  const handleMarkStarted = useCallback((id) => handleStatusChange(id, 'in_progress'), [handleStatusChange])
  const handleMarkDone    = useCallback((id) => handleStatusChange(id, 'submitted'),   [handleStatusChange])

  return {
    assignments,
    setAssignments,
    loading,
    error,
    updatingIds,
    exitingIds,
    lastSyncTime,
    setLastSyncTime,
    fetchAssignments,
    fetchLastSync,
    handleStatusChange,
    handleMarkStarted,
    handleMarkDone,
  }
}
