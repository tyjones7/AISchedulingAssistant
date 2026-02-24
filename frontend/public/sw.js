// CampusAI Service Worker — handles background push notifications

self.addEventListener('push', (event) => {
  if (!event.data) return

  let payload
  try {
    payload = event.data.json()
  } catch {
    payload = { title: 'CampusAI', body: event.data.text() }
  }

  const options = {
    body: payload.body || '',
    icon: payload.icon || '/vite.svg',
    badge: payload.badge || '/vite.svg',
    tag: 'campusai-reminder',       // replaces any existing notification
    renotify: true,
    data: { url: self.location.origin },
  }

  event.waitUntil(
    self.registration.showNotification(payload.title || 'CampusAI', options)
  )
})

// Clicking a notification opens (or focuses) the app
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const targetUrl = event.notification.data?.url || self.location.origin
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url === targetUrl && 'focus' in client) {
          return client.focus()
        }
      }
      if (clients.openWindow) return clients.openWindow(targetUrl)
    })
  )
})
