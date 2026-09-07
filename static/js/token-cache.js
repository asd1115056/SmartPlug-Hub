const TTL_MS = 15 * 60 * 1000 // 15 minutes

function storageKey(deviceId, outletId) {
  return `plug-token:${deviceId}:${outletId ?? ''}`
}

export function getCachedToken(deviceId, outletId) {
  const key = storageKey(deviceId, outletId)
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return null
    const { token, expiresAt } = JSON.parse(raw)
    if (Date.now() > expiresAt) {
      sessionStorage.removeItem(key)
      return null
    }
    return token
  } catch {
    return null
  }
}

export function setCachedToken(deviceId, outletId, token) {
  try {
    sessionStorage.setItem(storageKey(deviceId, outletId), JSON.stringify({
      token,
      expiresAt: Date.now() + TTL_MS,
    }))
  } catch {
    // sessionStorage unavailable (e.g. private mode quota) — fall back to prompting each time
  }
}

export function clearCachedToken(deviceId, outletId) {
  try {
    sessionStorage.removeItem(storageKey(deviceId, outletId))
  } catch {
    // ignore
  }
}
