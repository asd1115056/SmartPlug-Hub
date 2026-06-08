import { getToken, setToken, clearToken, verifyToken } from './js/admin/auth.js'
import * as adminApi from './js/admin/api.js'
import { loadAccounts, getCache as getAccounts, populateAccountSelect } from './js/admin/accounts.js'
import {
  loadDevices, openOutletsModal, renameDevice, regroupDevice, renameOutlet, confirmDelete,
} from './js/admin/devices.js'

// ── Cached DOM refs ───────────────────────────────────────────────────────────

const loginView   = document.getElementById('loginView')
const adminView   = document.getElementById('adminView')
const loginBtn    = document.getElementById('loginBtn')
const loginErr    = document.getElementById('loginErr')
const tokenInput  = document.getElementById('tokenInput')
const logoutBtn   = document.getElementById('logoutBtn')

// ── Notifications ─────────────────────────────────────────────────────────────

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
  loadAll()
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
  showLogin('')
})

// ── Accounts ──────────────────────────────────────────────────────────────────

document.getElementById('addAccountForm').addEventListener('submit', async e => {
  e.preventDefault()
  const f = e.target
  try {
    await adminApi.addAccount({ type: f.type.value, username: f.username.value, password: f.password.value })
    bootstrap.Modal.getInstance(document.getElementById('addAccountModal')).hide()
    f.reset()
    flash('Account added')
    await loadAccounts(onUnauth)
  } catch (err) {
    if (err.status !== 401) flash(err.message, false)
  }
})

document.getElementById('accountsTable').addEventListener('click', async e => {
  const btn = e.target.closest('.js-delete-account')
  if (!btn) return
  if (!await confirmDelete('Delete this account?')) return
  try {
    await adminApi.deleteAccount(btn.dataset.id)
    flash('Account deleted')
    await loadAccounts(onUnauth)
  } catch (err) {
    if (err.status !== 401) flash(err.message, false)
  }
})

// ── Devices ───────────────────────────────────────────────────────────────────

const accountSel   = document.getElementById('accountSelect')
const miioToken    = document.getElementById('miioToken')
const miioDeviceId = document.getElementById('miioDeviceId')

accountSel.addEventListener('change', () => {
  const type = accountSel.options[accountSel.selectedIndex]?.dataset.type
  const isMiio = type === 'miio'
  document.getElementById('miioFields').hidden = !isMiio
  miioToken.required = isMiio
  miioDeviceId.required = isMiio
})

let _miioSessionId = null

async function _applyMiioResult(result) {
  if (result.session_id) {
    _miioSessionId = result.session_id
    const isCaptcha = result.challenge === 'captcha'
    const img = document.getElementById('miioCaptchaImg')
    img.hidden = !isCaptcha
    if (isCaptcha) img.src = 'data:image/jpeg;base64,' + result.captcha_b64
    const input = document.getElementById('miioCaptchaInput')
    input.placeholder = isCaptcha ? 'Enter captcha (case-sensitive)' : 'Enter 2FA code from email'
    document.getElementById('miioCaptchaBlock').hidden = false
    input.value = ''
    input.focus()
  } else {
    _miioSessionId = null
    document.getElementById('miioCaptchaBlock').hidden = true
    miioToken.value = result.token
    miioDeviceId.value = result.did
    flash('Token and Device ID fetched')
  }
}

document.getElementById('miioFetchBtn').addEventListener('click', async () => {
  const accountId = accountSel.value
  const mac = document.querySelector('[name="mac"]').value.trim()
  const region = document.getElementById('miioRegion').value
  if (!accountId) { flash('Select a MiIO account first', false); return }
  if (!mac) { flash('Enter a MAC address first', false); return }
  const btn = document.getElementById('miioFetchBtn')
  const orig = btn.innerHTML
  btn.disabled = true
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>'
  try {
    const result = await adminApi.miioLoginStart(parseInt(accountId), mac, region)
    await _applyMiioResult(result)
  } catch (err) {
    flash(err.message, false)
  } finally {
    btn.innerHTML = orig
    btn.disabled = false
  }
})

document.getElementById('miioCaptchaSubmitBtn').addEventListener('click', async () => {
  if (!_miioSessionId) return
  const solution = document.getElementById('miioCaptchaInput').value.trim()
  if (!solution) { flash('Enter captcha code', false); return }
  const btn = document.getElementById('miioCaptchaSubmitBtn')
  btn.disabled = true
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>'
  try {
    const result = await adminApi.miioSolve(_miioSessionId, solution)
    await _applyMiioResult(result)
  } catch (err) {
    flash(err.message, false)
    // Session is dead — auto-retry to get a fresh captcha
    if (err.message.includes('captcha') || err.message.includes('Invalid')) {
      document.getElementById('miioCaptchaBlock').hidden = true
      document.getElementById('miioFetchBtn').click()
    }
  } finally {
    btn.innerHTML = 'Submit'
    btn.disabled = false
  }
})

document.getElementById('addDeviceForm').addEventListener('submit', async e => {
  e.preventDefault()
  const f = e.target
  const accountId = f.account_id.value ? parseInt(f.account_id.value) : null
  try {
    await adminApi.addDevice({
      mac: f.mac.value, type: accountSel.options[accountSel.selectedIndex]?.dataset.type || 'kasa',
      broadcast: f.broadcast.value, account_id: accountId,
      group_name: f.group_name.value || null,
      miio_token: f.miio_token?.value || null, miio_id: f.miio_id?.value || null,
    })
    bootstrap.Modal.getInstance(document.getElementById('addDeviceModal')).hide()
    f.reset()
    accountSel.dispatchEvent(new Event('change'))
    flash('Device added — probing in background…')
    await loadDevices(onUnauth)
  } catch (err) {
    if (err.status !== 401) flash(err.message, false)
  }
})

function _switchToView(id, field) {
  document.getElementById(`${field}-edit-${id}`)?.classList.add('d-none')
  document.getElementById(`${field}-view-${id}`)?.classList.remove('d-none')
}

function _switchToEdit(id, field) {
  document.getElementById(`${field}-view-${id}`)?.classList.add('d-none')
  const editDiv = document.getElementById(`${field}-edit-${id}`)
  editDiv?.classList.remove('d-none')
  editDiv?.querySelector('input')?.focus()
}

document.getElementById('devicesTable').addEventListener('click', async e => {
  const editTrigger = e.target.closest('.editable-field')
  if (editTrigger) { _switchToEdit(editTrigger.dataset.id, editTrigger.dataset.field); return }

  const cancel = e.target.closest('.js-cancel-edit')
  if (cancel) { _switchToView(cancel.dataset.id, cancel.dataset.field); return }

  const del = e.target.closest('.js-delete-device')
  if (del) {
    if (!await confirmDelete('Delete this device? This cannot be undone.')) return
    try {
      await adminApi.deleteDevice(del.dataset.id)
      flash('Device deleted')
      await loadDevices(onUnauth)
    } catch (err) {
      if (err.status !== 401) flash(err.message, false)
    }
    return
  }

  const rename = e.target.closest('.js-rename')
  if (rename) {
    const id = rename.dataset.id
    const ok = await renameDevice(id, flash)
    if (ok) {
      const val = document.getElementById(`name-${id}`).value
      document.querySelector(`#name-view-${id} .field-value`).textContent =
        val || document.getElementById(`name-${id}`).placeholder
      const outletBtn = document.querySelector(`.js-outlets[data-id="${id}"]`)
      if (outletBtn) outletBtn.dataset.name = val
      _switchToView(id, 'name')
    }
    return
  }

  const regroup = e.target.closest('.js-regroup')
  if (regroup) {
    const id = regroup.dataset.id
    const ok = await regroupDevice(id, flash)
    if (ok) {
      const val = document.getElementById(`group-${id}`).value
      document.querySelector(`#group-view-${id} .field-value`).textContent = val || '—'
      _switchToView(id, 'group')
    }
    return
  }

  const outlets = e.target.closest('.js-outlets')
  if (outlets) { await openOutletsModal(outlets.dataset.id, outlets.dataset.name) }
})

document.getElementById('devicesTable').addEventListener('keydown', e => {
  if (e.key === 'Enter') e.target.closest('tr')?.querySelector('.js-rename, .js-regroup')?.click()
  else if (e.key === 'Escape') e.target.closest('tr')?.querySelector('.js-cancel-edit')?.click()
})

document.getElementById('outletsModalBody').addEventListener('click', async e => {
  const btn = e.target.closest('.js-rename-outlet')
  if (btn) await renameOutlet(btn.dataset.deviceId, btn.dataset.outletId, flash)
})

// ── Scan ──────────────────────────────────────────────────────────────────────

const scanBtn        = document.getElementById('scanBtn')
const scanRunBtn     = document.getElementById('scanRunBtn')
const scanModal      = bootstrap.Modal.getOrCreateInstance(document.getElementById('scanModal'))
const scanStatus     = document.getElementById('scanModalStatus')
const scanTable      = document.getElementById('scanTable')
const scanBody       = document.getElementById('scanTableBody')
const scanPagination = document.getElementById('scanPagination')
const scanPageInfo   = document.getElementById('scanPageInfo')

const SCAN_PAGE_SIZE = 10
let _scanDevices = []
let _scanPage    = 0

function fmtMac(mac) {
  return (mac ?? '').replace(/(.{2})(?=.)/g, '$1:')
}

function renderScanTable(devices) {
  _scanDevices = devices
  _scanPage = 0
  _renderScanPage()
}

function _renderScanPage() {
  scanStatus.hidden = true
  if (!_scanDevices.length) {
    scanBody.innerHTML = ''
    scanTable.hidden = true
    scanPagination.hidden = true
    scanStatus.textContent = 'No new devices found.'
    scanStatus.hidden = false
    return
  }
  const total      = _scanDevices.length
  const totalPages = Math.ceil(total / SCAN_PAGE_SIZE)
  const start      = _scanPage * SCAN_PAGE_SIZE
  const slice      = _scanDevices.slice(start, start + SCAN_PAGE_SIZE)

  scanBody.innerHTML = slice.map(d => `<tr>
    <td class="text-center"><span class="badge bg-secondary">${esc(d.type)}</span></td>
    <td class="text-muted">${esc(d.model ?? '—')}</td>
    <td class="font-monospace small">${esc(fmtMac(d.mac))}</td>
    <td class="text-center text-muted">${esc(d.ip)}</td>
    <td class="text-center text-muted small">${esc(d.broadcast)}</td>
    <td class="text-end">
      <button class="btn btn-sm btn-outline-primary js-scan-add"
        data-mac="${esc(d.mac)}"
        data-type="${esc(d.type)}"
        data-broadcast="${esc(d.broadcast)}"
        data-miio-id="${esc(d.miio_id ?? '')}">
        <i class="bi bi-plus-lg me-1"></i>Add
      </button>
    </td>
  </tr>`).join('')
  scanTable.hidden = false

  if (totalPages <= 1) { scanPagination.hidden = true; return }

  scanPageInfo.textContent = `${start + 1}–${Math.min(start + SCAN_PAGE_SIZE, total)} / ${total}`
  scanPagination.querySelector('ul').innerHTML = `
    <li class="page-item ${_scanPage === 0 ? 'disabled' : ''}">
      <button class="page-link" data-page="${_scanPage - 1}">‹</button>
    </li>
    ${Array.from({ length: totalPages }, (_, i) => `
      <li class="page-item ${i === _scanPage ? 'active' : ''}">
        <button class="page-link" data-page="${i}">${i + 1}</button>
      </li>`).join('')}
    <li class="page-item ${_scanPage === totalPages - 1 ? 'disabled' : ''}">
      <button class="page-link" data-page="${_scanPage + 1}">›</button>
    </li>`
  scanPagination.hidden = false
}

scanPagination.addEventListener('click', e => {
  const btn = e.target.closest('[data-page]')
  if (!btn) return
  const page = parseInt(btn.dataset.page)
  if (page < 0 || page >= Math.ceil(_scanDevices.length / SCAN_PAGE_SIZE)) return
  _scanPage = page
  _renderScanPage()
})

async function runScan() {
  scanBody.innerHTML = ''
  scanTable.hidden = true
  scanStatus.textContent = ''
  scanStatus.hidden = true
  scanRunBtn.disabled = true
  scanRunBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Scanning…'
  scanStatus.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Scanning all interfaces…'
  scanStatus.hidden = false
  try {
    const devices = await adminApi.scanNetwork()
    renderScanTable(devices)
  } catch (err) {
    scanStatus.textContent = err.message || 'Scan failed'
    scanStatus.hidden = false
  } finally {
    scanRunBtn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Scan'
    scanRunBtn.disabled = false
  }
}

scanBtn.addEventListener('click', () => scanModal.show())
document.getElementById('scanModal').addEventListener('shown.bs.modal', runScan)
scanRunBtn.addEventListener('click', runScan)

document.getElementById('scanTable').addEventListener('click', e => {
  const btn = e.target.closest('.js-scan-add')
  if (!btn) return
  const { mac, type, broadcast, miioId } = btn.dataset

  const form = document.getElementById('addDeviceForm')
  form.querySelector('[name="mac"]').value = fmtMac(mac)
  form.querySelector('[name="broadcast"]').value = broadcast

  const opts = accountSel.options
  let matched = false
  for (let i = 0; i < opts.length; i++) {
    if (opts[i].dataset.type === type) { accountSel.selectedIndex = i; matched = true; break }
  }
  if (!matched) accountSel.selectedIndex = 0
  accountSel.dispatchEvent(new Event('change'))

  if (type === 'miio' && miioId) miioDeviceId.value = miioId

  scanModal.hide()
  bootstrap.Modal.getOrCreateInstance(document.getElementById('addDeviceModal')).show()
})

// ── Init ──────────────────────────────────────────────────────────────────────

async function loadAll() {
  await loadAccounts(onUnauth)
  await loadDevices(onUnauth)
}

;(async () => {
  if (getToken() && await verifyToken()) { showAdmin() }
  else { showLogin('') }
})()
