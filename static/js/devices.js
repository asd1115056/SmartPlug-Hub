function esc(str) {
  const d = document.createElement('div')
  d.textContent = str ?? ''
  return d.innerHTML
}

export function renderTabs(devices, activeGroup, searchQuery, onSelect) {
  const container = document.getElementById('tabs-nav')
  const groups = [...new Set(devices.filter(d => d.group_name).map(d => d.group_name))]
  if (!devices.length) { container.innerHTML = ''; return }

  const effectiveActive = searchQuery ? 'all' : activeGroup
  const tabs = [
    { id: 'all', label: 'All', count: devices.length },
    ...groups.map(g => ({ id: g, label: g, count: devices.filter(d => d.group_name === g).length })),
  ]

  container.innerHTML = `<ul class="nav nav-tabs">${tabs.map(t => `
    <li class="nav-item">
      <button class="nav-link ${effectiveActive === t.id ? 'active' : ''}" data-group="${esc(t.id)}">
        ${esc(t.label)} <span class="badge text-bg-secondary ms-1">${t.count}</span>
      </button>
    </li>`).join('')}</ul>`

  container.querySelectorAll('[data-group]').forEach(btn =>
    btn.addEventListener('click', () => onSelect(btn.dataset.group))
  )
}

export function renderDevices(devices, searchQuery, activeGroup) {
  const container = document.getElementById('devices-container')

  if (!devices.length) {
    container.innerHTML = `
      <div class="alert alert-info">
        <strong>No devices.</strong> Add devices from the <a href="/admin">Admin panel</a>.
      </div>`
    return
  }

  let filtered = devices
  if (searchQuery) {
    const q = searchQuery.toLowerCase()
    filtered = devices.filter(d =>
      d.name.toLowerCase().includes(q) ||
      d.outlets.some(o => o.name.toLowerCase().includes(q))
    )
  } else if (activeGroup !== 'all') {
    filtered = devices.filter(d => d.group_name === activeGroup)
  }

  if (!filtered.length) {
    container.innerHTML = '<p class="text-muted py-3">No matching devices.</p>'
    return
  }

  container.innerHTML = `<div class="row g-3">${filtered.map(d => `
    <div class="col-lg-4 col-md-6">
      ${_deviceCard(d)}
    </div>`).join('')}</div>`
}

function _deviceCard(d) {
  const stateClass = d.is_online ? 'state-online' : 'state-offline'
  const body = d.is_strip ? _outletList(d.id, d.outlets, d.is_online) : _mainToggle(d.id, d.is_on, d.is_online)
  const refreshBtn = !d.is_online
    ? `<button class="btn btn-sm refresh-btn" data-device-id="${d.id}" title="Refresh">
         <i class="bi bi-arrow-clockwise"></i>
       </button>`
    : ''

  return `
    <div class="card device-card h-100 ${stateClass}" data-device-id="${d.id}">
      <div class="card-header d-flex justify-content-between align-items-center">
        <div>
          <div class="fw-semibold">${esc(d.name)}</div>
          ${d.model ? `<div class="device-model">${esc(d.model)}</div>` : ''}
          ${d.last_updated ? `<div class="device-model">Last updated: ${_fmtTime(d.last_updated)}</div>` : ''}
        </div>
        ${refreshBtn}
      </div>
      <div class="card-body p-0">${body}</div>
    </div>`
}

function _mainToggle(deviceId, isOn, isOnline) {
  const onClass      = isOn ? 'is-on' : ''
  const action       = isOn ? 'off' : 'on'
  const disabledAttr = isOnline ? '' : 'disabled'
  return `
    <div class="single-device-control">
      <button class="toggle-switch ${onClass}"
        data-device-id="${deviceId}" data-action="${action}" ${disabledAttr}></button>
    </div>`
}

function _fmtTime(iso) {
  try {
    const date = new Date(iso)
    const offsetMin = -date.getTimezoneOffset()
    const sign = offsetMin >= 0 ? '+' : '-'
    const absMin = Math.abs(offsetMin)
    const hours = Math.floor(absMin / 60)
    const mins = absMin % 60
    const offset = mins ? `${hours}:${String(mins).padStart(2, '0')}` : `${hours}`
    return `${date.toLocaleTimeString(undefined, { hour12: true })} UTC${sign}${offset}`
  } catch { return '' }
}

function _outletList(deviceId, outlets, isOnline) {
  if (!outlets.length) return '<p class="text-muted text-center p-3 mb-0">No outlets</p>'
  const disabledAttr = isOnline ? '' : 'disabled'
  return outlets.map(o => {
    const onClass = o.is_on ? 'is-on' : ''
    const action  = o.is_on ? 'off' : 'on'
    return `
      <div class="child-outlet ${onClass}">
        <span class="outlet-name">${esc(o.name)}</span>
        <button class="toggle-switch ${onClass}"
          data-device-id="${deviceId}" data-outlet-id="${esc(o.outlet_id)}"
          data-action="${action}" ${disabledAttr}></button>
      </div>`
  }).join('')
}
