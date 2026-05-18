function esc(str) {
  const d = document.createElement('div')
  d.textContent = str ?? ''
  return d.innerHTML
}

export function renderTabs(devices, activeGroup, onSelect) {
  const container = document.getElementById('tabs-nav')
  const groups = [...new Set(devices.filter(d => d.group_name).map(d => d.group_name))]
  if (!groups.length) { container.innerHTML = ''; return }

  const tabs = [{ id: 'all', label: 'All', count: devices.length },
    ...groups.map(g => ({ id: g, label: g, count: devices.filter(d => d.group_name === g).length }))]

  container.innerHTML = `<ul class="nav nav-tabs">${tabs.map(t => `
    <li class="nav-item">
      <button class="nav-link ${activeGroup === t.id ? 'active' : ''}" data-group="${esc(t.id)}">
        ${esc(t.label)} <span class="badge text-bg-secondary ms-1">${t.count}</span>
      </button>
    </li>`).join('')}</ul>`

  container.querySelectorAll('[data-group]').forEach(btn =>
    btn.addEventListener('click', () => onSelect(btn.dataset.group))
  )
}

export function renderDevices(devices, searchQuery, activeGroup, onToggle, onRefresh) {
  const container = document.getElementById('devices-container')
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
    container.innerHTML = '<p class="text-muted text-center py-5">No devices found.</p>'
    return
  }

  container.innerHTML = filtered.map(d => _deviceCard(d)).join('')

  filtered.forEach(d => {
    const card = container.querySelector(`[data-device-id="${d.id}"]`)
    if (!card) return

    // whole-device toggle (non-strip)
    const mainToggle = card.querySelector('.main-toggle')
    mainToggle?.addEventListener('click', () => onToggle(d.id, null, !d.is_on))

    // per-outlet toggles
    card.querySelectorAll('[data-outlet-id]').forEach(btn => {
      const outlet = d.outlets.find(o => o.outlet_id === btn.dataset.outletId)
      btn.addEventListener('click', () => onToggle(d.id, btn.dataset.outletId, !outlet?.is_on))
    })

    // refresh
    card.querySelector('.refresh-btn')?.addEventListener('click', () => onRefresh(d.id))
  })
}

function _deviceCard(d) {
  const statusBadge = d.is_online
    ? '<span class="badge text-bg-success">Online</span>'
    : '<span class="badge text-bg-secondary">Offline</span>'

  const refreshBtn = !d.is_online
    ? `<button class="btn btn-sm btn-outline-secondary refresh-btn" title="Refresh">
         <i class="bi bi-arrow-clockwise"></i>
       </button>`
    : ''

  const body = d.is_strip
    ? _outletList(d.outlets, d.is_online)
    : _mainToggle(d.is_on, d.is_online)

  return `
    <div class="card mb-3" data-device-id="${d.id}">
      <div class="card-header d-flex justify-content-between align-items-center">
        <div>
          <div class="fw-semibold">${esc(d.name)}</div>
          ${d.model ? `<div class="text-muted small">${esc(d.model)}</div>` : ''}
        </div>
        <div class="d-flex align-items-center gap-2">
          ${statusBadge}
          ${refreshBtn}
        </div>
      </div>
      <div class="card-body p-0">${body}</div>
    </div>`
}

function _mainToggle(isOn, isOnline) {
  return `
    <div class="d-flex align-items-center justify-content-center p-3">
      <div class="form-check form-switch fs-4 mb-0">
        <input class="form-check-input main-toggle" type="checkbox" role="switch"
          ${isOn ? 'checked' : ''} ${!isOnline ? 'disabled' : ''}>
      </div>
    </div>`
}

function _outletList(outlets, isOnline) {
  if (!outlets.length) return '<p class="text-muted text-center p-3 mb-0">No outlets</p>'
  return outlets.map(o => `
    <div class="d-flex align-items-center justify-content-between px-3 py-2 border-bottom">
      <span>${esc(o.name)}</span>
      <div class="form-check form-switch mb-0">
        <input class="form-check-input" type="checkbox" role="switch"
          data-outlet-id="${esc(o.outlet_id)}"
          ${o.is_on ? 'checked' : ''} ${!isOnline ? 'disabled' : ''}>
      </div>
    </div>`).join('')
}
