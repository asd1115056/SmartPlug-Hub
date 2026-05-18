import { setPower, refreshDevice } from './js/api.js'
import { connectSSE } from './js/sse.js'
import { showToast } from './js/notifications.js'
import { renderDevices, renderTabs } from './js/devices.js'

let devices = []
let searchQuery = ''
let activeGroup = 'all'

function render() {
  renderTabs(devices, activeGroup, group => { activeGroup = group; render() })
  renderDevices(devices, searchQuery, activeGroup, handleToggle, handleRefresh)
}

async function handleToggle(deviceId, outletId, on) {
  try {
    const updated = await setPower(deviceId, outletId, on)
    devices = devices.map(d => d.id === updated.id ? updated : d)
    render()
  } catch (e) {
    showToast(e.message, false)
  }
}

async function handleRefresh(deviceId) {
  try {
    const updated = await refreshDevice(deviceId)
    devices = devices.map(d => d.id === updated.id ? updated : d)
    render()
  } catch (e) {
    showToast(e.message, false)
  }
}

const banner = document.getElementById('server-offline-banner')
const searchInput = document.getElementById('search-input')

searchInput.addEventListener('input', () => {
  searchQuery = searchInput.value.trim()
  render()
})

connectSSE(
  updated => {
    devices = updated
    render()
  },
  () => banner.classList.remove('d-none'),
  () => banner.classList.add('d-none'),
)
