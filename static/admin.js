import { getToken, setToken, clearToken, verifyToken } from './js/admin/auth.js'
import * as adminApi from './js/admin/api.js'
import { loadAccounts, getCache as getAccounts, populateAccountSelect } from './js/admin/accounts.js'
import { loadDevices, openOutletsModal, renameDevice, renameOutlet, confirmDelete } from './js/admin/devices.js'

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
  const d = document.createElement('div'); d.textContent = str ?? ''; return d.innerHTML
}

// ── Auth ──────────────────────────────────────────────────────────────────────

function showLogin(err) {
  document.getElementById('adminView').style.display = 'none'
  document.getElementById('loginView').style.display = 'flex'
  document.getElementById('loginErr').textContent = err || ''
  document.getElementById('loginBtn').disabled = false
}

function showAdmin() {
  document.getElementById('loginView').style.display = 'none'
  document.getElementById('adminView').style.display = 'block'
  loadAll()
}

const onUnauth = () => showLogin('Session expired. Please sign in again.')

document.getElementById('loginBtn').addEventListener('click', async () => {
  const input = document.getElementById('tokenInput')
  const token = input.value.trim()
  if (!token) return
  document.getElementById('loginBtn').disabled = true
  document.getElementById('loginErr').textContent = ''
  setToken(token)
  if (await verifyToken()) { showAdmin() }
  else { clearToken(); showLogin('Invalid token.') }
})

document.getElementById('tokenInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('loginBtn').click()
})

document.getElementById('logoutBtn').addEventListener('click', () => {
  clearToken()
  document.getElementById('tokenInput').value = ''
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

const accountSel = document.getElementById('accountSelect')
accountSel.addEventListener('change', () => {
  const type = accountSel.options[accountSel.selectedIndex]?.dataset.type
  document.getElementById('miioFields').hidden = type !== 'miio'
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
    flash('Device added — probing in background…')
    await loadDevices(onUnauth)
  } catch (err) {
    if (err.status !== 401) flash(err.message, false)
  }
})

document.getElementById('devicesTable').addEventListener('click', async e => {
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
  if (rename) { await renameDevice(rename.dataset.id, flash); return }

  const outlets = e.target.closest('.js-outlets')
  if (outlets) { await openOutletsModal(outlets.dataset.id, outlets.dataset.name) }
})

document.getElementById('outletsModalBody').addEventListener('click', async e => {
  const btn = e.target.closest('.js-rename-outlet')
  if (btn) await renameOutlet(btn.dataset.deviceId, btn.dataset.outletId, flash)
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
