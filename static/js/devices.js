function esc(str) {
  const d = document.createElement('div')
  d.textContent = str ?? ''
  return d.innerHTML.replaceAll('"', '&quot;')
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

  const singles = filtered.filter(d => !d.is_strip)
  const strips  = filtered.filter(d => d.is_strip)
  const showLabels = singles.length > 0 && strips.length > 0

  let html = ''
  if (singles.length) {
    html += showLabels ? '<div class="section-label">Single plugs</div>' : ''
    html += `<div class="row g-3 ${strips.length ? 'mb-4' : ''}">${singles.map(d => `
      <div class="col-12 col-md-6">${_deviceCard(d)}</div>`).join('')}</div>`
  }
  if (strips.length) {
    html += showLabels ? '<div class="section-label mt-2">Power strips</div>' : ''
    html += `<div class="row g-3">${strips.map(d => `
      <div class="col-12 col-md-6">${_deviceCard(d)}</div>`).join('')}</div>`
  }

  container.innerHTML = html
}

function _protocolBadge(type) {
  return `<span class="protocol-badge type-${esc(type)}">${esc(type)}</span>`
}

function _deviceHeader(d) {
  const totalWatts = d.is_online ? _headerWatts(d) : null
  const wattsHtml = totalWatts !== null
    ? `<div class="device-watts"><i class="bi bi-lightning-charge-fill me-1"></i>${_fmtWatts(totalWatts)}</div>`
    : ''
  const refreshBtn = !d.is_online
    ? `<button class="btn btn-sm refresh-btn" data-device-id="${d.id}" title="Refresh">
         <i class="bi bi-arrow-clockwise"></i>
       </button>`
    : ''
  const abs = d.last_updated ? _fmtTime(d.last_updated) : ''
  const timeLabel = d.is_online ? 'Last updated' : 'Last seen'
  const timeHtml = d.last_updated
    ? `<div style="font-size:.72rem;opacity:.4;margin-top:.1rem">
         <span class="${d.is_online ? 'js-last-updated' : 'js-offline-ago'}"
           data-ts="${d.last_updated}" title="${abs}">
           ${timeLabel} ${_fmtAgo(d.last_updated)}
         </span>
       </div>`
    : ''
  const modelHtml = (d.model || d.type)
    ? `<div style="font-size:.8rem;margin-top:.15rem;display:flex;align-items:center;gap:.4rem">
         ${d.model ? `<span style="opacity:.8">${esc(d.model)}</span>` : ''}
         ${_protocolBadge(d.type)}
       </div>`
    : ''

  return `
    <div class="card-header d-flex justify-content-between align-items-end">
      <div>
        <div class="fw-semibold">${esc(d.name)}</div>
        ${modelHtml}
        ${timeHtml}
      </div>
      <div class="d-flex flex-column align-items-end gap-1">
        ${wattsHtml}
        ${refreshBtn}
      </div>
    </div>`
}

function _deviceCard(d) {
  const stateClass = d.is_online ? 'state-online' : 'state-offline'
  const body = d.is_strip ? _outletList(d.id, d.outlets, d.is_online) : _singleControlRow(d)
  return `
    <div class="card device-card ${stateClass}" data-device-id="${d.id}">
      ${_deviceHeader(d)}
      <div class="card-body p-0">${body}</div>
    </div>`
}

function _singleControlRow(d) {
  const onClass      = d.is_on ? 'is-on' : ''
  const action       = d.is_on ? 'off' : 'on'
  const disabledAttr = d.is_online ? '' : 'disabled'
  const hasWatts     = d.watts !== null && d.watts !== undefined
  const wattsText    = hasWatts ? _fmtWatts(d.watts) : '—'
  return `
    <div class="control-row ${onClass}">
      <span class="row-label">${esc(d.name)}</span>
      <div class="d-flex align-items-center">
        <span class="row-watts">${wattsText}</span>
        <button class="toggle-switch ${onClass}"
          data-device-id="${d.id}" data-action="${action}" ${disabledAttr}></button>
      </div>
    </div>`
}

function _fmtWatts(w) {
  return `${parseFloat(w.toFixed(3))} W`
}

function _headerWatts(d) {
  if (d.watts !== null && d.watts !== undefined) return d.watts
  if (d.outlets?.some(o => o.watts !== null && o.watts !== undefined))
    return d.outlets.reduce((s, o) => s + (o.watts ?? 0), 0)
  return null
}

function _fmtAgo(iso) {
  try {
    const secs = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000))
    if (secs < 60) return `${secs}s ago`
    const mins = Math.floor(secs / 60)
    if (mins < 60) return `${mins} min ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs} hr ago`
    return `${Math.floor(hrs / 24)} days ago`
  } catch { return '' }
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

setInterval(() => {
  document.querySelectorAll('.js-offline-ago').forEach(el => {
    el.textContent = `Last seen ${_fmtAgo(el.dataset.ts)}`
  })
  document.querySelectorAll('.js-last-updated').forEach(el => {
    el.textContent = `Last updated ${_fmtAgo(el.dataset.ts)}`
  })
}, 10000)

function _outletList(deviceId, outlets, isOnline) {
  if (!outlets.length) return '<p class="text-muted text-center p-3 mb-0">No outlets</p>'
  const disabledAttr = isOnline ? '' : 'disabled'
  return outlets.map(o => {
    const onClass   = o.is_on ? 'is-on' : ''
    const action    = o.is_on ? 'off' : 'on'
    const hasWatts  = o.watts !== null && o.watts !== undefined
    const wattsText = hasWatts ? _fmtWatts(o.watts) : '—'
    const wattsTip  = hasWatts ? '' : ' title="Power monitoring not supported for individual outlets"'
    return `
      <div class="outlet-row ${onClass}">
        <span class="outlet-name">${esc(o.name)}</span>
        <span class="outlet-watts"${wattsTip}>${wattsText}</span>
        <button class="toggle-switch ${onClass}"
          data-device-id="${deviceId}" data-outlet-id="${esc(o.outlet_id)}"
          data-action="${action}" ${disabledAttr}></button>
      </div>`
  }).join('')
}
