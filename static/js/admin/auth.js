const KEY = 'adminToken'

export function getToken() {
  return sessionStorage.getItem(KEY) || ''
}

export function setToken(t) {
  sessionStorage.setItem(KEY, t)
}

export function clearToken() {
  sessionStorage.removeItem(KEY)
}

export async function verifyToken() {
  try {
    const res = await fetch('/admin/api/login', {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
    return res.ok
  } catch (_) {
    return false
  }
}

export async function authFetch(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` } }
  if (body !== undefined) opts.body = JSON.stringify(body)
  const res = await fetch(path, opts)
  if (res.status === 401) throw Object.assign(new Error('Unauthorized'), { status: 401 })
  if (res.status === 204) return null
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
  return data
}
