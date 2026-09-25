import { request } from './common.js'

const BASE = '/api/v1'

export function setPower(deviceId, outletId, on, token = null) {
  return request('PATCH', `${BASE}/devices/${encodeURIComponent(deviceId)}`, {
    body: { outlet_id: outletId ?? null, on, token },
  })
}

export function refreshDevice(deviceId) {
  return request('POST', `${BASE}/devices/${encodeURIComponent(deviceId)}/refresh`)
}
