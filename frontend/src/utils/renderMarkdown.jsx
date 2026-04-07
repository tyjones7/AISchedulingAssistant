/**
 * Lightweight markdown-to-React renderer.
 * Handles: **bold**, *italic*, `inline code`, bullet lists (- / •), numbered lists.
 * Safe — no dangerouslySetInnerHTML.
 */

// Parse inline styles within a line of text
export function parseInline(text) {
  const parts = []
  const re = /(\*\*(.+?)\*\*|\*([^*\s][^*]*[^*\s]|[^*\s])\*|`([^`]+)`)/g
  let last = 0
  let m
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    if (m[2] !== undefined) parts.push(<strong key={m.index}>{m[2]}</strong>)
    else if (m[3] !== undefined) parts.push(<em key={m.index}>{m[3]}</em>)
    else if (m[4] !== undefined) parts.push(<code key={m.index} className="ai-inline-code">{m[4]}</code>)
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

// Convert a markdown string to an array of React elements
export function renderMarkdown(text) {
  if (!text) return null
  const lines = text.split('\n')
  const elements = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Blank line — skip
    if (line.trim() === '') { i++; continue }

    // Bullet list item: - or • or *
    if (/^[\s]*[-•*]\s/.test(line)) {
      const items = []
      while (i < lines.length && /^[\s]*[-•*]\s/.test(lines[i])) {
        items.push(<li key={i}>{parseInline(lines[i].replace(/^[\s]*[-•*]\s/, ''))}</li>)
        i++
      }
      elements.push(<ul key={`ul-${i}`} className="ai-md-list">{items}</ul>)
      continue
    }

    // Numbered list item: 1. 2. etc.
    if (/^[\s]*\d+\.\s/.test(line)) {
      const items = []
      while (i < lines.length && /^[\s]*\d+\.\s/.test(lines[i])) {
        items.push(<li key={i}>{parseInline(lines[i].replace(/^[\s]*\d+\.\s/, ''))}</li>)
        i++
      }
      elements.push(<ol key={`ol-${i}`} className="ai-md-list">{items}</ol>)
      continue
    }

    // Regular paragraph — group consecutive non-blank non-list lines
    const paraLines = []
    while (i < lines.length && lines[i].trim() !== '' && !/^[\s]*[-•*\d]/.test(lines[i])) {
      paraLines.push(lines[i])
      i++
    }
    if (paraLines.length > 0) {
      elements.push(<p key={`p-${i}`} className="ai-md-para">{parseInline(paraLines.join(' '))}</p>)
    }
  }

  return elements.length > 0 ? elements : null
}
