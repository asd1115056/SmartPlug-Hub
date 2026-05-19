import { setPower, refreshDevice } from './js/api.js'
import { connectSSE } from './js/sse.js'
import { showToast, initNotifBell } from './js/notifications.js'
import { renderDevices, renderTabs } from './js/devices.js'

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
        d.is_online ? `Back online: ${d.name}` : `Went offline: ${d.name}`,
        d.is_online ? 'success' : 'warning',
      )
      continue
    }

    if (!d.is_online || pending.has(d.id)) continue

    if (d.is_strip) {
      for (const o of d.outlets) {
        const prevO = old.outlets.find(p => p.outlet_id === o.outlet_id)
        if (prevO && prevO.is_on !== o.is_on) {
          showToast(`${o.is_on ? 'On' : 'Off'}: ${d.name} / ${o.name}`, 'info')
        }
      }
    } else if (old.is_on !== null && old.is_on !== d.is_on && d.is_on !== null) {
      showToast(`${d.is_on ? 'On' : 'Off'}: ${d.name}`, 'info')
    }
  }
}

async function handleToggle(deviceId, outletId, action) {
  pending.add(deviceId)
  document.querySelector(`.device-card[data-device-id="${deviceId}"]`)?.classList.add('loading')

  try {
    const updated = await setPower(deviceId, outletId, action === 'on')
    devices = devices.map(d => d.id === updated.id ? updated : d)
  } catch (e) {
    const name = devices.find(d => d.id === deviceId)?.name ?? deviceId
    showToast(`${e.message}: ${name}`, 'danger')
  } finally {
    pending.delete(deviceId)
    render()
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

document.getElementById('devices-container').addEventListener('click', e => {
  const toggle = e.target.closest('.toggle-switch:not([disabled])')
  if (toggle) {
    handleToggle(toggle.dataset.deviceId, toggle.dataset.outletId ?? null, toggle.dataset.action)
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
