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

// ── Delete confirmation modal ─────────────────────────────────────────────────

function confirmDelete(message) {
  return new Promise(resolve => {
    const modalEl = document.getElementById('deleteModal')
    const btn = document.getElementById('deleteConfirmBtn')
    document.getElementById('deleteModalBody').textContent = message

    const modal = bootstrap.Modal.getOrCreateInstance(modalEl)

    function onConfirm() {
      cleanup()
      resolve(true)
    }
    function onDismiss() {
      cleanup()
      resolve(false)
    }
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
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">No accounts yet.</td></tr>'
    return
  }
  tbody.innerHTML = accountsCache.map(a => `
    <tr>
      <td class="text-muted">${a.id}</td>
      <td><span class="badge bg-secondary">${a.type}</span></td>
      <td class="font-monospace">${esc(a.username)}</td>
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
    accountsCache.map(a => `<option value="${a.id}" data-type="${a.type}">${esc(a.username)}</option>`).join('')
  sel.value = current
  syncTypeFromAccount()
}

function syncTypeFromAccount() {
  const accountSel = document.getElementById('accountSelect')
  const accountType = accountSel.options[accountSel.selectedIndex]?.dataset.type
  onTypeChange(accountType || 'kasa')
}

async function addAccount(e) {
  e.preventDefault()
  const form = e.target
  try {
    await api('POST', '/api/v1/admin/accounts', {
      type: form.type.value,
      username: form.username.value, password: form.password.value,
    })
    bootstrap.Modal.getInstance(document.getElementById('addAccountModal')).hide()
    form.reset()
    flash('Account added', true)
    await loadAccounts()
  } catch (err) {
    if (err.message !== 'Unauthorized') flash(`Failed to add account: ${err.message}`, false)
  }
}

async function deleteAccount(id) {
  if (!await confirmDelete(`Delete account ${id}? Devices using it will lose their credentials.`)) return
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
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4">No devices yet.</td></tr>'
    return
  }
  tbody.innerHTML = devices.map(d => {
    const outletCell = d.is_strip
      ? `<button class="btn btn-sm btn-outline-secondary"
           data-device-id="${d.id}" data-device-name="${esc(d.name)}"
           onclick="openOutletsModal(this.dataset.deviceId, this.dataset.deviceName)">
           <i class="bi bi-diagram-3"></i>
         </button>`
      : '<span class="text-muted">—</span>'
    return `
      <tr>
        <td>
          <div class="d-flex gap-1 align-items-center">
            <input id="name-${d.id}" class="form-control inline-input" value="${esc(d.name)}">
            <button class="btn btn-sm btn-outline-secondary" onclick="renameDevice('${d.id}')">
              <i class="bi bi-check-lg"></i>
            </button>
          </div>
        </td>
        <td><span class="badge bg-secondary">${d.type}</span></td>
        <td class="font-monospace text-muted">${d.mac}</td>
        <td>${esc(d.group_name || '—')}</td>
        <td class="text-muted">${esc(d.last_known_ip || '—')}</td>
        <td>${outletCell}</td>
        <td class="text-end">
          <button class="btn btn-sm btn-outline-danger" onclick="deleteDevice('${d.id}')">
            <i class="bi bi-trash"></i>
          </button>
        </td>
      </tr>`
  }).join('')

}

async function openOutletsModal(deviceId, deviceName) {
  const modalEl = document.getElementById('outletsModal')
  const bodyEl = document.getElementById('outletsModalBody')
  document.getElementById('outletsModalTitle').innerHTML =
    `<i class="bi bi-diagram-3 me-2"></i>Outlets — ${esc(deviceName)}`
  bodyEl.innerHTML = `
    <div class="text-center py-3">
      <div class="spinner-border spinner-border-sm text-secondary" role="status"></div>
    </div>`

  bootstrap.Modal.getOrCreateInstance(modalEl).show()

  try {
    const device = await api('GET', `/api/v1/devices/${deviceId}`)
    if (!device.children?.length) {
      bodyEl.innerHTML = '<p class="text-muted mb-0">No outlets found.</p>'
      return
    }
    bodyEl.innerHTML = device.children.map((c, i) => `
      <div class="outlet-row">
        <span class="outlet-id">${i}</span>
        <input id="ol-${deviceId}-${c.id}" class="form-control flex-grow-1" value="${esc(c.alias || c.id)}">
        <button class="btn btn-sm btn-outline-secondary" onclick="renameOutlet('${deviceId}','${c.id}')">
          <i class="bi bi-check-lg"></i>
        </button>
      </div>`).join('')
  } catch (e) {
    bodyEl.innerHTML = `<p class="text-danger mb-0">Failed to load outlets: ${esc(e.message)}</p>`
  }
}

async function addDevice(e) {
  e.preventDefault()
  const form = e.target
  const accountVal = form.account_id.value
  try {
    const accountSel = document.getElementById('accountSelect')
    const type = accountSel.options[accountSel.selectedIndex]?.dataset.type || 'kasa'
    const result = await api('POST', '/api/v1/admin/devices', {
      mac: form.mac.value, name: form.name.value, type,
      broadcast: form.broadcast.value,
      group_name: form.group_name.value || null,
      account_id: accountVal ? parseInt(accountVal) : null,
      token: form.token?.value || null,
      miio_id: form.miio_id?.value || null,
    })
    bootstrap.Modal.getInstance(document.getElementById('addDeviceModal')).hide()
    form.reset()
    onTypeChange('kasa')
    flash(`Device added (id: ${result.id})`, true)
    await loadDevices()
  } catch (err) {
    if (err.message !== 'Unauthorized') flash(`Failed to add device: ${err.message}`, false)
  }
}

async function deleteDevice(id) {
  if (!await confirmDelete(`Delete this device? This cannot be undone.`)) return
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
