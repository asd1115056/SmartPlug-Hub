// Shared by the public page and the admin panel

export function esc(str) {
  const d = document.createElement('div')
  d.textContent = str ?? ''
  // Also escape quotes: callers interpolate into attribute values, not just text
  return d.innerHTML.replaceAll('"', '&quot;')
}

// JSON request; on failure throws an Error carrying the HTTP status and the API's detail
export async function request(method, path, { body, headers = {} } = {}) {
  const opts = { method, headers: { ...headers } }
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const res = await fetch(path, opts)
  if (res.status === 204) return null
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw Object.assign(new Error(data.detail || `HTTP ${res.status}`), { status: res.status })
  return data
}

// Local wall-clock time with its UTC offset, e.g. "3:04:05 PM UTC+8"
export function fmtTime(iso) {
  try {
    const date = new Date(iso)
    const offsetMin = -date.getTimezoneOffset()
    const sign = offsetMin >= 0 ? '+' : '-'
    const absMin = Math.abs(offsetMin)
    const hours = Math.floor(absMin / 60)
    const mins = absMin % 60
    const offset = mins ? `${hours}:${String(mins).padStart(2, '0')}` : `${hours}`
    return `${date.toLocaleTimeString(undefined, { hour12: true })} UTC${sign}${offset}`
  } catch { return '' }
}
