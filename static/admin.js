import { getToken, setToken, clearToken, verifyToken } from './js/admin/auth.js'
import * as adminApi from './js/admin/api.js'
import { renderDeviceCards, renderScanResults, fillDetailPanel, confirmDelete } from './js/admin/devices.js'

// ── State ─────────────────────────────────────────────────────────────────────

let _devices = []
let _activeDeviceId = null

// ── DOM refs ──────────────────────────────────────────────────────────────────

const loginView    = document.getElementById('loginView')
const adminView    = document.getElementById('adminView')
const loginBtn     = document.getElementById('loginBtn')
const loginErr     = document.getElementById('loginErr')
const tokenInput   = document.getElementById('tokenInput')
const logoutBtn    = document.getElementById('logoutBtn')
const menuBtn      = document.getElementById('menuBtn')
const menuDropdown = document.getElementById('menuDropdown')
const scanBtn      = document.getElementById('scanBtn')
const deviceFilter = document.getElementById('deviceFilter')
const panelBackdrop  = document.getElementById('panelBackdrop')
const detailPanel    = document.getElementById('detailPanel')
const panelClose     = document.getElementById('panelClose')
const panelSaveBtn   = document.getElementById('panelSaveBtn')
const panelDeleteBtn = document.getElementById('panelDeleteBtn')

// ── Toast ─────────────────────────────────────────────────────────────────────

function flash(msg, ok = true) {
  const container = document.getElementById('toastContainer')
  const el = document.createElement('div')
  el.className = `toast align-items-center text-bg-${ok ? 'success' : 'danger'} border-0`
  el.setAttribute('role', 'alert')
  el.innerHTML = `<div class="d-flex">
    <div class="toast-body">${esc(msg)}</div>
    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
  </div>`
  container.appendChild(el)
  const toast = new bootstrap.Toast(el, { delay: 3000 })
  toast.show()
  el.addEventListener('hidden.bs.toast', () => el.remove())
}

function esc(str) {
  const d = document.createElement('div')
  d.textContent = str ?? ''
  return d.innerHTML
}

// ── Auth ──────────────────────────────────────────────────────────────────────

function showLogin(err) {
  adminView.style.display = 'none'
  loginView.style.display = 'flex'
  loginErr.textContent = err || ''
  loginBtn.disabled = false
}

function showAdmin() {
  loginView.style.display = 'none'
  adminView.style.display = 'block'
  loadDevices()
}

function onUnauth() {
  showLogin('Session expired. Please sign in again.')
}

loginBtn.addEventListener('click', async () => {
  const token = tokenInput.value.trim()
  if (!token) return
  loginBtn.disabled = true
  loginErr.textContent = ''
  setToken(token)
  if (await verifyToken()) { showAdmin() }
  else { clearToken(); showLogin('Invalid token.') }
})

tokenInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') loginBtn.click()
})

logoutBtn.addEventListener('click', () => {
  clearToken()
  tokenInput.value = ''
  closeMenu()
  showLogin('')
})

// ── Navbar dropdown ───────────────────────────────────────────────────────────

function closeMenu() { menuDropdown.classList.remove('open') }

menuBtn.addEventListener('click', e => {
  e.stopPropagation()
  menuDropdown.classList.toggle('open')
})

document.addEventListener('click', closeMenu)
menuDropdown.addEventListener('click', e => e.stopPropagation())

// ── Devices ───────────────────────────────────────────────────────────────────

async function loadDevices() {
  try {
    _devices = await adminApi.getDevices()
    renderDeviceCards(_devices, deviceFilter.value)
  } catch (e) {
    if (e.status === 401) onUnauth()
  }
}

deviceFilter.addEventListener('input', () => {
  renderDeviceCards(_devices, deviceFilter.value)
})

document.getElementById('deviceCards').addEventListener('click', e => {
  const card = e.target.closest('.admin-device-card')
  if (!card) return
  openPanel(card.dataset.deviceId)
})

// ── Scan ──────────────────────────────────────────────────────────────────────

scanBtn.addEventListener('click', async () => {
  scanBtn.disabled = true
  scanBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Scanning…'
  const resultsEl = document.getElementById('scanResults')
  resultsEl.hidden = true
  resultsEl.innerHTML = ''

  try {
    const discovered = await adminApi.scanNetwork()
    renderScanResults(discovered, handleScanAdd)
  } catch (err) {
    resultsEl.innerHTML = `<p class="text-danger mb-0 mt-2">${esc(err.message || 'Scan failed')}</p>`
    resultsEl.hidden = false
  } finally {
    scanBtn.disabled = false
    scanBtn.innerHTML = '<i class="bi bi-radar me-1"></i>Scan'
  }
})

async function handleScanAdd(deviceData) {
  try {
    const row = await adminApi.addDevice({
      mac: deviceData.mac,
      type: deviceData.type,
      broadcast: deviceData.broadcast,
      miio_id: deviceData.miio_id,
      miio_token: null,
      tuya_device_id: deviceData.tuya_device_id,
      tuya_local_key: deviceData.tuya_local_key,
      tuya_product_id: deviceData.tuya_product_id,
    })
    flash('Device added')
    await loadDevices()
    openPanel(row.id)
    const btn = document.querySelector(`.js-scan-add[data-mac="${deviceData.mac}"]`)
    if (btn) {
      const scanRow = btn.closest('.scan-row')
      if (scanRow) {
        btn.replaceWith(Object.assign(document.createElement('span'), {
          className: 'text-success flex-shrink-0',
          style: 'font-size:.78rem;width:80px;text-align:center',
          innerHTML: '<i class="bi bi-check-lg me-1"></i>Added',
        }))
        scanRow.classList.add('is-registered')
      }
    }
  } catch (err) {
    flash(err.message || 'Failed to add device', false)
  }
}

// ── Detail panel ──────────────────────────────────────────────────────────────

function openPanel(deviceId) {
  const device = _devices.find(d => d.id === deviceId)
  if (!device) return
  _activeDeviceId = deviceId

  document.querySelectorAll('.admin-device-card').forEach(c => {
    c.classList.toggle('selected', c.dataset.deviceId === deviceId)
  })

  fillDetailPanel(device)
  panelBackdrop.classList.add('open')
  detailPanel.classList.add('open')
}

function closePanel() {
  _activeDeviceId = null
  panelBackdrop.classList.remove('open')
  detailPanel.classList.remove('open')
  document.querySelectorAll('.admin-device-card.selected').forEach(c => c.classList.remove('selected'))
}

panelClose.addEventListener('click', closePanel)
panelBackdrop.addEventListener('click', closePanel)

// ── Panel save ────────────────────────────────────────────────────────────────

panelSaveBtn.addEventListener('click', async () => {
  if (!_activeDeviceId) return
  const device = _devices.find(d => d.id === _activeDeviceId)
  if (!device) return

  panelSaveBtn.disabled = true
  panelSaveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Saving…'

  const errors = []
  try {
    // Name
    const newName = document.getElementById('panelNameInput').value.trim()
    if (newName !== (device.name ?? '')) {
      await adminApi.setDeviceName(_activeDeviceId, newName)
    }

    // Group
    const newGroup = document.getElementById('panelGroupInput').value.trim() || null
    if (newGroup !== (device.group_name ?? null)) {
      await adminApi.setDeviceGroup(_activeDeviceId, newGroup)
    }

    // Tuya credentials (tuya only)
    const tuyaSec = document.getElementById('panelTuya')
    if (!tuyaSec.hidden) {
      const newDeviceId = document.getElementById('panelTuyaDeviceId').value.trim() || null
      const newLocalKey = document.getElementById('panelTuyaLocalKey').value.trim() || null
      const newProductId = document.getElementById('panelTuyaProductId').value.trim() || null
      if (
        newDeviceId !== (device.tuya_device_id ?? null) ||
        newLocalKey !== (device.tuya_local_key ?? null) ||
        newProductId !== (device.tuya_product_id ?? null)
      ) {
        await adminApi.setTuyaCredentials(_activeDeviceId, newDeviceId, newLocalKey, newProductId)
      }
    }

    // MiIO credentials (miio only)
    const miioSec = document.getElementById('panelMiio')
    if (!miioSec.hidden) {
      const newToken = document.getElementById('panelMiioToken').value.trim() || null
      if (newToken !== (device.miio_token ?? null)) {
        await adminApi.setMiioCredentials(_activeDeviceId, newToken)
      }
    }

    // Kasa credentials (kasa only)
    const kasaSec = document.getElementById('panelKasa')
    if (!kasaSec.hidden) {
      const newUsername = document.getElementById('panelKasaUsername').value.trim() || null
      const newPassword = document.getElementById('panelKasaPassword').value || null
      if (newUsername !== (device.kasa_username ?? null) || newPassword !== (device.kasa_password ?? null)) {
        await adminApi.setKasaCredentials(_activeDeviceId, newUsername, newPassword)
      }
    }

    // Outlet names (strip only)
    if (device.hw_is_strip) {
      const inputs = document.querySelectorAll('#panelOutlets .js-outlet-name')
      const outlet = device.outlets ?? []
      for (const input of inputs) {
        const outletId = input.dataset.outletId
        const original = outlet.find(o => o.outlet_id === outletId)
        if (original && input.value !== original.name) {
          try {
            await adminApi.setOutletName(_activeDeviceId, outletId, input.value)
          } catch (e) {
            errors.push(`Outlet ${outletId}: ${e.message}`)
          }
        }
      }
    }

    await loadDevices()
    if (errors.length) {
      flash(`Saved with errors: ${errors.join('; ')}`, false)
    } else {
      flash('Changes saved')
      closePanel()
    }
  } catch (err) {
    flash(err.message || 'Save failed', false)
  } finally {
    panelSaveBtn.disabled = false
    panelSaveBtn.innerHTML = '<i class="bi bi-floppy me-1"></i>Save Changes'
  }
})

// ── Panel delete ──────────────────────────────────────────────────────────────

panelDeleteBtn.addEventListener('click', async () => {
  if (!_activeDeviceId) return
  if (!await confirmDelete('Delete this device? This cannot be undone.')) return
  try {
    await adminApi.deleteDevice(_activeDeviceId)
    flash('Device deleted')
    closePanel()
    await loadDevices()
  } catch (err) {
    if (err.status !== 401) flash(err.message, false)
  }
})

// ── Init ──────────────────────────────────────────────────────────────────────

;(async () => {
  if (getToken() && await verifyToken()) { showAdmin() }
  else { showLogin('') }
})()
