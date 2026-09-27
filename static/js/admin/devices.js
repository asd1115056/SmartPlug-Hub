import { esc } from '../common.js'

export const deviceCards = document.getElementById('deviceCards')
export const scanResults = document.getElementById('scanResults')
const deviceCount = document.getElementById('deviceCount')
const deleteModal = document.getElementById('deleteModal')
const deleteConfirmBtn = document.getElementById('deleteConfirmBtn')
const deleteModalBody = document.getElementById('deleteModalBody')

// Detail panel fields, shared with admin.js so each element is looked up once
export const panel = {
  name:               document.getElementById('panelName'),
  nameInput:          document.getElementById('panelNameInput'),
  groupInput:         document.getElementById('panelGroupInput'),
  status:             document.getElementById('panelStatus'),
  model:              document.getElementById('panelModel'),
  type:               document.getElementById('panelType'),
  mac:                document.getElementById('panelMac'),
  ip:                 document.getElementById('panelIp'),
  kasa:               document.getElementById('panelKasa'),
  kasaUsername:       document.getElementById('panelKasaUsername'),
  kasaPassword:       document.getElementById('panelKasaPassword'),
  kasaPasswordToggle: document.getElementById('panelKasaPasswordToggle'),
  tuya:               document.getElementById('panelTuya'),
  tuyaDeviceId:       document.getElementById('panelTuyaDeviceId'),
  tuyaLocalKey:       document.getElementById('panelTuyaLocalKey'),
  tuyaProductId:      document.getElementById('panelTuyaProductId'),
  miio:               document.getElementById('panelMiio'),
  miioId:             document.getElementById('panelMiioId'),
  miioToken:          document.getElementById('panelMiioToken'),
  deviceTokenSec:     document.getElementById('panelDeviceTokenSec'),
  deviceToken:        document.getElementById('panelDeviceToken'),
  outletsSec:         document.getElementById('panelOutletsSec'),
  outlets:            document.getElementById('panelOutlets'),
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

  const q = filter.toLowerCase().trim()
  const filtered = q
    ? devices.filter(d =>
        (d.name ?? '').toLowerCase().includes(q) ||
        (d.hw_alias ?? '').toLowerCase().includes(q) ||
        (d.mac ?? '').toLowerCase().includes(q) ||
        (d.group_name ?? '').toLowerCase().includes(q)
      )
    : devices

  deviceCount.textContent = filtered.length

  if (!filtered.length) {
    deviceCards.innerHTML = q
      ? '<p class="text-muted py-3">No devices match the filter.</p>'
      : '<p class="text-muted py-3">No devices yet. Use Scan to discover devices.</p>'
    return
  }

  deviceCards.innerHTML = filtered.map(d => {
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
  if (!discovered.length) {
    scanResults.innerHTML = '<p class="text-muted mb-0 mt-2">No devices found on any interface.</p>'
    scanResults.hidden = false
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

  scanResults.innerHTML = html
  scanResults.hidden = false

  // Collapse toggle
  scanResults.querySelectorAll('[data-toggle]').forEach(header => {
    header.addEventListener('click', () => {
      const list = document.getElementById(header.dataset.toggle)
      const chev = document.getElementById(`chev-${header.dataset.toggle}`)
      const collapsed = list.style.display === 'none'
      list.style.display = collapsed ? '' : 'none'
      chev.style.transform = collapsed ? '' : 'rotate(-90deg)'
    })
  })

  // Add buttons
  scanResults.querySelectorAll('.js-scan-add').forEach(btn => {
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

  panel.name.textContent = displayName
  panel.nameInput.value = device.name ?? ''
  panel.groupInput.value = device.group_name ?? ''

  // Status
  if (device.is_online) {
    panel.status.innerHTML = '<span style="color:#198754"><i class="bi bi-circle-fill me-1" style="font-size:.45rem"></i>Online</span>'
  } else {
    panel.status.innerHTML = '<span class="text-muted">○ Offline</span>'
  }

  // Info
  panel.model.textContent = device.hw_model ?? '—'
  panel.type.innerHTML = _protocolBadge(device.type)
  panel.mac.textContent = _formatMac(device.mac)
  panel.ip.textContent = device.last_known_ip ?? '—'

  // Kasa credentials (editable)
  if (device.type === 'kasa') {
    panel.kasaUsername.value = device.kasa_username ?? ''
    panel.kasaPassword.value = device.kasa_password ?? ''
    panel.kasa.hidden = false
  } else {
    panel.kasa.hidden = true
  }

  // Tuya credentials (editable)
  if (device.type === 'tuya') {
    panel.tuyaDeviceId.value = device.tuya_device_id ?? ''
    panel.tuyaLocalKey.value = device.tuya_local_key ?? ''
    panel.tuyaProductId.value = device.tuya_product_id ?? ''
    panel.tuya.hidden = false
  } else {
    panel.tuya.hidden = true
  }

  // MiIO credentials (editable)
  if (device.type === 'miio') {
    panel.miioId.value = device.miio_id ?? ''
    panel.miioToken.value = device.miio_token ?? ''
    panel.miio.hidden = false
  } else {
    panel.miio.hidden = true
  }

  // Device token (non-strip only)
  if (!device.hw_is_strip) {
    panel.deviceToken.value = device.device_token ?? ''
    panel.deviceTokenSec.hidden = false
  } else {
    panel.deviceTokenSec.hidden = true
  }

  // Outlets (strip only)
  if (device.hw_is_strip && device.outlets?.length) {
    panel.outlets.innerHTML = device.outlets.map((o, i) => `
      <div class="border rounded p-2 mb-2">
        <div class="d-flex align-items-center gap-1 mb-1">
          <span class="badge bg-secondary font-monospace">${i}</span>
          <input class="form-control form-control-sm js-outlet-name" data-outlet-id="${esc(o.outlet_id)}"
            value="${esc(o.name)}" placeholder="Name">
        </div>
        <div class="d-flex gap-1">
          <span class="badge bg-secondary font-monospace invisible">${i}</span>
          <input class="form-control form-control-sm js-outlet-token font-monospace" data-outlet-id="${esc(o.outlet_id)}"
            value="${esc(o.token ?? '')}" placeholder="Access token (blank = no restriction)" autocomplete="off">
        </div>
      </div>`).join('')
    panel.outletsSec.hidden = false
  } else {
    panel.outletsSec.hidden = true
  }
}

// ── Delete confirm ────────────────────────────────────────────────────────────

export function confirmDelete(message) {
  return new Promise(resolve => {
    deleteModalBody.textContent = message
    const modal = bootstrap.Modal.getOrCreateInstance(deleteModal)
    function cleanup() {
      deleteConfirmBtn.removeEventListener('click', onConfirm)
      deleteModal.removeEventListener('hidden.bs.modal', onDismiss)
      modal.hide()
    }
    const onConfirm = () => { cleanup(); resolve(true) }
    const onDismiss = () => { cleanup(); resolve(false) }
    deleteConfirmBtn.addEventListener('click', onConfirm, { once: true })
    deleteModal.addEventListener('hidden.bs.modal', onDismiss, { once: true })
    modal.show()
  })
}
