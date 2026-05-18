'use strict'

// ── Auth / view switching ────────────────────────────────────────────────────

function getToken() {
  return sessionStorage.getItem('adminToken') || ''
}

function showLogin(errMsg) {
  document.getElementById('adminView').style.display = 'none'
  document.getElementById('loginView').style.display = 'flex'
  document.getElementById('loginErr').textContent = errMsg || ''
  document.getElementById('loginBtn').disabled = false
}

function showAdmin() {
  document.getElementById('loginView').style.display = 'none'
  document.getElementById('adminView').style.display = 'block'
  loadAll()
}

async function doLogin() {
  const input = document.getElementById('tokenInput')
  const token = input.value.trim()
  if (!token) return

  document.getElementById('loginBtn').disabled = true
  document.getElementById('loginErr').textContent = ''

  sessionStorage.setItem('adminToken', token)
  if (await verifyToken()) {
    showAdmin()
  } else {
    sessionStorage.removeItem('adminToken')
    showLogin('Invalid token.')
  }
}

function doLogout() {
  sessionStorage.removeItem('adminToken')
  document.getElementById('tokenInput').value = ''
  showLogin('')
}

async function verifyToken() {
  try {
    const res = await fetch('/api/v1/admin/accounts', { headers: authHeaders() })
    return res.ok
  } catch (_) {
    return false
  }
}

// ── Init ─────────────────────────────────────────────────────────────────────

;(async () => {
  if (getToken() && await verifyToken()) { showAdmin(); return }
  showLogin('')
})()

document.getElementById('tokenInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') doLogin()
})

// ── API helpers ──────────────────────────────────────────────────────────────

function authHeaders() {
  return { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` }
}

async function api(method, path, body) {
  const opts = { method, headers: authHeaders() }
  if (body !== undefined) opts.body = JSON.stringify(body)
  const res = await fetch(path, opts)
  if (res.status === 401) { showLogin('Session expired. Please sign in again.'); throw new Error('Unauthorized') }
  if (res.status === 204) return null
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
  return data
}

// ── Bootstrap Toast notifications ────────────────────────────────────────────

function flash(msg, ok) {
  const container = document.getElementById('toastContainer')
  const div = document.createElement('div')
  div.className = `toast align-items-center text-bg-${ok ? 'success' : 'danger'} border-0`
  div.setAttribute('role', 'alert')
  div.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">${esc(msg)}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
    </div>`
  container.appendChild(div)
  const toast = new bootstrap.Toast(div, { delay: 3000 })
  toast.show()
  div.addEventListener('hidden.bs.toast', () => div.remove())
}

// ── Accounts ─────────────────────────────────────────────────────────────────

let accountsCache = []

async function loadAccounts() {
  try {
    accountsCache = await api('GET', '/api/v1/admin/accounts')
    renderAccounts()
    populateAccountSelect()
  } catch (e) {
    if (e.message !== 'Unauthorized') flash(`Failed to load accounts: ${e.message}`, false)
  }
}

function renderAccounts() {
  const tbody = document.querySelector('#accountsTable tbody')
  if (!accountsCache.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3">No accounts yet.</td></tr>'
    return
  }
  tbody.innerHTML = accountsCache.map(a => `
    <tr>
      <td class="text-muted">${a.id}</td>
      <td><span class="badge bg-secondary">${a.type}</span></td>
      <td>${esc(a.label)}</td>
      <td class="font-monospace small">${esc(a.username)}</td>
      <td class="text-end">
        <button class="btn btn-sm btn-outline-danger" onclick="deleteAccount(${a.id})">
          <i class="bi bi-trash"></i>
        </button>
      </td>
    </tr>`).join('')
}

function populateAccountSelect() {
  const sel = document.getElementById('accountSelect')
  const current = sel.value
  sel.innerHTML = '<option value="">— none —</option>' +
    accountsCache.map(a => `<option value="${a.id}">${esc(a.label)} (${a.type})</option>`).join('')
  sel.value = current
}

async function addAccount(e) {
  e.preventDefault()
  const form = e.target
  try {
    await api('POST', '/api/v1/admin/accounts', {
      type: form.type.value, label: form.label.value,
      username: form.username.value, password: form.password.value,
    })
    flash('Account added', true)
    form.reset()
    await loadAccounts()
  } catch (err) {
    if (err.message !== 'Unauthorized') flash(`Failed to add account: ${err.message}`, false)
  }
}

async function deleteAccount(id) {
  if (!confirm(`Delete account ${id}?`)) return
  try {
    await api('DELETE', `/api/v1/admin/accounts/${id}`)
    flash('Account deleted', true)
    await loadAccounts()
  } catch (err) {
    if (err.message !== 'Unauthorized') flash(`Delete failed: ${err.message}`, false)
  }
}

// ── Devices ──────────────────────────────────────────────────────────────────

async function loadDevices() {
  try {
    const devices = await api('GET', '/api/v1/admin/devices')
    renderDevices(devices)
  } catch (e) {
    if (e.message !== 'Unauthorized') flash(`Failed to load devices: ${e.message}`, false)
  }
}

function renderDevices(devices) {
  const tbody = document.querySelector('#devicesTable tbody')
  if (!devices.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">No devices yet.</td></tr>'
    return
  }
  tbody.innerHTML = devices.map(d => {
    const outletCell = d.is_strip
      ? `<button class="btn btn-sm btn-outline-secondary" type="button"
           data-bs-toggle="collapse" data-bs-target="#outlets-${d.id}">
           <i class="bi bi-diagram-3"></i>
         </button>
         <div class="collapse mt-1" id="outlets-${d.id}">
           <div class="outlet-list" id="outlet-list-${d.id}">
             <span class="text-muted small">Loading…</span>
           </div>
         </div>`
      : '<span class="text-muted">—</span>'
    return `
      <tr>
        <td>
          <div class="d-flex gap-1 align-items-center">
            <input id="name-${d.id}" class="form-control form-control-sm inline-input" value="${esc(d.name)}">
            <button class="btn btn-sm btn-outline-secondary" onclick="renameDevice('${d.id}')">
              <i class="bi bi-check-lg"></i>
            </button>
          </div>
        </td>
        <td><span class="badge bg-secondary">${d.type}</span></td>
        <td class="font-monospace small text-muted">${d.mac}</td>
        <td class="small">${esc(d.group_name || '—')}</td>
        <td class="small text-muted">${esc(d.last_known_ip || '—')}</td>
        <td>${outletCell}</td>
        <td class="text-end">
          <button class="btn btn-sm btn-outline-danger" onclick="deleteDevice('${d.id}')">
            <i class="bi bi-trash"></i>
          </button>
        </td>
      </tr>`
  }).join('')

  // Load outlets after render, triggered on first expand
  devices.filter(d => d.is_strip).forEach(d => {
    const collapseEl = document.getElementById(`outlets-${d.id}`)
    if (!collapseEl) return
    collapseEl.addEventListener('show.bs.collapse', () => loadOutlets(d.id), { once: true })
  })
}

async function loadOutlets(deviceId) {
  try {
    const device = await api('GET', `/api/v1/devices/${deviceId}`)
    const el = document.getElementById(`outlet-list-${deviceId}`)
    if (!el || !device.children) return
    el.innerHTML = device.children.map(c => `
      <div class="outlet-row">
        <span class="outlet-id">${c.id}</span>
        <input id="ol-${deviceId}-${c.id}" class="form-control form-control-sm" style="width:140px" value="${esc(c.alias || c.id)}">
        <button class="btn btn-sm btn-outline-secondary" onclick="renameOutlet('${deviceId}','${c.id}')">
          <i class="bi bi-check-lg"></i>
        </button>
      </div>`).join('')
  } catch (_) {}
}

async function addDevice(e) {
  e.preventDefault()
  const form = e.target
  const accountVal = form.account_id.value
  try {
    const result = await api('POST', '/api/v1/admin/devices', {
      mac: form.mac.value, name: form.name.value, type: form.type.value,
      broadcast: form.broadcast.value,
      group_name: form.group_name.value || null,
      account_id: accountVal ? parseInt(accountVal) : null,
      token: form.token?.value || null,
      miio_id: form.miio_id?.value || null,
    })
    flash(`Device added (id: ${result.id})`, true)
    form.reset()
    onTypeChange('kasa')
    await loadDevices()
  } catch (err) {
    if (err.message !== 'Unauthorized') flash(`Failed to add device: ${err.message}`, false)
  }
}

async function deleteDevice(id) {
  if (!confirm(`Delete device ${id}?`)) return
  try {
    await api('DELETE', `/api/v1/admin/devices/${id}`)
    flash('Device deleted', true)
    await loadDevices()
  } catch (err) {
    if (err.message !== 'Unauthorized') flash(`Delete failed: ${err.message}`, false)
  }
}

async function renameDevice(id) {
  const input = document.getElementById(`name-${id}`)
  if (!input) return
  try {
    await api('PATCH', `/api/v1/admin/devices/${id}/name`, { new_name: input.value })
    flash('Device name updated', true)
  } catch (err) {
    if (err.message !== 'Unauthorized') flash(`Rename failed: ${err.message}`, false)
  }
}

async function renameOutlet(deviceId, outletId) {
  const input = document.getElementById(`ol-${deviceId}-${outletId}`)
  if (!input) return
  try {
    await api('PATCH', `/api/v1/admin/devices/${deviceId}/outlets/${outletId}/label`, {
      new_name: input.value,
    })
    flash('Outlet label updated', true)
  } catch (err) {
    if (err.message !== 'Unauthorized') flash(`Rename failed: ${err.message}`, false)
  }
}

// ── UI helpers ───────────────────────────────────────────────────────────────

function onTypeChange(type) {
  document.getElementById('miioFields').hidden = type !== 'miio'
}

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

async function loadAll() {
  await loadAccounts()
  await loadDevices()
}
