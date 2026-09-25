import { request } from '../common.js'

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

export function authFetch(method, path, body) {
  return request(method, path, { body, headers: { Authorization: `Bearer ${getToken()}` } })
}
