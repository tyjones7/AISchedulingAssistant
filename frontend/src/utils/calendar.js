/**
 * Calendar export utilities — generates ICS files and Google Calendar deep links
 * from assignment data.
 */

function buildCalendarEvent(assignment) {
  let start, end, title

  if (assignment.planned_start && assignment.planned_end) {
    start = new Date(assignment.planned_start)
    end = new Date(assignment.planned_end)
    title = `Study: ${assignment.title}`
  } else {
    const dueDate = assignment.due_date ? new Date(assignment.due_date) : new Date()
    const durationMs = (assignment.estimated_minutes || 60) * 60 * 1000
    end = dueDate
    start = new Date(dueDate.getTime() - durationMs)
    title = `Due: ${assignment.title}`
  }

  const descriptionParts = []
  if (assignment.course_name) descriptionParts.push(`Course: ${assignment.course_name}`)
  if (assignment.due_date) {
    descriptionParts.push(`Due: ${new Date(assignment.due_date).toLocaleString('en-US', { timeZone: 'America/Denver' })}`)
  }
  if (assignment.estimated_minutes) descriptionParts.push(`Estimated time: ${assignment.estimated_minutes} min`)
  if (assignment.description) descriptionParts.push(`\n${assignment.description}`)
  if (assignment.link) descriptionParts.push(`\nLink: ${assignment.link}`)

  return { title, start, end, description: descriptionParts.join('\n') }
}

function formatICSDate(date) {
  return date.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '')
}

function generateUID() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}@aischeduler`
}

export function downloadICS(assignment) {
  const event = buildCalendarEvent(assignment)

  const icsContent = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//AI Scheduling Assistant//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'BEGIN:VEVENT',
    `UID:${generateUID()}`,
    `DTSTART:${formatICSDate(event.start)}`,
    `DTEND:${formatICSDate(event.end)}`,
    `SUMMARY:${event.title}`,
    `DESCRIPTION:${event.description.replace(/\n/g, '\\n')}`,
    `DTSTAMP:${formatICSDate(new Date())}`,
    'END:VEVENT',
    'END:VCALENDAR',
  ].join('\r\n')

  const blob = new Blob([icsContent], { type: 'text/calendar;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${assignment.title.replace(/[^a-zA-Z0-9 ]/g, '').trim()}.ics`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function formatGoogleDate(date) {
  return date.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '')
}

/**
 * Export a full week of time blocks as a single ICS file.
 * Each block becomes its own calendar event with the correct start/end time.
 *
 * @param {Array} blocks  - time_blocks from GET /schedule/week
 * @param {string} weekStart - "YYYY-MM-DD" label for the filename
 */
export function downloadTimeBlocksICS(blocks, weekStart) {
  const events = blocks
    .filter(b => b.status !== 'skipped')
    .map(block => {
      const start = new Date(block.start_time)
      const end   = new Date(block.end_time)
      const asgn  = block.assignments || {}
      const title = block.label || asgn.title || 'Study block'
      const course = asgn.course_name || ''
      const descParts = []
      if (course) descParts.push(`Course: ${course}`)
      if (asgn.estimated_minutes) descParts.push(`Estimated: ${asgn.estimated_minutes} min`)

      return [
        'BEGIN:VEVENT',
        `UID:${block.id || generateUID()}@campusai`,
        `DTSTART:${formatICSDate(start)}`,
        `DTEND:${formatICSDate(end)}`,
        `SUMMARY:${title}`,
        descParts.length ? `DESCRIPTION:${descParts.join('\\n')}` : null,
        `DTSTAMP:${formatICSDate(new Date())}`,
        'END:VEVENT',
      ].filter(Boolean).join('\r\n')
    })

  const icsContent = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//CampusAI//Study Schedule//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'X-WR-CALNAME:CampusAI Study Plan',
    ...events,
    'END:VCALENDAR',
  ].join('\r\n')

  const label = weekStart ? `week-of-${weekStart}` : 'study-plan'
  const blob = new Blob([icsContent], { type: 'text/calendar;charset=utf-8' })
  const url  = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `campusai-${label}.ics`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

export function downloadMultiICS(assignments) {
  const events = assignments.map((assignment) => {
    const event = buildCalendarEvent(assignment)
    return [
      'BEGIN:VEVENT',
      `UID:${generateUID()}`,
      `DTSTART:${formatICSDate(event.start)}`,
      `DTEND:${formatICSDate(event.end)}`,
      `SUMMARY:${event.title}`,
      `DESCRIPTION:${event.description.replace(/\n/g, '\\n')}`,
      `DTSTAMP:${formatICSDate(new Date())}`,
      'END:VEVENT',
    ].join('\r\n')
  })

  const icsContent = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//AI Scheduling Assistant//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    ...events,
    'END:VCALENDAR',
  ].join('\r\n')

  const blob = new Blob([icsContent], { type: 'text/calendar;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'campusai-study-plan.ics'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

export function getGoogleCalendarUrl(assignment) {
  const event = buildCalendarEvent(assignment)

  const params = new URLSearchParams({
    action: 'TEMPLATE',
    text: event.title,
    dates: `${formatGoogleDate(event.start)}/${formatGoogleDate(event.end)}`,
    details: event.description,
  })

  return `https://calendar.google.com/calendar/render?${params.toString()}`
}
