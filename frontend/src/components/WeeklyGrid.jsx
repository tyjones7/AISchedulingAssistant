import { useState, useEffect, useRef } from 'react'
import { authFetch, API_BASE } from '../lib/api'
import { downloadTimeBlocksICS } from '../utils/calendar'
import './WeeklyGrid.css'

const GRID_START_HOUR = 7   // 7 am
const GRID_END_HOUR   = 22  // 10 pm
const GRID_START_MIN  = GRID_START_HOUR * 60
const SLOT_HEIGHT     = 48  // px per 30-min slot
const SLOT_MIN        = 30
const SNAP_MIN        = 15  // drag/resize snap resolution

// Each course gets a dark shade (class time) and light shade (study/homework)
export const PALETTE = [ // eslint-disable-line react-refresh/only-export-components
  { dark: '#6366f1', light: '#eef2ff', text: '#3730a3' },
  { dark: '#0ea5e9', light: '#e0f2fe', text: '#0369a1' },
  { dark: '#10b981', light: '#d1fae5', text: '#065f46' },
  { dark: '#f59e0b', light: '#fef3c7', text: '#92400e' },
  { dark: '#ef4444', light: '#fee2e2', text: '#991b1b' },
  { dark: '#8b5cf6', light: '#ede9fe', text: '#5b21b6' },
  { dark: '#ec4899', light: '#fce7f3', text: '#9d174d' },
  { dark: '#14b8a6', light: '#ccfbf1', text: '#134e4a' },
  { dark: '#f97316', light: '#ffedd5', text: '#9a3412' },
  { dark: '#84cc16', light: '#f7fee7', text: '#3f6212' },
]

export function buildCourseColorMap(courseNames, courseColorPrefs = {}) { // eslint-disable-line react-refresh/only-export-components
  const sorted = [...new Set(courseNames.filter(Boolean))].sort()
  const colorMap = {}
  const usedIndices = new Set()
  for (const name of sorted) {
    const idx = courseColorPrefs[name]
    if (idx !== undefined) {
      colorMap[name] = PALETTE[Number(idx) % PALETTE.length]
      usedIndices.add(Number(idx) % PALETTE.length)
    }
  }
  let nextIdx = 0
  for (const name of sorted) {
    if (colorMap[name]) continue
    while (usedIndices.has(nextIdx % PALETTE.length)) nextIdx++
    colorMap[name] = PALETTE[nextIdx % PALETTE.length]
    usedIndices.add(nextIdx % PALETTE.length)
    nextIdx++
  }
  return colorMap
}

function getMtDateStr(d) {
  const p = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Denver', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(d)
  return `${p.find(x => x.type === 'year').value}-${p.find(x => x.type === 'month').value}-${p.find(x => x.type === 'day').value}`
}

function getMtHourMin(isoStr) {
  const p = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Denver', hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(new Date(isoStr))
  const h = parseInt(p.find(x => x.type === 'hour').value) % 24
  const m = parseInt(p.find(x => x.type === 'minute').value)
  return h * 60 + m
}

function getMtOffsetStr() {
  const s = new Date().toLocaleString('en-US', { timeZone: 'America/Denver', timeZoneName: 'shortOffset' })
  const match = s.match(/GMT([+-])(\d+)/)
  if (match) return `${match[1]}${match[2].padStart(2, '0')}:00`
  return '-07:00'
}

function blockTop(isoStr) {
  return Math.max(0, (getMtHourMin(isoStr) - GRID_START_MIN) / SLOT_MIN * SLOT_HEIGHT)
}

function blockHeight(startIso, endIso) {
  const dur = (new Date(endIso) - new Date(startIso)) / 60000
  return Math.max(SLOT_HEIGHT / 2, dur / SLOT_MIN * SLOT_HEIGHT)
}

function blockHeightFromMin(durMin) {
  return Math.max(SLOT_HEIGHT / 2, durMin / SLOT_MIN * SLOT_HEIGHT)
}

function parseHHMM(t) {
  const [h, m] = t.split(':').map(Number)
  return h * 60 + m
}

function classTop(startStr) {
  return Math.max(0, (parseHHMM(startStr) - GRID_START_MIN) / SLOT_MIN * SLOT_HEIGHT)
}

function classHeight(startStr, endStr) {
  const [sh, sm] = startStr.split(':').map(Number)
  const [eh, em] = endStr.split(':').map(Number)
  return Math.max(24, ((eh * 60 + em) - (sh * 60 + sm)) / SLOT_MIN * SLOT_HEIGHT)
}

function formatTime(isoStr) {
  return new Date(isoStr).toLocaleString('en-US', {
    timeZone: 'America/Denver', hour: 'numeric', minute: '2-digit', hour12: true,
  })
}

function minToTimeStr(totalMin) {
  const h = Math.floor(totalMin / 60)
  const m = totalMin % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

// Assign non-overlapping columns to blocks that share the same time slot.
// Returns [{block, col, totalCols}, ...] so each block can be sized/offset correctly.
function computeLayout(blocks) {
  const sorted = [...blocks].sort((a, b) => getMtHourMin(a.start_time) - getMtHourMin(b.start_time))
  const columns = [] // endMin of last block placed in each column
  const layout = []
  for (const block of sorted) {
    const startMin = getMtHourMin(block.start_time)
    const endMin = getMtHourMin(block.end_time)
    let col = columns.findIndex(colEnd => colEnd <= startMin)
    if (col === -1) { col = columns.length; columns.push(endMin) }
    else columns[col] = endMin
    layout.push({ block, col })
  }
  const totalCols = Math.max(1, columns.length)
  return layout.map(item => ({ ...item, totalCols }))
}

function getWeekStart(d) {
  const dowStr = d.toLocaleDateString('en-US', { timeZone: 'America/Denver', weekday: 'short' })
  const dowIndex = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].indexOf(dowStr)
  const daysBack = dowIndex === 0 ? 6 : dowIndex - 1
  const mtStr = getMtDateStr(d)
  const [y, mo, dy] = mtStr.split('-').map(Number)
  return new Date(Date.UTC(y, mo - 1, dy - daysBack, 12, 0, 0))
}

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
const TOTAL_SLOTS = (GRID_END_HOUR - GRID_START_HOUR) * 2
const GRID_HEIGHT = TOTAL_SLOTS * SLOT_HEIGHT
const PAD = n => String(n).padStart(2, '0')

const DURATION_OPTIONS = [15, 20, 30, 45, 60, 75, 90, 120]

function getMtCurrentMin() {
  const p = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Denver', hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(new Date())
  const h = parseInt(p.find(x => x.type === 'hour').value) % 24
  const m = parseInt(p.find(x => x.type === 'minute').value)
  return h * 60 + m
}

export default function WeeklyGrid({ preferences, addToast, onOpenChat, refreshKey = 0 }) {
  const [dragOverDay, setDragOverDay] = useState(null)   // dayDateStr of the column being dragged over
  const [blocks, setBlocks] = useState([])
  const [externalEvents, setExternalEvents] = useState([])
  const [lsClassEvents, setLsClassEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [approved, setApproved] = useState(false)
  const [approving, setApproving] = useState(false)
  const [weekStart, setWeekStart] = useState(() => getWeekStart(new Date()))
  const [draggedBlockId, setDraggedBlockId] = useState(null)
  const [exporting, setExporting] = useState(false)

  // Current time indicator (updates every minute)
  const [currentTimeMin, setCurrentTimeMin] = useState(getMtCurrentMin)
  useEffect(() => {
    const iv = setInterval(() => setCurrentTimeMin(getMtCurrentMin()), 60000)
    return () => clearInterval(iv)
  }, [])

  // Resize state
  const resizeRef = useRef(null)        // {blockId, dayDateStr, origEndMin, startY}
  const blocksRef = useRef(blocks)
  const [resizePreview, setResizePreview] = useState(null) // {blockId, endMin}

  // Click-to-edit popover
  const [editingBlock, setEditingBlock] = useState(null) // {id, dayDateStr, startMin, durMin, label}
  const [editStartTime, setEditStartTime] = useState('09:00')
  const [editDurMin, setEditDurMin] = useState(60)
  const [editSaving, setEditSaving] = useState(false)
  const [editPopoverPos, setEditPopoverPos] = useState({ x: 200, y: 200 })
  const editPopoverRef = useRef(null)

  useEffect(() => { blocksRef.current = blocks }, [blocks])

  const weeklySchedule = preferences?.weekly_schedule || []
  const courseColorPrefs = preferences?.course_colors || {}

  const courseColorMap = buildCourseColorMap(
    [
      ...blocks.map(b => b.assignments?.course_name),
      ...weeklySchedule.map(b => b.label),
      ...lsClassEvents.map(e => e.course_name),
    ],
    courseColorPrefs
  )

  const getCourseColor = (name) => courseColorMap[name] || PALETTE[0]

  // Global pointer handlers for resize
  useEffect(() => {
    const onMove = (e) => {
      if (!resizeRef.current) return
      const { origEndMin, startY, blockId } = resizeRef.current
      const deltaY = e.clientY - startY
      const rawMin = origEndMin + (deltaY / (SLOT_HEIGHT / SLOT_MIN))
      const snapped = Math.round(rawMin / SNAP_MIN) * SNAP_MIN
      setResizePreview({ blockId, endMin: snapped })
    }
    const onUp = async () => {
      if (!resizeRef.current) return
      const { blockId, dayDateStr } = resizeRef.current
      resizeRef.current = null
      setResizePreview(prev => {
        if (!prev || prev.blockId !== blockId) return null
        const newEndMin = prev.endMin
        const block = blocksRef.current.find(b => b.id === blockId)
        if (!block) return null
        const startMin = getMtHourMin(block.start_time)
        const clampedEnd = Math.max(startMin + SNAP_MIN, Math.min(GRID_END_HOUR * 60, newEndMin))
        const off = getMtOffsetStr()
        const newEnd = `${dayDateStr}T${PAD(Math.floor(clampedEnd / 60))}:${PAD(clampedEnd % 60)}:00${off}`
        authFetch(`${API_BASE}/time-blocks/${blockId}`, {
          method: 'PATCH',
          body: JSON.stringify({ end_time: newEnd }),
        }).then(res => {
          if (res.ok) {
            res.json().then(data => {
              setBlocks(bks => bks.map(b => b.id === blockId ? { ...b, ...data.block } : b))
            })
          } else {
            addToast('Failed to resize block', 'error')
          }
        }).catch(() => addToast('Failed to resize block', 'error'))
        return null
      })
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [addToast])

  // Close edit popover on outside click
  useEffect(() => {
    if (!editingBlock) return
    const onMouseDown = (e) => {
      if (editPopoverRef.current && !editPopoverRef.current.contains(e.target)) {
        setEditingBlock(null)
      }
    }
    const onKey = (e) => { if (e.key === 'Escape') setEditingBlock(null) }
    document.addEventListener('mousedown', onMouseDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onMouseDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [editingBlock])

  useEffect(() => {
    fetchWeek()
  }, [weekStart, refreshKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const fetchWeek = async () => {
    setLoading(true)
    const ws = getMtDateStr(weekStart)
    try {
      const [schedRes, extRes, lsRes] = await Promise.all([
        authFetch(`${API_BASE}/schedule/week?week_start=${ws}`),
        authFetch(`${API_BASE}/external-calendars/events?week_start=${ws}`),
        authFetch(`${API_BASE}/ls-feeds/class-events?week_start=${ws}`),
      ])
      if (schedRes.ok) {
        const data = await schedRes.json()
        setBlocks(data.blocks || [])
      }
      if (extRes.ok) {
        const extData = await extRes.json()
        setExternalEvents(extData.events || [])
      }
      if (lsRes.ok) {
        const lsData = await lsRes.json()
        setLsClassEvents(lsData.events || [])
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const handleGenerate = async () => {
    setGenerating(true)
    setApproved(false)
    try {
      const res = await authFetch(`${API_BASE}/schedule/generate`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        if (data.total_blocks > 0) {
          addToast(`Generated ${data.total_blocks} study block${data.total_blocks !== 1 ? 's' : ''}`, 'success')
        } else {
          addToast('No assignments due this week — nothing to schedule.', 'info')
        }
        // Refetch full week from DB (includes past blocks that weren't deleted)
        await fetchWeek()
      } else {
        addToast('Failed to generate schedule', 'error')
      }
    } catch {
      addToast('Failed to generate schedule', 'error')
    } finally {
      setGenerating(false)
    }
  }

  const handleApprove = async () => {
    setApproving(true)
    try {
      const res = await authFetch(`${API_BASE}/schedule/approve`, { method: 'POST' })
      if (res.ok) {
        setApproved(true)
        addToast('Plan approved!', 'success')
      }
    } catch {
      addToast('Failed to approve plan', 'error')
    } finally {
      setApproving(false)
    }
  }

  // ── Drag (HTML5) — 15-min snap ──────────────────────────────────────────────
  const handleDragStart = (e, blockId) => {
    setDraggedBlockId(blockId)
    e.dataTransfer.effectAllowed = 'move'
  }

  const handleDragEnter = (dayDateStr) => {
    if (draggedBlockId) setDragOverDay(dayDateStr)
  }

  const handleDragLeave = (e) => {
    // Only clear if leaving the column entirely (not entering a child element)
    if (!e.currentTarget.contains(e.relatedTarget)) setDragOverDay(null)
  }

  const handleDrop = async (e, dayDateStr, pixelY) => {
    e.preventDefault()
    if (!draggedBlockId) return
    const block = blocks.find(b => b.id === draggedBlockId)
    if (!block) return

    const durMin = (new Date(block.end_time) - new Date(block.start_time)) / 60000
    // Snap to SNAP_MIN intervals
    const rawStartMin = GRID_START_MIN + pixelY / SLOT_HEIGHT * SLOT_MIN
    const newStartMin = Math.round(rawStartMin / SNAP_MIN) * SNAP_MIN
    const newEndMin   = newStartMin + durMin

    // Conflict check vs class blocks
    const hasConflict = classBlocksForDay(dayDateStr).some(cb => {
      const [sh, sm] = cb.start.split(':').map(Number)
      const [eh, em] = cb.end.split(':').map(Number)
      return newStartMin < (eh * 60 + em) && newEndMin > (sh * 60 + sm)
    })
    if (hasConflict) {
      addToast('Cannot place block during class time', 'error')
      setDraggedBlockId(null)
      return
    }

    const off = getMtOffsetStr()
    const newStart = `${dayDateStr}T${PAD(Math.floor(newStartMin / 60))}:${PAD(newStartMin % 60)}:00${off}`
    const newEnd   = `${dayDateStr}T${PAD(Math.floor(newEndMin / 60) % 24)}:${PAD(newEndMin % 60)}:00${off}`

    try {
      const res = await authFetch(`${API_BASE}/time-blocks/${draggedBlockId}`, {
        method: 'PATCH',
        body: JSON.stringify({ start_time: newStart, end_time: newEnd }),
      })
      if (res.ok) {
        const data = await res.json()
        setBlocks(prev => prev.map(b =>
          b.id === draggedBlockId ? { ...b, ...data.block, date: dayDateStr } : b
        ))
        setApproved(false)
      } else {
        addToast('Failed to move block', 'error')
      }
    } catch {
      addToast('Failed to move block', 'error')
    }
    setDraggedBlockId(null)
    setDragOverDay(null)
  }

  const handleDeleteBlock = async (blockId) => {
    try {
      await authFetch(`${API_BASE}/time-blocks/${blockId}`, { method: 'DELETE' })
      setBlocks(prev => prev.filter(b => b.id !== blockId))
    } catch {
      addToast('Failed to remove block', 'error')
    }
  }

  // ── Resize handle ─────────────────────────────────────────────────────────
  const handleResizeStart = (e, blockId, dayDateStr) => {
    e.stopPropagation()
    e.preventDefault()
    const block = blocksRef.current.find(b => b.id === blockId)
    if (!block) return
    const origEndMin = getMtHourMin(block.end_time)
    resizeRef.current = { blockId, dayDateStr, origEndMin, startY: e.clientY }
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  // ── Click-to-edit ─────────────────────────────────────────────────────────
  const handleBlockClick = (e, block, dayDateStr) => {
    // Don't open edit if user is dragging or clicking the × button
    if (draggedBlockId) return
    if (e.target.closest('.wg-block-remove') || e.target.closest('.wg-block-resize')) return
    e.stopPropagation()

    const startMin = getMtHourMin(block.start_time)
    const endMin   = getMtHourMin(block.end_time)
    const durMin   = endMin - startMin

    setEditStartTime(minToTimeStr(startMin))
    setEditDurMin(durMin)
    setEditingBlock({ id: block.id, dayDateStr, startMin, durMin, label: block.label || block.assignments?.title || 'Study' })

    // Position popover near click, keeping in viewport
    const x = Math.min(e.clientX + 12, window.innerWidth - 260)
    const y = Math.min(Math.max(8, e.clientY - 10), window.innerHeight - 280)
    setEditPopoverPos({ x, y })
  }

  const handleEditSave = async () => {
    if (!editingBlock || editSaving) return
    setEditSaving(true)
    const { id, dayDateStr } = editingBlock

    const [hStr, mStr] = editStartTime.split(':')
    const startMin = parseInt(hStr) * 60 + parseInt(mStr)
    const endMin   = startMin + editDurMin

    const off = getMtOffsetStr()
    const newStart = `${dayDateStr}T${PAD(Math.floor(startMin / 60))}:${PAD(startMin % 60)}:00${off}`
    const newEnd   = `${dayDateStr}T${PAD(Math.floor(endMin / 60) % 24)}:${PAD(endMin % 60)}:00${off}`

    try {
      const res = await authFetch(`${API_BASE}/time-blocks/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ start_time: newStart, end_time: newEnd }),
      })
      if (res.ok) {
        const data = await res.json()
        setBlocks(prev => prev.map(b => b.id === id ? { ...b, ...data.block, date: dayDateStr } : b))
        setEditingBlock(null)
        setApproved(false)
      } else {
        addToast('Failed to update block', 'error')
      }
    } catch {
      addToast('Failed to update block', 'error')
    } finally {
      setEditSaving(false)
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  const classBlocksForDay = (dayDateStr) => {
    const dayAbbrev = new Date(dayDateStr + 'T12:00:00').toLocaleDateString('en-US', {
      timeZone: 'America/Denver', weekday: 'short',
    })
    return (weeklySchedule || []).filter(b =>
      b.day === dayAbbrev || (Array.isArray(b.days) && b.days.includes(dayAbbrev))
    )
  }

  const timeBlocksForDay = (dayDateStr) =>
    blocks.filter(b => b.date === dayDateStr)

  const externalEventsForDay = (dayDateStr) =>
    externalEvents.filter(ev => getMtDateStr(new Date(ev.start)) === dayDateStr)

  const lsClassEventsForDay = (dayDateStr) =>
    lsClassEvents.filter(ev => ev.date === dayDateStr)

  const prevWeek = () => {
    const d = new Date(weekStart)
    d.setUTCDate(d.getUTCDate() - 7)
    setWeekStart(d)
  }

  const nextWeek = () => {
    const d = new Date(weekStart)
    d.setUTCDate(d.getUTCDate() + 7)
    setWeekStart(d)
  }

  const weekDates = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart)
    d.setUTCDate(d.getUTCDate() + i)
    return d
  })

  const weekEnd = new Date(weekStart)
  weekEnd.setUTCDate(weekEnd.getUTCDate() + 6)
  const weekStartStr = getMtDateStr(weekStart)
  const weekEndStr = getMtDateStr(weekEnd)
  const weekLabel = `${MONTH_NAMES[parseInt(weekStartStr.slice(5,7),10)-1]} ${parseInt(weekStartStr.slice(-2),10)} – ${MONTH_NAMES[parseInt(weekEndStr.slice(5,7),10)-1]} ${parseInt(weekEndStr.slice(-2),10)}`

  const timeLabels = Array.from({ length: GRID_END_HOUR - GRID_START_HOUR }, (_, i) => {
    const h = GRID_START_HOUR + i
    return h < 12 ? `${h}am` : h === 12 ? '12pm' : `${h - 12}pm`
  })

  const todayStr = getMtDateStr(new Date())

  return (
    <div className="wg-wrap">
      {/* Controls */}
      <div className="wg-controls">
        <div className="wg-nav">
          <button className="wg-nav-btn" onClick={prevWeek} aria-label="Previous week">‹</button>
          <span className="wg-week-label">{weekLabel}</span>
          <button className="wg-nav-btn" onClick={nextWeek} aria-label="Next week">›</button>
        </div>
        <div className="wg-actions">
          <button
            className="wg-btn wg-btn--generate"
            onClick={handleGenerate}
            disabled={generating}
          >
            {generating ? 'Generating…' : 'Generate Plan'}
          </button>
          {onOpenChat && (
            <button
              className="wg-btn wg-btn--chat"
              onClick={() => onOpenChat(blocks.length > 0
                ? 'I want to adjust my schedule this week. Can you help me optimize it?'
                : 'Help me build a study plan for this week. Ask me a few questions so we can make it work for me.'
              )}
              title="Plan or adjust your schedule with AI"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                width="14" height="14" style={{flexShrink: 0}}>
                <path d="M12 3l1.88 5.76a1 1 0 0 0 .95.69h6.06l-4.9 3.56a1 1 0 0 0-.36 1.12L17.5 20l-4.9-3.56a1 1 0 0 0-1.18 0L6.5 20l1.87-5.87a1 1 0 0 0-.36-1.12L3.11 9.45h6.06a1 1 0 0 0 .95-.69L12 3z" />
              </svg>
              {blocks.length > 0 ? 'Refine with AI' : 'Plan with AI'}
            </button>
          )}
          {blocks.length > 0 && (
            <>
              <button
                className={`wg-btn ${approved ? 'wg-btn--approved' : 'wg-btn--approve'}`}
                onClick={handleApprove}
                disabled={approving || approved}
              >
                {approved ? '✓ Approved' : approving ? 'Approving…' : 'Approve'}
              </button>
              <button
                className="wg-btn wg-btn--export"
                onClick={async () => {
                  if (exporting) return
                  setExporting(true)
                  try {
                    const ws = getMtDateStr(weekStart)
                    const res = await authFetch(`${API_BASE}/schedule/week?week_start=${ws}`)
                    if (res.ok) {
                      const data = await res.json()
                      if ((data.blocks || []).length === 0) {
                        addToast('No blocks to export', 'error')
                      } else {
                        downloadTimeBlocksICS(data.blocks, data.week_start)
                      }
                    } else {
                      addToast('Export failed', 'error')
                    }
                  } catch {
                    addToast('Export failed', 'error')
                  } finally {
                    setExporting(false)
                  }
                }}
                disabled={exporting}
                title="Export week to .ics"
              >
                {exporting ? 'Exporting…' : '↓ .ics'}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Scrollable grid */}
      <div className="wg-scroll">
        {loading ? (
          <div className="wg-loading">Loading schedule…</div>
        ) : (
          <div className="wg-grid">
            {/* Time labels column */}
            <div className="wg-time-col">
              <div className="wg-day-header" />
              <div className="wg-day-body" style={{ height: GRID_HEIGHT }}>
                {timeLabels.map((label, i) => (
                  <div
                    key={i}
                    className="wg-time-label"
                    style={{ top: i * 2 * SLOT_HEIGHT }}
                  >
                    {label}
                  </div>
                ))}
              </div>
            </div>

            {/* Day columns */}
            {weekDates.map((dayDate, di) => {
              const dayDateStr = getMtDateStr(dayDate)
              const isToday = dayDateStr === todayStr
              const isBeforeToday = dayDateStr < todayStr
              const isBlockPast = (endTimeStr) => isBeforeToday || (isToday && getMtHourMin(endTimeStr) <= currentTimeMin)
              const clsBlocks = classBlocksForDay(dayDateStr)
              const dayBlocks = timeBlocksForDay(dayDateStr)
              const extEvents = externalEventsForDay(dayDateStr)
              const lsClasses = lsClassEventsForDay(dayDateStr)

              return (
                <div key={dayDateStr} className={`wg-day-col ${isToday ? 'is-today' : ''}`}>
                  <div className="wg-day-header">
                    <span className="wg-day-name">{DAY_LABELS[di]}</span>
                    <span className={`wg-day-num ${isToday ? 'is-today-num' : ''}`}>
                      {parseInt(dayDateStr.slice(-2), 10)}
                    </span>
                  </div>

                  <div
                    className={`wg-day-body ${dragOverDay === dayDateStr && draggedBlockId ? 'wg-drop-target' : ''}`}
                    style={{ height: GRID_HEIGHT }}
                    onDragOver={e => e.preventDefault()}
                    onDragEnter={() => handleDragEnter(dayDateStr)}
                    onDragLeave={handleDragLeave}
                    onDrop={e => {
                      const rect = e.currentTarget.getBoundingClientRect()
                      const pixelY = Math.max(0, e.clientY - rect.top)
                      handleDrop(e, dayDateStr, pixelY)
                    }}
                  >

                    {/* Current time indicator — only in today's column */}
                    {dayDateStr === todayStr && currentTimeMin >= GRID_START_MIN && currentTimeMin <= GRID_END_HOUR * 60 && (
                      <div
                        className="wg-now-line"
                        style={{ top: Math.max(0, (currentTimeMin - GRID_START_MIN) / SLOT_MIN * SLOT_HEIGHT) }}
                      >
                        <div className="wg-now-dot" />
                      </div>
                    )}

                    {/* Hour/half-hour lines */}
                    {Array.from({ length: TOTAL_SLOTS }).map((_, si) => (
                      <div
                        key={si}
                        className={`wg-slot ${si % 2 === 0 ? 'is-hour' : ''}`}
                        style={{ top: si * SLOT_HEIGHT, height: SLOT_HEIGHT }}
                      />
                    ))}

                    {/* Class blocks (read-only) */}
                    {clsBlocks.map((cb, ci) => {
                      const clsColor = getCourseColor(cb.label)
                      const isClsPast = isBeforeToday || (isToday && parseHHMM(cb.end) <= currentTimeMin)
                      return (
                        <div
                          key={ci}
                          className={`wg-block wg-block--class ${isClsPast ? 'wg-block--past' : ''}`}
                          style={{
                            top: classTop(cb.start),
                            height: classHeight(cb.start, cb.end),
                            background: clsColor.dark,
                            borderLeft: `3px solid ${clsColor.dark}`,
                            color: '#fff',
                          }}
                        >
                          <span className="wg-block-title">{cb.label || 'Class'}</span>
                        </div>
                      )
                    })}

                    {/* LS class session blocks */}
                    {lsClasses.map((ev, ei) => {
                      const lsColor = getCourseColor(ev.course_name)
                      return (
                        <div
                          key={`ls-${ei}`}
                          className={`wg-block wg-block--class ${isBlockPast(ev.end) ? 'wg-block--past' : ''}`}
                          style={{
                            top: blockTop(ev.start),
                            height: blockHeight(ev.start, ev.end),
                            background: lsColor.dark,
                            borderLeft: `3px solid ${lsColor.dark}`,
                            color: '#fff',
                          }}
                          title={`${ev.course_name}\n${formatTime(ev.start)} – ${formatTime(ev.end)}`}
                        >
                          <span className="wg-block-title">{ev.course_name}</span>
                        </div>
                      )
                    })}

                    {/* External calendar events */}
                    {extEvents.map((ev, ei) => (
                      <div
                        key={`ext-${ei}`}
                        className={`wg-block wg-block--external ${isBlockPast(ev.end) ? 'wg-block--past' : ''}`}
                        style={{
                          top: blockTop(ev.start),
                          height: blockHeight(ev.start, ev.end),
                        }}
                        title={`${ev.title}\n${ev.calendar_label}`}
                      >
                        <span className="wg-block-title">{ev.title}</span>
                        <span className="wg-block-course">{ev.calendar_label}</span>
                      </div>
                    ))}

                    {/* Study blocks (draggable + resizable + clickable) */}
                    {computeLayout(dayBlocks).map(({ block, col, totalCols }) => {
                      const asgn = block.assignments || {}
                      const label = block.label || asgn.title || 'Study'

                      // ── Study block ───────────────────────────────────────
                      const color = getCourseColor(asgn.course_name)
                      const isDragging = draggedBlockId === block.id
                      const isCompleted = block.status === 'completed'
                      const isPast = isBlockPast(block.end_time)
                      const isResizing = resizePreview?.blockId === block.id
                      const displayEndMin = isResizing ? resizePreview.endMin : null
                      const startMin = getMtHourMin(block.start_time)
                      const origEndMin = getMtHourMin(block.end_time)
                      const durMin = (displayEndMin ?? origEndMin) - startMin
                      const colWidth = `${100 / totalCols}%`
                      const colLeft = `${(col / totalCols) * 100}%`

                      return (
                        <div
                          key={block.id}
                          className={`wg-block wg-block--task ${isCompleted ? 'is-done' : ''} ${isDragging ? 'is-dragging' : ''} ${isResizing ? 'is-resizing' : ''} ${isPast ? 'wg-block--past' : ''}`}
                          style={{
                            top: blockTop(block.start_time),
                            height: blockHeightFromMin(Math.max(15, durMin)),
                            width: colWidth,
                            left: colLeft,
                            background: color.light,
                            borderLeft: `3px solid ${color.dark}`,
                            color: color.text,
                            opacity: isDragging ? 0.4 : 1,
                          }}
                          draggable={!isCompleted && !isPast && !resizeRef.current}
                          onDragStart={e => handleDragStart(e, block.id)}
                          onDragEnd={() => setDraggedBlockId(null)}
                          onClick={e => handleBlockClick(e, block, dayDateStr)}
                          title={`${label}\n${formatTime(block.start_time)} – ${formatTime(block.end_time)}\nClick to edit • Drag to move • Drag bottom to resize`}
                        >
                          <span className="wg-block-title">{label}</span>
                          <span className="wg-block-course">{asgn.course_name}</span>
                          <button
                            className="wg-block-remove"
                            onClick={e => { e.stopPropagation(); handleDeleteBlock(block.id) }}
                            title="Remove block"
                          >×</button>
                          {!isCompleted && (
                            <div
                              className="wg-block-resize"
                              onPointerDown={e => handleResizeStart(e, block.id, dayDateStr)}
                              title="Drag to resize"
                            />
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Empty state */}
      {!loading && blocks.length === 0 && (
        <div className="wg-empty">
          <p>{weekStartStr > todayStr ? 'No blocks scheduled for this week yet.' : 'No study blocks scheduled yet.'}</p>
          <p className="wg-empty-hint">
            Click <strong>Generate Plan</strong> for an AI-powered schedule, or{' '}
            {onOpenChat && (
              <button className="wg-empty-chat-link" onClick={() => onOpenChat('Help me build a study plan for this week. Ask me a few questions so we can make it work for me.')}>
                chat with AI
              </button>
            )}
            {!onOpenChat && 'chat with AI'} to plan collaboratively.
          </p>
        </div>
      )}

      {/* Click-to-edit popover */}
      {editingBlock && (
        <div
          ref={editPopoverRef}
          className="wg-edit-popover"
          style={{ left: editPopoverPos.x, top: editPopoverPos.y }}
        >
          <div className="wg-edit-title">{editingBlock.label}</div>
          <div className="wg-edit-field">
            <label className="wg-edit-label">Start time</label>
            <input
              type="time"
              className="wg-edit-input"
              value={editStartTime}
              onChange={e => setEditStartTime(e.target.value)}
              step={SNAP_MIN * 60}
            />
          </div>
          <div className="wg-edit-field">
            <label className="wg-edit-label">Duration</label>
            <select
              className="wg-edit-input"
              value={editDurMin}
              onChange={e => setEditDurMin(Number(e.target.value))}
            >
              {DURATION_OPTIONS.map(d => (
                <option key={d} value={d}>
                  {d < 60 ? `${d} min` : d === 60 ? '1 hour' : `${d / 60}h ${d % 60 ? `${d % 60}m` : ''}`}
                </option>
              ))}
              {/* Add current duration if not in options */}
              {!DURATION_OPTIONS.includes(editDurMin) && (
                <option value={editDurMin}>
                  {editDurMin < 60 ? `${editDurMin} min` : `${Math.floor(editDurMin/60)}h ${editDurMin%60 ? `${editDurMin%60}m` : ''}`}
                </option>
              )}
            </select>
          </div>
          <div className="wg-edit-actions">
            <button
              className="wg-edit-save"
              onClick={handleEditSave}
              disabled={editSaving}
            >
              {editSaving ? 'Saving…' : 'Save'}
            </button>
            <button
              className="wg-edit-cancel"
              onClick={() => setEditingBlock(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
