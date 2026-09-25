import { authFetch } from './auth.js'

const BASE = '/admin/api'

export function getDevices() { return authFetch('GET', `${BASE}/devices`) }
export function addDevice(data) { return authFetch('POST', `${BASE}/devices`, data) }
export function deleteDevice(id) { return authFetch('DELETE', `${BASE}/devices/${id}`) }
export function updateDevice(id, patch) {
  return authFetch('PATCH', `${BASE}/devices/${id}`, patch)
}
export function setOutletName(deviceId, outletId, name) {
  return authFetch('PATCH', `${BASE}/devices/${deviceId}/outlets/${outletId}/name`, { name })
}
export function setOutletToken(deviceId, outletId, token) {
  return authFetch('PATCH', `${BASE}/devices/${deviceId}/outlets/${outletId}/token`, { token })
}

export function scanNetwork() { return authFetch('POST', `${BASE}/scan`) }
