'use strict'

// ── Token management ─────────────────────────────────────────────────────────

function getToken() {
  return sessionStorage.getItem('adminToken') || ''
}

function saveToken() {
  const val = document.getElementById('tokenInput').value.trim()
  sessionStorage.setItem('adminToken', val)
  setStatus('Token saved', true)
  loadAll()
}

function clearToken() {
  sessionStorage.removeItem('adminToken')
  document.getElementById('tokenInput').value = ''
  setStatus('Token cleared', false)
}

function authHeaders() {
  return { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` }
}

function setStatus(msg, ok) {
  const el = document.getElementById('status')
  el.textContent = msg
  el.className = ok ? 'status-ok' : 'status-err'
}

// ── API helpers ──────────────────────────────────────────────────────────────

async function api(method, path, body) {
  const opts = { method, headers: authHeaders() }
  if (body !== undefined) opts.body = JSON.stringify(body)
  const res = await fetch(path, opts)
  if (res.status === 204) return null
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
  return data
}

// ── Accounts ─────────────────────────────────────────────────────────────────

let accountsCache = []

async function loadAccounts() {
  try {
    accountsCache = await api('GET', '/api/v1/admin/accounts')
    renderAccounts()
    populateAccountSelect()
  } catch (e) {
    setStatus(`Failed to load accounts: ${e.message}`, false)
  }
}

function renderAccounts() {
  const tbody = document.querySelector('#accountsTable tbody')
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
  const body = {
    type: form.type.value,
    label: form.label.value,
    username: form.username.value,
    password: form.password.value,
  }
  try {
    await api('POST', '/api/v1/admin/accounts', body)
    setStatus('Account added', true)
    form.reset()
    await loadAccounts()
  } catch (err) {
    setStatus(`Failed to add account: ${err.message}`, false)
  }
}

async function deleteAccount(id) {
  if (!confirm(`Delete account ${id}?`)) return
  try {
    await api('DELETE', `/api/v1/admin/accounts/${id}`)
    setStatus('Account deleted', true)
    await loadAccounts()
  } catch (err) {
    setStatus(`Delete failed: ${err.message}`, false)
  }
}

// ── Devices ──────────────────────────────────────────────────────────────────

async function loadDevices() {
  try {
    const devices = await api('GET', '/api/v1/admin/devices')
    renderDevices(devices)
  } catch (e) {
    setStatus(`Failed to load devices: ${e.message}`, false)
  }
}

function renderDevices(devices) {
  const tbody = document.querySelector('#devicesTable tbody')
  tbody.innerHTML = devices.map(d => {
    const outletHtml = d.is_strip
      ? `<details><summary>Outlets</summary>
          <div class="outlet-list" id="outlets-${d.id}">Loading…</div>
         </details>`
      : '—'
    return `
      <tr>
        <td>
          <div class="inline-edit">
            <input id="name-${d.id}" value="${esc(d.name)}" style="width:120px">
            <button class="btn btn-sm" onclick="renameDevice('${d.id}')">Rename</button>
          </div>
        </td>
        <td>${d.type}</td>
        <td style="font-size:0.8rem;font-family:monospace">${d.mac}</td>
        <td>${esc(d.group_name || '')}</td>
        <td style="font-size:0.8rem">${esc(d.last_known_ip || '—')}</td>
        <td>${outletHtml}</td>
        <td><button class="btn btn-danger btn-sm" onclick="deleteDevice('${d.id}')">Delete</button></td>
      </tr>
    `
  }).join('')

  devices.filter(d => d.is_strip).forEach(d => loadOutlets(d.id))
}

async function loadOutlets(deviceId) {
  try {
    const res = await fetch(`/api/v1/devices/${deviceId}`, { headers: authHeaders() })
    if (!res.ok) return
    const device = await res.json()
    const el = document.getElementById(`outlets-${deviceId}`)
    if (!el || !device.children) return
    el.innerHTML = device.children.map(c => `
      <div class="outlet-row">
        <span>${c.id}</span>
        <input id="ol-${deviceId}-${c.id}" value="${esc(c.alias || c.id)}" style="width:120px">
        <button class="btn btn-sm" onclick="renameOutlet('${deviceId}', '${c.id}')">Rename</button>
      </div>
    `).join('')
  } catch (_) {}
}

async function addDevice(e) {
  e.preventDefault()
  const form = e.target
  const accountVal = form.account_id.value
  const body = {
    mac: form.mac.value,
    name: form.name.value,
    type: form.type.value,
    broadcast: form.broadcast.value,
    group_name: form.group_name.value || null,
    account_id: accountVal ? parseInt(accountVal) : null,
    token: form.token?.value || null,
    miio_id: form.miio_id?.value || null,
  }
  try {
    const result = await api('POST', '/api/v1/admin/devices', body)
    setStatus(`Device added (id: ${result.id})`, true)
    form.reset()
    onTypeChange('kasa')
    await loadDevices()
  } catch (err) {
    setStatus(`Failed to add device: ${err.message}`, false)
  }
}

async function deleteDevice(id) {
  if (!confirm(`Delete device ${id}?`)) return
  try {
    await api('DELETE', `/api/v1/admin/devices/${id}`)
    setStatus('Device deleted', true)
    await loadDevices()
  } catch (err) {
    setStatus(`Delete failed: ${err.message}`, false)
  }
}

async function renameDevice(id) {
  const input = document.getElementById(`name-${id}`)
  if (!input) return
  try {
    await api('PATCH', `/api/v1/admin/devices/${id}/name`, { new_name: input.value })
    setStatus('Device name updated', true)
  } catch (err) {
    setStatus(`Rename failed: ${err.message}`, false)
  }
}

async function renameOutlet(deviceId, outletId) {
  const input = document.getElementById(`ol-${deviceId}-${outletId}`)
  if (!input) return
  try {
    await api('PATCH', `/api/v1/admin/devices/${deviceId}/outlets/${outletId}/label`, {
      new_name: input.value,
    })
    setStatus('Outlet label updated', true)
  } catch (err) {
    setStatus(`Rename failed: ${err.message}`, false)
  }
}

// ── UI helpers ───────────────────────────────────────────────────────────────

function onTypeChange(type) {
  const miioFields = document.getElementById('miioFields')
  if (type === 'miio') {
    miioFields.removeAttribute('data-hide')
  } else {
    miioFields.setAttribute('data-hide', '')
  }
}

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

async function loadAll() {
  await loadAccounts()
  await loadDevices()
}

// ── Init ─────────────────────────────────────────────────────────────────────

const stored = getToken()
if (stored) document.getElementById('tokenInput').value = stored

loadAll()
