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
export function setKasaCredentials(id, kasa_username, kasa_password) {
  return authFetch('PATCH', `${BASE}/devices/${id}/kasa-credentials`, { kasa_username, kasa_password })
}
export function setMiioCredentials(id, miio_device_id, miio_device_token) {
  return authFetch('PATCH', `${BASE}/devices/${id}/miio-credentials`, { miio_device_id, miio_device_token })
}
export function setTuyaCredentials(id, tuya_device_id, tuya_local_key, tuya_product_id) {
  return authFetch('PATCH', `${BASE}/devices/${id}/tuya-credentials`, { tuya_device_id, tuya_local_key, tuya_product_id })
}
export function setOutletName(deviceId, outletId, name) {
  return authFetch('PATCH', `${BASE}/devices/${deviceId}/outlets/${outletId}/name`, { name })
}
export function setOutletToken(deviceId, outletId, token) {
  return authFetch('PATCH', `${BASE}/devices/${deviceId}/outlets/${outletId}/token`, { token })
}
export function setDeviceToken(id, token) {
  return authFetch('PATCH', `${BASE}/devices/${id}/token`, { token })
}

export function scanNetwork() { return authFetch('POST', `${BASE}/scan`) }
