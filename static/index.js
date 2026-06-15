import { setPower, refreshDevice } from './js/api.js'
import { connectSSE } from './js/sse.js'
import { showToast, initNotifBell } from './js/notifications.js'
import { renderDevices, renderTabs } from './js/devices.js'

function promptToken(msg, isError = false) {
  return new Promise(resolve => {
    const el = document.getElementById('tokenModal')
    const modal = bootstrap.Modal.getOrCreateInstance(el)
    const input = document.getElementById('tokenModalInput')
    const msgEl = document.getElementById('tokenModalMsg')

    msgEl.textContent = msg
    msgEl.className = `small mb-2 ${isError ? 'text-danger' : 'text-muted'}`
    input.value = ''
    input.classList.toggle('is-invalid', isError)

    let confirmedValue = null

    const submit = () => {
      const val = input.value.trim()
      if (!val) return
      confirmedValue = val
      modal.hide()
    }

    input.onkeydown = e => { if (e.key === 'Enter') submit() }
    document.getElementById('tokenModalSubmit').onclick = submit
    // Resolve after fully hidden so the next show() doesn't collide with the close animation
    el.addEventListener('hidden.bs.modal', () => resolve(confirmedValue), { once: true })
    el.addEventListener('shown.bs.modal', () => input.focus(), { once: true })

    modal.show()
  })
}

let devices = []
let searchQuery = ''
let activeGroup = 'all'
const pending = new Set()

function render() {
  renderTabs(devices, activeGroup, searchQuery, onTabSelect)
  renderDevices(devices, searchQuery, activeGroup)
}

function onTabSelect(group) {
  activeGroup = group
  searchQuery = ''
  document.getElementById('search-input').value = ''
  render()
}

function detectChanges(prev, next) {
  for (const d of next) {
    const old = prev.find(p => p.id === d.id)
    if (!old) continue

    if (old.is_online !== d.is_online) {
      showToast(
        d.is_online ? `${d.name} is back online` : `${d.name} went offline`,
        d.is_online ? 'success' : 'warning',
      )
      continue
    }

    if (!d.is_online || pending.has(d.id)) continue

    if (d.is_strip) {
      for (const o of d.outlets) {
        const prevO = old.outlets.find(p => p.outlet_id === o.outlet_id)
        if (prevO && prevO.is_on !== o.is_on) {
          showToast(`${d.name} / ${o.name} turned ${o.is_on ? 'on' : 'off'}`, 'info')
        }
      }
    } else if (old.is_on !== null && old.is_on !== d.is_on && d.is_on !== null) {
      showToast(`${d.name} turned ${d.is_on ? 'on' : 'off'}`, 'info')
    }
  }
}

async function handleToggle(deviceId, outletId, action, token = null) {
  pending.add(deviceId)
  document.querySelector(`.device-card[data-device-id="${deviceId}"]`)?.classList.add('loading')

  let retryToken = null
  try {
    const updated = await setPower(deviceId, outletId, action === 'on', token)
    devices = devices.map(d => d.id === updated.id ? updated : d)
    const label = outletId
      ? `${updated.name} / ${updated.outlets.find(o => o.outlet_id === outletId)?.name ?? outletId}`
      : updated.name
    showToast(`${label} turned ${action}`, 'success')
  } catch (e) {
    if (e.status === 403) {
      const isRetry = token !== null
      const msg = isRetry ? 'Invalid token — try again' : 'Enter the token to control this device'
      retryToken = await promptToken(msg, isRetry)
    } else {
      const name = devices.find(d => d.id === deviceId)?.name ?? deviceId
      showToast(`${e.message}: ${name}`, 'danger')
    }
  } finally {
    if (!retryToken) {
      pending.delete(deviceId)
      render()
    }
  }

  if (retryToken) {
    await handleToggle(deviceId, outletId, action, retryToken)
  }
}

async function handleRefresh(deviceId) {
  document.querySelector(`.device-card[data-device-id="${deviceId}"]`)?.classList.add('loading')
  try {
    const updated = await refreshDevice(deviceId)
    showToast(
      updated.is_online ? `Back online: ${updated.name}` : `Still offline: ${updated.name}`,
      updated.is_online ? 'success' : 'warning',
    )
    devices = devices.map(d => d.id === updated.id ? updated : d)
  } catch (e) {
    const name = devices.find(d => d.id === deviceId)?.name ?? deviceId
    showToast(`${e.message}: ${name}`, 'danger')
  } finally {
    render()
  }
}

document.getElementById('devices-container').addEventListener('click', async e => {
  const toggle = e.target.closest('.toggle-switch:not([disabled])')
  if (toggle) {
    const { deviceId, outletId, action, hasToken } = toggle.dataset
    if (hasToken) {
      const token = await promptToken('Enter the token to control this device')
      if (!token) return
      handleToggle(deviceId, outletId ?? null, action, token)
    } else {
      handleToggle(deviceId, outletId ?? null, action)
    }
    return
  }
  const refresh = e.target.closest('.refresh-btn')
  if (refresh) handleRefresh(refresh.dataset.deviceId)
})

document.getElementById('search-input').addEventListener('input', e => {
  searchQuery = e.target.value.trim()
  render()
})

const banner = document.getElementById('server-offline-banner')
connectSSE(
  updated => {
    detectChanges(devices, updated)
    devices = updated
    render()
  },
  () => banner.classList.remove('d-none'),
  () => banner.classList.add('d-none'),
)

initNotifBell()
