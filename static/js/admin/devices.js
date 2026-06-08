import * as api from './api.js'
import { refreshDevice } from '../api.js'

function esc(str) {
  const d = document.createElement('div')
  d.textContent = str ?? ''
  return d.innerHTML.replaceAll('"', '&quot;')
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
    tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">No devices yet.</td></tr>'
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
      <td class="text-center"><span class="badge bg-secondary">${d.type}</span></td>
      <td>
        <span id="name-view-${d.id}" class="editable-field" data-id="${d.id}" data-field="name">
          <span class="field-value">${esc(d.name ?? d.hw_alias ?? d.mac)}</span><i class="bi bi-pencil edit-pencil ms-1"></i>
        </span>
        <div id="name-edit-${d.id}" class="d-none d-flex gap-1 align-items-center">
          <input id="name-${d.id}" class="form-control form-control-sm" value="${esc(d.name ?? '')}"
            placeholder="${esc(d.hw_alias ?? d.mac)}" style="width:160px">
          <button class="btn btn-sm btn-outline-secondary js-rename" data-id="${d.id}">
            <i class="bi bi-check-lg"></i>
          </button>
          <button class="btn btn-sm btn-outline-secondary js-cancel-edit" data-id="${d.id}" data-field="name">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
      </td>
      <td>
        <span id="group-view-${d.id}" class="editable-field" data-id="${d.id}" data-field="group">
          <span class="field-value">${esc(d.group_name ?? '—')}</span><i class="bi bi-pencil edit-pencil ms-1"></i>
        </span>
        <div id="group-edit-${d.id}" class="d-none d-flex gap-1 align-items-center">
          <input id="group-${d.id}" class="form-control form-control-sm" value="${esc(d.group_name ?? '')}"
            placeholder="—" style="width:110px">
          <button class="btn btn-sm btn-outline-secondary js-regroup" data-id="${d.id}">
            <i class="bi bi-check-lg"></i>
          </button>
          <button class="btn btn-sm btn-outline-secondary js-cancel-edit" data-id="${d.id}" data-field="group">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
      </td>
      <td class="text-center text-muted">${esc(d.last_known_ip ?? '—')}</td>
      <td class="text-center font-monospace text-muted small">${fmtMac(d.mac)}</td>
      <td class="text-center">${outletBtn}</td>
      <td class="text-center">
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
      <div class="input-group mb-2">
        <span class="input-group-text text-secondary font-monospace outlet-id-cell">${i}</span>
        <input id="ol-${deviceId}-${o.outlet_id}" class="form-control" value="${esc(o.name)}">
        <button class="btn btn-outline-secondary js-rename-outlet"
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
  if (!input || !btn) return false
  return _renameWithFeedback(input, btn, () => api.setDeviceName(id, input.value), flash)
}

export async function regroupDevice(id, flash) {
  const input = document.getElementById(`group-${id}`)
  const btn = input?.nextElementSibling
  if (!input || !btn) return false
  return _renameWithFeedback(input, btn, () => api.setDeviceGroup(id, input.value), flash)
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
  let success = false
  try {
    await apiCall()
    success = true
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
  return success
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
