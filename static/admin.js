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
  const ok = await verifyToken()
  if (ok) {
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

// ── Init: check existing token on page load ───────────────────────────────────

;(async () => {
  if (getToken()) {
    const ok = await verifyToken()
    if (ok) { showAdmin(); return }
  }
  showLogin('')
})()

// Pressing Enter in the token input triggers login
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

// ── Flash notifications ──────────────────────────────────────────────────────

let _flashTimer = null

function flash(msg, ok) {
  const el = document.getElementById('flashMsg')
  el.textContent = msg
  el.className = `show ${ok ? 'ok' : 'err'}`
  clearTimeout(_flashTimer)
  _flashTimer = setTimeout(() => { el.className = '' }, 2800)
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
    tbody.innerHTML = '<tr class="empty-row"><td colspan="5">No accounts yet.</td></tr>'
    return
  }
  tbody.innerHTML = accountsCache.map(a => `
    <tr>
      <td>${a.id}</td>
      <td>${a.type}</td>
      <td>${esc(a.label)}</td>
      <td>${esc(a.username)}</td>
      <td><button class="btn btn-danger btn-sm" onclick="deleteAccount(${a.id})">Delete</button></td>
    </tr>
  `).join('')
}

function populateAccountSelect() {
  const sel = document.getElementById('accountSelect')
  const current = sel.value
  sel.innerHTML = '<option value="">— No account —</option>' +
    accountsCache.map(a => `<option value="${a.id}">${esc(a.label)} (${a.type})</option>`).join('')
  sel.value = current
}

async function addAccount(e) {
  e.preventDefault()
  const form = e.target
  try {
    await api('POST', '/api/v1/admin/accounts', {
      type: form.type.value,
      label: form.label.value,
      username: form.username.value,
      password: form.password.value,
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
    tbody.innerHTML = '<tr class="empty-row"><td colspan="7">No devices yet.</td></tr>'
    return
  }
  tbody.innerHTML = devices.map(d => {
    const outletCell = d.is_strip
      ? `<details><summary>Show outlets</summary>
           <div class="outlet-list" id="outlets-${d.id}">Loading…</div>
         </details>`
      : '—'
    return `
      <tr>
        <td>
          <div class="inline-edit">
            <input id="name-${d.id}" value="${esc(d.name)}">
            <button class="btn btn-ghost btn-sm" onclick="renameDevice('${d.id}')">Save</button>
          </div>
        </td>
        <td>${d.type}</td>
        <td style="font-family:monospace;font-size:0.8rem">${d.mac}</td>
        <td>${esc(d.group_name || '—')}</td>
        <td style="font-size:0.8rem;color:#718096">${esc(d.last_known_ip || '—')}</td>
        <td>${outletCell}</td>
        <td><button class="btn btn-danger btn-sm" onclick="deleteDevice('${d.id}')">Delete</button></td>
      </tr>
    `
  }).join('')

  devices.filter(d => d.is_strip).forEach(d => loadOutlets(d.id))
}

async function loadOutlets(deviceId) {
  try {
    const device = await api('GET', `/api/v1/devices/${deviceId}`)
    const el = document.getElementById(`outlets-${deviceId}`)
    if (!el || !device.children) return
    el.innerHTML = device.children.map(c => `
      <div class="outlet-row">
        <span class="outlet-id">${c.id}</span>
        <input id="ol-${deviceId}-${c.id}" value="${esc(c.alias || c.id)}" style="width:120px">
        <button class="btn btn-ghost btn-sm" onclick="renameOutlet('${deviceId}','${c.id}')">Save</button>
      </div>
    `).join('')
  } catch (_) {}
}

async function addDevice(e) {
  e.preventDefault()
  const form = e.target
  const accountVal = form.account_id.value
  try {
    const result = await api('POST', '/api/v1/admin/devices', {
      mac: form.mac.value,
      name: form.name.value,
      type: form.type.value,
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
