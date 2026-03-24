import { useState, useEffect } from 'react'
import { authFetch, API_BASE } from '../lib/api'
import { downloadTimeBlocksICS } from '../utils/calendar'
import './WeeklyGrid.css'

const GRID_START_HOUR = 7   // 7 am
const GRID_END_HOUR   = 22  // 10 pm
const GRID_START_MIN  = GRID_START_HOUR * 60
const SLOT_HEIGHT     = 48  // px per 30-min slot
const SLOT_MIN        = 30

// Each course gets a dark shade (class time) and light shade (study/homework)
const PALETTE = [
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

function getCourseColor(name) {
  if (!name) return PALETTE[0]
  const h = [...name].reduce((a, c) => a + c.charCodeAt(0), 0)
  return PALETTE[h % PALETTE.length]
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

function classTop(startStr) {
  const [h, m] = startStr.split(':').map(Number)
  return Math.max(0, (h * 60 + m - GRID_START_MIN) / SLOT_MIN * SLOT_HEIGHT)
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

function getWeekStart(d) {
  const date = new Date(d)
  const day = date.getDay()
  date.setDate(date.getDate() - (day === 0 ? 6 : day - 1))
  date.setHours(0, 0, 0, 0)
  return date
}

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
const TOTAL_SLOTS = (GRID_END_HOUR - GRID_START_HOUR) * 2
const GRID_HEIGHT = TOTAL_SLOTS * SLOT_HEIGHT

export default function WeeklyGrid({ preferences, addToast }) {
  const [blocks, setBlocks] = useState([])
  const [overbooked, setOverbooked] = useState([])
  const [externalEvents, setExternalEvents] = useState([])
  const [lsClassEvents, setLsClassEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [approved, setApproved] = useState(false)
  const [approving, setApproving] = useState(false)
  const [weekStart, setWeekStart] = useState(() => getWeekStart(new Date()))
  const [draggedBlockId, setDraggedBlockId] = useState(null)
  const [exporting, setExporting] = useState(false)

  const weeklySchedule = preferences?.weekly_schedule || []

  useEffect(() => {
    fetchWeek()
  }, [weekStart]) // eslint-disable-line react-hooks/exhaustive-deps

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
        setBlocks(data.blocks || [])
        setOverbooked(data.overbooked || [])
        addToast(`Generated ${data.total_blocks} study blocks`, 'success')
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

  const handleDragStart = (e, blockId) => {
    setDraggedBlockId(blockId)
    e.dataTransfer.effectAllowed = 'move'
  }

  const handleDrop = async (e, dayDateStr, slotIndex) => {
    e.preventDefault()
    if (!draggedBlockId) return
    const block = blocks.find(b => b.id === draggedBlockId)
    if (!block) return

    const durMin = (new Date(block.end_time) - new Date(block.start_time)) / 60000
    const newStartMin = GRID_START_MIN + slotIndex * SLOT_MIN
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

    const pad = n => String(n).padStart(2, '0')
    const off = getMtOffsetStr()
    const newStart = `${dayDateStr}T${pad(Math.floor(newStartMin / 60))}:${pad(newStartMin % 60)}:00${off}`
    const newEnd   = `${dayDateStr}T${pad(Math.floor(newEndMin / 60) % 24)}:${pad(newEndMin % 60)}:00${off}`

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
  }

  const handleDeleteBlock = async (blockId) => {
    try {
      await authFetch(`${API_BASE}/time-blocks/${blockId}`, { method: 'DELETE' })
      setBlocks(prev => prev.filter(b => b.id !== blockId))
    } catch {
      addToast('Failed to remove block', 'error')
    }
  }

  const classBlocksForDay = (dayDateStr) => {
    const dayAbbrev = new Date(dayDateStr + 'T12:00:00').toLocaleDateString('en-US', {
      timeZone: 'America/Denver', weekday: 'short',
    })
    // Support both {day: "Mon"} (singular, from Settings) and {days: ["Mon"]} (array, legacy)
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
    d.setDate(d.getDate() - 7)
    setWeekStart(d)
  }

  const nextWeek = () => {
    const d = new Date(weekStart)
    d.setDate(d.getDate() + 7)
    setWeekStart(d)
  }

  const weekDates = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart)
    d.setDate(d.getDate() + i)
    return d
  })

  const weekEnd = new Date(weekStart)
  weekEnd.setDate(weekEnd.getDate() + 6)
  const weekLabel = `${MONTH_NAMES[weekStart.getMonth()]} ${weekStart.getDate()} – ${MONTH_NAMES[weekEnd.getMonth()]} ${weekEnd.getDate()}`

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
          {blocks.length > 0 && (
            <>
              <button
                className={`wg-btn ${approved ? 'wg-btn--approved' : 'wg-btn--approve'}`}
                onClick={handleApprove}
                disabled={approving || approved}
              >
                {approved ? '✓ Plan Approved' : approving ? 'Approving…' : 'Approve Plan'}
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
                title="Export week to .ics (Google/Apple Calendar)"
              >
                {exporting ? 'Exporting…' : '↓ Export .ics'}
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
              const clsBlocks = classBlocksForDay(dayDateStr)
              const dayBlocks = timeBlocksForDay(dayDateStr)
              const extEvents = externalEventsForDay(dayDateStr)
              const lsClasses = lsClassEventsForDay(dayDateStr)

              return (
                <div key={dayDateStr} className={`wg-day-col ${isToday ? 'is-today' : ''}`}>
                  <div className="wg-day-header">
                    <span className="wg-day-name">{DAY_LABELS[di]}</span>
                    <span className={`wg-day-num ${isToday ? 'is-today-num' : ''}`}>
                      {dayDate.getDate()}
                    </span>
                  </div>

                  <div
                    className="wg-day-body"
                    style={{ height: GRID_HEIGHT }}
                    onDragOver={e => e.preventDefault()}
                    onDrop={e => {
                      const rect = e.currentTarget.getBoundingClientRect()
                      const slotIdx = Math.floor((e.clientY - rect.top) / SLOT_HEIGHT)
                      handleDrop(e, dayDateStr, Math.max(0, Math.min(slotIdx, TOTAL_SLOTS - 1)))
                    }}
                  >
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
                      return (
                        <div
                          key={ci}
                          className="wg-block wg-block--class"
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

                    {/* LS class session blocks (auto from iCal, color-coded) */}
                    {lsClasses.map((ev, ei) => {
                      const lsColor = getCourseColor(ev.course_name)
                      return (
                        <div
                          key={`ls-${ei}`}
                          className="wg-block wg-block--class"
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

                    {/* External calendar events (read-only, gray busy blocks) */}
                    {extEvents.map((ev, ei) => (
                      <div
                        key={`ext-${ei}`}
                        className="wg-block wg-block--external"
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

                    {/* Study blocks (draggable) */}
                    {dayBlocks.map(block => {
                      const asgn = block.assignments || {}
                      const color = getCourseColor(asgn.course_name)
                      const isDragging = draggedBlockId === block.id
                      const isCompleted = block.status === 'completed'
                      const label = block.label || asgn.title || 'Study'
                      return (
                        <div
                          key={block.id}
                          className={`wg-block wg-block--task ${isCompleted ? 'is-done' : ''} ${isDragging ? 'is-dragging' : ''}`}
                          style={{
                            top: blockTop(block.start_time),
                            height: blockHeight(block.start_time, block.end_time),
                            background: color.light,
                            borderLeft: `3px solid ${color.dark}`,
                            color: color.text,
                            opacity: isDragging ? 0.4 : 1,
                          }}
                          draggable={!isCompleted}
                          onDragStart={e => handleDragStart(e, block.id)}
                          onDragEnd={() => setDraggedBlockId(null)}
                          title={`${label}\n${formatTime(block.start_time)} – ${formatTime(block.end_time)}`}
                        >
                          <span className="wg-block-title">{label}</span>
                          <span className="wg-block-course">{asgn.course_name}</span>
                          <button
                            className="wg-block-remove"
                            onClick={e => { e.stopPropagation(); handleDeleteBlock(block.id) }}
                            title="Remove block"
                          >×</button>
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

      {/* Overbooked */}
      {overbooked.length > 0 && (
        <div className="wg-overbooked">
          <span className="wg-overbooked-label">
            ⚠ {overbooked.length} task{overbooked.length > 1 ? 's' : ''} couldn&apos;t fit this week:
          </span>
          <div className="wg-overbooked-tags">
            {overbooked.map(t => (
              <span key={t.id} className="wg-overbooked-tag">{t.title}</span>
            ))}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!loading && blocks.length === 0 && overbooked.length === 0 && (
        <div className="wg-empty">
          <p>No study blocks scheduled yet.</p>
          <p className="wg-empty-hint">
            Set time estimates on your assignments, then click <strong>Generate Plan</strong>.
          </p>
        </div>
      )}
    </div>
  )
}
