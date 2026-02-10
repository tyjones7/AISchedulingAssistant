// API Configuration
// The backend runs on port 8000, frontend on 5173

export const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Helper for making API requests with error handling
export async function apiFetch(path, options = {}) {
  const url = `${API_BASE}${path}`
  console.log(`[API] ${options.method || 'GET'} ${url}`)

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    })

    if (!response.ok) {
      let errorMessage = `${response.status} ${response.statusText}`
      try {
        const data = await response.json()
        errorMessage = data.detail || errorMessage
      } catch {
        // Response wasn't JSON
      }
      console.error(`[API] Error: ${errorMessage}`, url)
      throw new Error(errorMessage)
    }

    return response.json()
  } catch (err) {
    console.error(`[API] Request failed:`, err, 'URL:', url)
    throw err
  }
}
