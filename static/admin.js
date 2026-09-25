import { getToken, setToken, clearToken, verifyToken } from './js/admin/auth.js'
import * as adminApi from './js/admin/api.js'
import { renderDeviceCards, renderScanResults, fillDetailPanel, confirmDelete } from './js/admin/devices.js'
import { esc } from './js/common.js'
import { showToast } from './js/notifications.js'

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
const kasaPassword       = document.getElementById('panelKasaPassword')
const kasaPasswordToggle = document.getElementById('panelKasaPasswordToggle')

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
      ip: deviceData.ip,
      miio_id: deviceData.miio_id,
      miio_token: null,
      tuya_device_id: deviceData.tuya_device_id,
      tuya_local_key: deviceData.tuya_local_key,
      tuya_product_id: deviceData.tuya_product_id,
    })
    showToast('Device added', 'success')
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
    showToast(err.message || 'Failed to add device', 'danger')
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
  setPasswordVisible(false)   // never carry a revealed password over to another device
  panelBackdrop.classList.add('open')
  detailPanel.classList.add('open')
}

function setPasswordVisible(isVisible) {
  kasaPassword.type = isVisible ? 'text' : 'password'
  kasaPasswordToggle.querySelector('i').className = `bi ${isVisible ? 'bi-eye-slash' : 'bi-eye'}`
  const label = isVisible ? 'Hide password' : 'Show password'
  kasaPasswordToggle.title = label
  kasaPasswordToggle.setAttribute('aria-label', label)
}

kasaPasswordToggle.addEventListener('click', () => setPasswordVisible(kasaPassword.type === 'password'))

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
    // Device fields: collect what changed and send it as one partial update
    const patch = {}

    const newName = document.getElementById('panelNameInput').value.trim()
    if (newName !== (device.name ?? '')) patch.name = newName

    const newGroup = document.getElementById('panelGroupInput').value.trim() || null
    if (newGroup !== (device.group_name ?? null)) patch.group_name = newGroup

    if (!document.getElementById('panelTuya').hidden) {
      const tuya = {
        tuya_device_id: document.getElementById('panelTuyaDeviceId').value.trim() || null,
        tuya_local_key: document.getElementById('panelTuyaLocalKey').value.trim() || null,
        tuya_product_id: document.getElementById('panelTuyaProductId').value.trim() || null,
      }
      if (Object.entries(tuya).some(([k, v]) => v !== (device[k] ?? null))) Object.assign(patch, tuya)
    }

    if (!document.getElementById('panelMiio').hidden) {
      const miio = {
        miio_id: document.getElementById('panelMiioId').value.trim() || null,
        miio_token: document.getElementById('panelMiioToken').value.trim() || null,
      }
      if (Object.entries(miio).some(([k, v]) => v !== (device[k] ?? null))) Object.assign(patch, miio)
    }

    if (!document.getElementById('panelKasa').hidden) {
      const kasa = {
        kasa_username: document.getElementById('panelKasaUsername').value.trim() || null,
        kasa_password: kasaPassword.value || null,
      }
      if (Object.entries(kasa).some(([k, v]) => v !== (device[k] ?? null))) Object.assign(patch, kasa)
    }

    // Device token (non-strip only)
    if (!document.getElementById('panelDeviceTokenSec').hidden) {
      const newDeviceToken = document.getElementById('panelDeviceToken').value.trim() || null
      if (newDeviceToken !== (device.device_token ?? null)) patch.device_token = newDeviceToken
    }

    if (Object.keys(patch).length) await adminApi.updateDevice(_activeDeviceId, patch)

    // Outlet names + tokens (strip only)
    if (device.hw_is_strip) {
      const outlets = device.outlets ?? []

      for (const input of document.querySelectorAll('#panelOutlets .js-outlet-name')) {
        const outletId = input.dataset.outletId
        const original = outlets.find(o => o.outlet_id === outletId)
        if (original && input.value !== original.name) {
          try {
            await adminApi.setOutletName(_activeDeviceId, outletId, input.value)
          } catch (e) {
            errors.push(`Outlet ${outletId} name: ${e.message}`)
          }
        }
      }

      for (const input of document.querySelectorAll('#panelOutlets .js-outlet-token')) {
        const outletId = input.dataset.outletId
        const original = outlets.find(o => o.outlet_id === outletId)
        const newToken = input.value.trim() || null
        const oldToken = original?.token ?? null
        if (newToken !== oldToken) {
          try {
            await adminApi.setOutletToken(_activeDeviceId, outletId, newToken)
          } catch (e) {
            errors.push(`Outlet ${outletId} token: ${e.message}`)
          }
        }
      }
    }

    await loadDevices()
    if (errors.length) {
      showToast(`Saved with errors: ${errors.join('; ')}`, 'danger')
    } else {
      showToast('Changes saved', 'success')
      closePanel()
    }
  } catch (err) {
    showToast(err.message || 'Save failed', 'danger')
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
    showToast('Device deleted', 'success')
    closePanel()
    await loadDevices()
  } catch (err) {
    if (err.status !== 401) showToast(err.message, 'danger')
  }
})

// ── Init ──────────────────────────────────────────────────────────────────────

;(async () => {
  if (getToken() && await verifyToken()) { showAdmin() }
  else { showLogin('') }
})()
