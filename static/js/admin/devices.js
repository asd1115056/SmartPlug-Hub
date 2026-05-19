import * as api from './api.js'
import { refreshDevice } from '../api.js'

function esc(str) {
  const d = document.createElement('div')
  d.textContent = str ?? ''
  return d.innerHTML
}

function fmtMac(mac) {
  return (mac ?? '').replace(/(.{2})(?=.)/g, '$1:')
}

export async function loadDevices(onUnauth) {
  try {
    const devices = await api.getDevices()
    renderDevices(devices)
  } catch (e) {
    if (e.status === 401) onUnauth?.()
  }
}

function renderDevices(devices) {
  const tbody = document.querySelector('#devicesTable tbody')
  if (!devices.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4">No devices yet.</td></tr>'
    return
  }
  tbody.innerHTML = devices.map(d => {
    const statusDot = `<i class="bi bi-circle-fill ${d.is_online ? 'text-success' : 'text-secondary'}"
      style="font-size:.7rem;flex-shrink:0" title="${d.is_online ? 'online' : 'offline'}"></i>`
    const outletBtn = d.hw_is_strip
      ? `<button class="btn btn-sm btn-outline-secondary js-outlets" data-id="${d.id}" data-name="${esc(d.name ?? d.hw_alias ?? d.mac)}">
           <i class="bi bi-diagram-3"></i>
         </button>`
      : '<span class="text-muted">—</span>'
    return `<tr>
      <td class="text-center">${statusDot}</td>
      <td>
        <div class="d-flex gap-2 align-items-center">
          <input id="name-${d.id}" class="form-control inline-input" value="${esc(d.name ?? '')}"
            placeholder="${esc(d.hw_alias ?? d.mac)}">
          <button class="btn btn-sm btn-outline-secondary js-rename" data-id="${d.id}">
            <i class="bi bi-check-lg"></i>
          </button>
        </div>
      </td>
      <td><span class="badge bg-secondary">${d.type}</span></td>
      <td class="font-monospace text-muted">${fmtMac(d.mac)}</td>
      <td>
        <div class="d-flex gap-2 align-items-center">
          <input id="group-${d.id}" class="form-control form-control-sm" value="${esc(d.group_name ?? '')}"
            placeholder="—" style="width:110px">
          <button class="btn btn-sm btn-outline-secondary js-regroup" data-id="${d.id}">
            <i class="bi bi-check-lg"></i>
          </button>
        </div>
      </td>
      <td class="text-muted">${esc(d.last_known_ip ?? '—')}</td>
      <td>${outletBtn}</td>
      <td class="text-end">
        <button class="btn btn-sm btn-outline-danger js-delete-device" data-id="${d.id}">
          <i class="bi bi-trash"></i>
        </button>
      </td>
    </tr>`
  }).join('')
}

export async function openOutletsModal(deviceId, deviceName) {
  const modalEl = document.getElementById('outletsModal')
  const bodyEl = document.getElementById('outletsModalBody')
  document.getElementById('outletsModalTitle').innerHTML =
    `<i class="bi bi-diagram-3 me-2"></i>Outlets — ${esc(deviceName)}`
  bodyEl.innerHTML = `<div class="text-center py-3">
    <div class="spinner-border spinner-border-sm text-secondary" role="status"></div></div>`
  bootstrap.Modal.getOrCreateInstance(modalEl).show()

  try {
    // refresh first to get the latest outlet state
    const device = await refreshDevice(deviceId)
    if (!device.outlets?.length) {
      bodyEl.innerHTML = '<p class="text-muted mb-0">No outlets found.</p>'
      return
    }
    bodyEl.innerHTML = device.outlets.map((o, i) => `
      <div class="outlet-row">
        <span class="outlet-id">${i}</span>
        <input id="ol-${deviceId}-${o.outlet_id}" class="form-control flex-grow-1" value="${esc(o.name)}">
        <button class="btn btn-sm btn-outline-secondary js-rename-outlet"
          data-device-id="${deviceId}" data-outlet-id="${esc(o.outlet_id)}">
          <i class="bi bi-check-lg"></i>
        </button>
      </div>`).join('')
  } catch (e) {
    bodyEl.innerHTML = `<p class="text-danger mb-0">Failed to load outlets: ${esc(e.message)}</p>`
  }
}

export async function renameDevice(id, flash) {
  const input = document.getElementById(`name-${id}`)
  const btn = input?.nextElementSibling
  if (!input || !btn) return
  await _renameWithFeedback(input, btn, () => api.setDeviceName(id, input.value), flash)
}

export async function regroupDevice(id, flash) {
  const input = document.getElementById(`group-${id}`)
  const btn = input?.nextElementSibling
  if (!input || !btn) return
  await _renameWithFeedback(input, btn, () => api.setDeviceGroup(id, input.value), flash)
}

export async function renameOutlet(deviceId, outletId, flash) {
  const input = document.getElementById(`ol-${deviceId}-${outletId}`)
  const btn = input?.nextElementSibling
  if (!input || !btn) return
  await _renameWithFeedback(input, btn, () => api.setOutletName(deviceId, outletId, input.value), flash)
}

async function _renameWithFeedback(input, btn, apiCall, flash) {
  const orig = btn.innerHTML
  btn.disabled = true
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>'
  input.classList.remove('is-valid', 'is-invalid')
  try {
    await apiCall()
    input.classList.add('is-valid')
    setTimeout(() => input.classList.remove('is-valid'), 1500)
  } catch (e) {
    input.classList.add('is-invalid')
    setTimeout(() => input.classList.remove('is-invalid'), 2000)
    flash?.(e.message, false)
  } finally {
    btn.innerHTML = orig
    btn.disabled = false
  }
}

export function confirmDelete(message) {
  return new Promise(resolve => {
    const modalEl = document.getElementById('deleteModal')
    const btn = document.getElementById('deleteConfirmBtn')
    document.getElementById('deleteModalBody').textContent = message
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl)
    const onConfirm = () => { cleanup(); resolve(true) }
    const onDismiss = () => { cleanup(); resolve(false) }
    function cleanup() {
      btn.removeEventListener('click', onConfirm)
      modalEl.removeEventListener('hidden.bs.modal', onDismiss)
      modal.hide()
    }
    btn.addEventListener('click', onConfirm, { once: true })
    modalEl.addEventListener('hidden.bs.modal', onDismiss, { once: true })
    modal.show()
  })
}
