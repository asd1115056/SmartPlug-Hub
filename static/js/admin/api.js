import { authFetch } from './auth.js'

const BASE = '/admin/api'

export function getDevices() { return authFetch('GET', `${BASE}/devices`) }
export function addDevice(data) { return authFetch('POST', `${BASE}/devices`, data) }
export function deleteDevice(id) { return authFetch('DELETE', `${BASE}/devices/${id}`) }
export function setDeviceName(id, name) {
  return authFetch('PATCH', `${BASE}/devices/${id}/name`, { name })
}
export function setDeviceGroup(id, group_name) {
  return authFetch('PATCH', `${BASE}/devices/${id}/group`, { group_name })
}
export function setKasaCredentials(id, username, password) {
  return authFetch('PATCH', `${BASE}/devices/${id}/kasa-credentials`, { username, password })
}
export function setMiioCredentials(id, token) {
  return authFetch('PATCH', `${BASE}/devices/${id}/miio-credentials`, { token })
}
export function setTuyaCredentials(id, device_id, local_key, product_id) {
  return authFetch('PATCH', `${BASE}/devices/${id}/tuya-credentials`, { device_id, local_key, product_id })
}
export function setOutletName(deviceId, outletId, name) {
  return authFetch('PATCH', `${BASE}/devices/${deviceId}/outlets/${outletId}/name`, { name })
}

export function scanNetwork() { return authFetch('POST', `${BASE}/scan`) }
