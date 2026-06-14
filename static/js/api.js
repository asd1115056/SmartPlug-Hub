const BASE = '/api/v1'

export async function getDevices() {
  const res = await fetch(`${BASE}/devices`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function setPower(deviceId, outletId, on, token = null) {
  const res = await fetch(`${BASE}/devices/${encodeURIComponent(deviceId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ outlet_id: outletId ?? null, on, token }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    const err = new Error(data.detail || `HTTP ${res.status}`)
    err.status = res.status
    throw err
  }
  return res.json()
}

export async function refreshDevice(deviceId) {
  const res = await fetch(`${BASE}/devices/${encodeURIComponent(deviceId)}/refresh`, {
    method: 'POST',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}
