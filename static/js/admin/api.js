import { authFetch } from './auth.js'

const BASE = '/admin/api'

export const getAccounts = () => authFetch('GET', `${BASE}/accounts`)
export const addAccount = data => authFetch('POST', `${BASE}/accounts`, data)
export const deleteAccount = id => authFetch('DELETE', `${BASE}/accounts/${id}`)

export const getDevices = () => authFetch('GET', `${BASE}/devices`)
export const addDevice = data => authFetch('POST', `${BASE}/devices`, data)
export const deleteDevice = id => authFetch('DELETE', `${BASE}/devices/${id}`)
export const setDeviceName = (id, name) => authFetch('PATCH', `${BASE}/devices/${id}/name`, { name })
export const setOutletName = (deviceId, outletId, name) =>
  authFetch('PATCH', `${BASE}/devices/${deviceId}/outlets/${outletId}/name`, { name })

export const miioLoginStart = (accountId, mac, region) =>
  authFetch('POST', `${BASE}/accounts/${accountId}/miio-login`, { mac, region })

export const miioSolveCaptcha = (sessionId, solution) =>
  authFetch('POST', `${BASE}/miio-sessions/${sessionId}/captcha`, { solution })

export const miioCaptchaImageUrl = sessionId =>
  `${BASE}/miio-sessions/${sessionId}/captcha-image`
