import { API_BASE } from '../config/api'

const VAPID_PUBLIC_KEY = import.meta.env.VITE_VAPID_PUBLIC_KEY

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = window.atob(base64)
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)))
}

export async function registerPushNotifications() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    console.warn('[Push] Not supported in this browser.')
    return false
  }

  if (!VAPID_PUBLIC_KEY) {
    console.warn('[Push] VITE_VAPID_PUBLIC_KEY not set.')
    return false
  }

  try {
    // Register (or reuse) the service worker
    const registration = await navigator.serviceWorker.register('/sw.js')
    await navigator.serviceWorker.ready

    // Ask for notification permission
    const permission = await Notification.requestPermission()
    if (permission !== 'granted') {
      console.info('[Push] Permission not granted.')
      return false
    }

    // Subscribe to push
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
    })

    // Send subscription to backend
    const subJson = subscription.toJSON()
    const res = await fetch(`${API_BASE}/push/subscribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint: subJson.endpoint, keys: subJson.keys }),
    })

    if (res.ok) {
      console.info('[Push] Subscribed successfully.')
      return true
    }
    return false
  } catch (err) {
    console.error('[Push] Registration failed:', err)
    return false
  }
}

export async function unregisterPushNotifications() {
  if (!('serviceWorker' in navigator)) return
  try {
    const registration = await navigator.serviceWorker.getRegistration('/sw.js')
    if (!registration) return
    const subscription = await registration.pushManager.getSubscription()
    if (!subscription) return

    const subJson = subscription.toJSON()
    await fetch(`${API_BASE}/push/subscribe`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint: subJson.endpoint, keys: subJson.keys }),
    })
    await subscription.unsubscribe()
    console.info('[Push] Unsubscribed.')
  } catch (err) {
    console.error('[Push] Unsubscribe failed:', err)
  }
}

export function isPushSupported() {
  return 'serviceWorker' in navigator && 'PushManager' in window && !!VAPID_PUBLIC_KEY
}

export function getPushPermission() {
  if (!('Notification' in window)) return 'unsupported'
  return Notification.permission // 'default' | 'granted' | 'denied'
}
