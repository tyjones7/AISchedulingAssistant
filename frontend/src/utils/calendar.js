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
