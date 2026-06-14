function esc(str) {
  const d = document.createElement('div')
  d.textContent = str ?? ''
  return d.innerHTML.replaceAll('"', '&quot;')
}

function _formatMac(mac) {
  if (!mac) return '—'
  const clean = mac.replace(/[:-]/g, '').toUpperCase()
  return clean.match(/.{1,2}/g)?.join(':') ?? mac
}

function _protocolBadge(type) {
  return `<span class="protocol-badge type-${esc(type)}">${esc(type)}</span>`
}

// ── Device cards ──────────────────────────────────────────────────────────────

export function renderDeviceCards(devices, filter = '') {
  const container = document.getElementById('deviceCards')
  const count = document.getElementById('deviceCount')

  const q = filter.toLowerCase().trim()
  const filtered = q
    ? devices.filter(d =>
        (d.name ?? '').toLowerCase().includes(q) ||
        (d.hw_alias ?? '').toLowerCase().includes(q) ||
        (d.mac ?? '').toLowerCase().includes(q) ||
        (d.group_name ?? '').toLowerCase().includes(q)
      )
    : devices

  count.textContent = filtered.length

  if (!filtered.length) {
    container.innerHTML = q
      ? '<p class="text-muted py-3">No devices match the filter.</p>'
      : '<p class="text-muted py-3">No devices yet. Use Scan to discover devices.</p>'
    return
  }

  container.innerHTML = filtered.map(d => {
    const dotClass = d.is_online ? 'online' : 'offline'
    const cardClass = d.is_online ? '' : 'offline'
    const displayName = d.name || d.hw_alias || d.mac
    const model = d.hw_model ? `${esc(d.hw_model)} ${_protocolBadge(d.type)}` : _protocolBadge(d.type)
    const group = d.group_name
      ? `<div class="adc-group"><i class="bi bi-folder me-1"></i>${esc(d.group_name)}</div>`
      : ''
    const meta = [_formatMac(d.mac), d.last_known_ip].filter(Boolean).join(' · ')

    return `
      <div class="col-lg-4 col-md-6">
        <div class="admin-device-card ${cardClass}" data-device-id="${esc(d.id)}" role="button">
          <div class="d-flex gap-2">
            <div class="adc-dot ${dotClass}"></div>
            <div class="flex-fill">
              <div class="adc-name">${esc(displayName)}</div>
              <div class="adc-model">${model}</div>
              ${group}
              ${meta ? `<div class="adc-meta">${esc(meta)}</div>` : ''}
            </div>
          </div>
        </div>
      </div>`
  }).join('')
}

// ── Scan results ──────────────────────────────────────────────────────────────

export function renderScanResults(discovered, onAdd) {
  const container = document.getElementById('scanResults')
  if (!discovered.length) {
    container.innerHTML = '<p class="text-muted mb-0 mt-2">No devices found on any interface.</p>'
    container.hidden = false
    return
  }

  // Group by broadcast → derive subnet label
  const groups = new Map()
  for (const d of discovered) {
    if (!groups.has(d.broadcast)) groups.set(d.broadcast, [])
    groups.get(d.broadcast).push(d)
  }

  const newTotal = discovered.filter(d => !d.is_registered).length
  const addedTotal = discovered.filter(d => d.is_registered).length

  let html = `<div class="d-flex align-items-center gap-2 mb-3">
    <span class="fw-semibold" style="font-size:.85rem">Scan Results</span>
    ${newTotal ? `<span class="badge bg-success">${newTotal} new</span>` : ''}
    ${addedTotal ? `<span class="badge bg-secondary">${addedTotal} already added</span>` : ''}
  </div>`

  for (const [broadcast, devices] of groups) {
    const subnet = broadcast.replace(/\.\d+$/, '.0/24')
    const newCount = devices.filter(d => !d.is_registered).length
    const addedCount = devices.filter(d => d.is_registered).length
    const groupId = `nic-${broadcast.replaceAll('.', '-')}`

    html += `
      <div class="mb-3">
        <div class="scan-nic-header" data-toggle="${groupId}">
          <i class="bi bi-chevron-down me-2" style="font-size:.65rem;transition:transform .2s" id="chev-${groupId}"></i>
          <i class="bi bi-diagram-3 me-1 text-muted"></i>
          <span class="fw-semibold font-monospace">${esc(subnet)}</span>
          <span class="text-muted ms-2">·
            ${newCount ? `${newCount} new` : ''}
            ${newCount && addedCount ? ' · ' : ''}
            ${addedCount ? `${addedCount} added` : ''}
          </span>
        </div>
        <div class="scan-list" id="${groupId}">
          ${devices.map(d => _scanRow(d)).join('')}
        </div>
      </div>`
  }

  container.innerHTML = html
  container.hidden = false

  // Collapse toggle
  container.querySelectorAll('[data-toggle]').forEach(header => {
    header.addEventListener('click', () => {
      const list = document.getElementById(header.dataset.toggle)
      const chev = document.getElementById(`chev-${header.dataset.toggle}`)
      const collapsed = list.style.display === 'none'
      list.style.display = collapsed ? '' : 'none'
      chev.style.transform = collapsed ? '' : 'rotate(-90deg)'
    })
  })

  // Add buttons
  container.querySelectorAll('.js-scan-add').forEach(btn => {
    btn.addEventListener('click', () => {
      const { mac, type, broadcast, ip, model, miioId, tuyaDeviceId, tuyaLocalKey, tuyaProductId } = btn.dataset
      onAdd({
        mac, type, broadcast, ip, model: model || null,
        miio_id: miioId || null,
        tuya_device_id: tuyaDeviceId || null,
        tuya_local_key: tuyaLocalKey || null,
        tuya_product_id: tuyaProductId || null,
      })
    })
  })
}

function _scanRow(d) {
  const registeredLabel = d.is_registered
    ? `<div class="scan-registered-label"><i class="bi bi-check-circle-fill me-1"></i>${esc(d.registered_name || 'Added')}</div>`
    : ''

  const action = d.is_registered
    ? `<span class="flex-shrink-0" style="width:72px;text-align:center">
         <i class="bi bi-check-circle-fill text-success" style="font-size:1.1rem"></i>
       </span>`
    : `<button class="js-scan-add btn btn-outline-success btn-sm flex-shrink-0"
         style="width:72px"
         data-mac="${esc(d.mac)}" data-type="${esc(d.type)}"
         data-broadcast="${esc(d.broadcast)}" data-ip="${esc(d.ip)}"
         data-model="${esc(d.model ?? '')}"
         data-miio-id="${esc(d.miio_id ?? '')}"
         data-tuya-device-id="${esc(d.tuya_device_id ?? '')}"
         data-tuya-local-key="${esc(d.tuya_local_key ?? '')}"
         data-tuya-product-id="${esc(d.tuya_product_id ?? '')}">
         <i class="bi bi-plus-lg me-1"></i>Add
       </button>`

  return `
    <div class="scan-row ${d.is_registered ? 'is-registered' : ''}">
      <span style="flex-shrink:0">${_protocolBadge(d.type)}</span>
      <div class="scan-model">
        <div>${esc(d.model || d.type)}</div>
        ${registeredLabel}
      </div>
      <span class="scan-ip">${esc(d.ip)}</span>
      <span class="scan-mac">${esc(_formatMac(d.mac))}</span>
      ${action}
    </div>`
}

// ── Detail panel ──────────────────────────────────────────────────────────────

export function fillDetailPanel(device) {
  const displayName = device.name || device.hw_alias || device.mac

  document.getElementById('panelName').textContent = displayName
  document.getElementById('panelNameInput').value = device.name ?? ''
  document.getElementById('panelGroupInput').value = device.group_name ?? ''

  // Status
  const statusEl = document.getElementById('panelStatus')
  if (device.is_online) {
    statusEl.innerHTML = '<span style="color:#198754"><i class="bi bi-circle-fill me-1" style="font-size:.45rem"></i>Online</span>'
  } else {
    statusEl.innerHTML = '<span class="text-muted">○ Offline</span>'
  }

  // Info
  document.getElementById('panelModel').textContent = device.hw_model ?? '—'
  document.getElementById('panelType').innerHTML = _protocolBadge(device.type)
  document.getElementById('panelMac').textContent = _formatMac(device.mac)
  document.getElementById('panelIp').textContent = device.last_known_ip ?? '—'

  // Tuya credentials (read-only)
  const tuyaSec = document.getElementById('panelTuya')
  if (device.type === 'tuya') {
    document.getElementById('panelTuyaDeviceId').textContent = device.tuya_device_id ?? '—'
    document.getElementById('panelTuyaLocalKey').textContent = device.tuya_local_key ?? '—'
    document.getElementById('panelTuyaProductId').textContent = device.tuya_product_id ?? '—'
    tuyaSec.hidden = false
  } else {
    tuyaSec.hidden = true
  }

  // MiIO credentials (read-only)
  const miioSec = document.getElementById('panelMiio')
  if (device.type === 'miio') {
    document.getElementById('panelMiioToken').textContent = device.miio_token ?? '—'
    document.getElementById('panelMiioId').textContent = device.miio_id ?? '—'
    miioSec.hidden = false
  } else {
    miioSec.hidden = true
  }

  // Outlets (strip only)
  const outletsSec = document.getElementById('panelOutletsSec')
  if (device.hw_is_strip && device.outlets?.length) {
    document.getElementById('panelOutlets').innerHTML = device.outlets.map((o, i) => `
      <div class="input-group input-group-sm mb-2">
        <span class="input-group-text text-muted font-monospace" style="width:2.2rem">${i}</span>
        <input class="form-control js-outlet-name" data-outlet-id="${esc(o.outlet_id)}" value="${esc(o.name)}">
      </div>`).join('')
    outletsSec.hidden = false
  } else {
    outletsSec.hidden = true
  }
}

// ── Delete confirm ────────────────────────────────────────────────────────────

export function confirmDelete(message) {
  return new Promise(resolve => {
    const modalEl = document.getElementById('deleteModal')
    const btn = document.getElementById('deleteConfirmBtn')
    document.getElementById('deleteModalBody').textContent = message
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl)
    function cleanup() {
      btn.removeEventListener('click', onConfirm)
      modalEl.removeEventListener('hidden.bs.modal', onDismiss)
      modal.hide()
    }
    const onConfirm = () => { cleanup(); resolve(true) }
    const onDismiss = () => { cleanup(); resolve(false) }
    btn.addEventListener('click', onConfirm, { once: true })
    modalEl.addEventListener('hidden.bs.modal', onDismiss, { once: true })
    modal.show()
  })
}
