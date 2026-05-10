// SmartPlug Hub frontend — theme, polling, device card rendering.

const API_BASE = '/api/v1'
const POLL_INTERVAL = 5000

let pollTimer = null
const currentDevices = {}
let allDeviceIds = []
let activeGroup = 'all'
let searchQuery = ''


async function fetchDevices() {
    const response = await fetch(`${API_BASE}/devices`)
    if (!response.ok) throw new Error('Failed to fetch devices')
    return response.json()
}

async function controlDevice(deviceId, action, childId = null) {
    const body = { is_on: action === 'on' }
    if (childId !== null) body.child_id = childId

    const response = await fetch(`${API_BASE}/devices/${encodeURIComponent(deviceId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    })

    if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail?.message || 'Control failed')
    }
    return response.json()
}

async function refreshDevice(deviceId) {
    const response = await fetch(`${API_BASE}/devices/${encodeURIComponent(deviceId)}/refresh`, {
        method: 'POST'
    })
    return response.json()
}

function showToast(message, type = 'danger') {
    const container = document.getElementById('toast-container')
    const colorClass = {
        success: 'text-bg-success',
        warning: 'text-bg-warning',
        danger: 'text-bg-danger',
        info: 'text-bg-info',
    }[type] || 'text-bg-danger'

    const toastEl = document.createElement('div')
    toastEl.className = `toast ${colorClass}`
    toastEl.setAttribute('role', 'alert')
    toastEl.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${escapeHtml(message)}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto"
                    data-bs-dismiss="toast"></button>
        </div>
    `

    container.appendChild(toastEl)
    const toast = new bootstrap.Toast(toastEl, { delay: 5000 })
    toast.show()
    toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove())
}

function escapeHtml(text) {
    if (!text) return ''
    const div = document.createElement('div')
    div.textContent = text
    return div.innerHTML
}

function formatTime(isoString) {
    try {
        const date = new Date(isoString)
        const offsetMin = -date.getTimezoneOffset()
        const sign = offsetMin >= 0 ? '+' : '-'
        const absMin = Math.abs(offsetMin)
        const hours = Math.floor(absMin / 60)
        const mins = absMin % 60
        const offset = mins ? `${hours}:${String(mins).padStart(2, '0')}` : `${hours}`
        const time = date.toLocaleTimeString(undefined, { hour12: false })
        return `${time} UTC${sign}${offset}`
    } catch {
        return ''
    }
}

function getAllDevices() {
    return allDeviceIds.map(id => currentDevices[id]).filter(Boolean)
}

function getFilteredDevices(devices) {
    if (searchQuery) {
        const q = searchQuery.toLowerCase()
        return devices.filter(d =>
            d.name.toLowerCase().includes(q) ||
            (d.children?.some(c => c.alias.toLowerCase().includes(q)))
        )
    }
    if (activeGroup !== 'all') {
        return devices.filter(d => d.group === activeGroup)
    }
    return devices
}

function renderTabs(devices) {
    const container = document.getElementById('tabs-nav')
    if (!container) return

    const groups = [...new Set(devices.filter(d => d.group).map(d => d.group))]

    // When searching, highlight All tab
    const effectiveActive = searchQuery ? 'all' : activeGroup

    const tabs = [
        { id: 'all', label: 'All', count: devices.length },
        ...groups.map(g => ({
            id: g,
            label: g,
            count: devices.filter(d => d.group === g).length,
        }))
    ]

    container.innerHTML = `
        <ul class="nav nav-tabs mb-3">
            ${tabs.map(tab => `
                <li class="nav-item">
                    <button class="nav-link ${effectiveActive === tab.id ? 'active' : ''}"
                            data-group="${escapeHtml(tab.id)}">
                        ${escapeHtml(tab.label)}
                        <span class="badge text-bg-secondary ms-1">${tab.count}</span>
                    </button>
                </li>
            `).join('')}
        </ul>
    `

    container.querySelectorAll('.nav-link').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.group))
    })
}

function switchTab(group) {
    activeGroup = group
    searchQuery = ''
    const searchInput = document.getElementById('search-input')
    if (searchInput) searchInput.value = ''
    const all = getAllDevices()
    renderTabs(all)
    renderDeviceGrid(getFilteredDevices(all))
}

function renderDevices(devices) {
    allDeviceIds = devices.map(d => d.id)
    for (const device of devices) {
        currentDevices[device.id] = device
    }
    renderTabs(devices)
    renderDeviceGrid(getFilteredDevices(devices))
}

function renderDeviceGrid(devices) {
    const container = document.getElementById('devices-container')

    if (getAllDevices().length === 0) {
        container.innerHTML = `
            <div class="alert alert-info">
                <strong>No devices</strong><br>
                Please configure whitelisted devices in <code>config/devices.json</code>.
            </div>
        `
        return
    }

    if (devices.length === 0) {
        container.innerHTML = `<div class="text-muted py-3">No matching devices.</div>`
        return
    }

    container.innerHTML = `
        <div class="row g-3">
            ${devices.map(device => `
                <div class="col-lg-4 col-md-6">
                    ${renderDeviceCard(device)}
                </div>
            `).join('')}
        </div>
    `
}

function renderDeviceCard(device) {
    const online = device.status === 'online'
    const stateClass = online ? 'online' : 'offline'

    let bodyHtml = ''
    if (device.is_strip && device.children && device.children.length > 0) {
        bodyHtml = device.children.map(child =>
            renderChildOutlet(device.id, child, online)
        ).join('')
    } else if (online) {
        bodyHtml = `
            <div class="single-device-control">
                ${renderToggleSwitch(device.id, null, device.is_on, true)}
            </div>
        `
    } else {
        bodyHtml = `
            <div class="single-device-control">
                ${renderToggleSwitch(device.id, null, false, false)}
            </div>
        `
    }

    const refreshBtn = !online ? `
        <button class="btn btn-sm refresh-device-btn"
                onclick="handleRefresh('${device.id}')" title="Refresh">
            &#x21bb;
        </button>
    ` : ''

    const updatedTime = device.last_updated ? formatTime(device.last_updated) : ''

    return `
        <div class="card device-card h-100 state-${stateClass}" data-id="${device.id}">
            <div class="card-header d-flex justify-content-between align-items-center">
                <div>
                    <strong>${escapeHtml(device.name)}</strong>
                    ${device.model ? `<div class="device-model">${escapeHtml(device.model)}</div>` : ''}
                    ${updatedTime ? `<div class="last-updated">Last updated: ${updatedTime}</div>` : ''}
                </div>
                ${refreshBtn}
            </div>
            <div class="card-body">
                ${bodyHtml}
            </div>
        </div>
    `
}

function renderChildOutlet(deviceId, child, online) {
    const onClass = child.is_on ? 'is-on' : ''

    return `
        <div class="child-outlet ${onClass}">
            <span class="outlet-name">${escapeHtml(child.alias)}</span>
            <div class="outlet-controls">
                ${renderToggleSwitch(deviceId, child.id, child.is_on, online)}
            </div>
        </div>
    `
}

function renderToggleSwitch(deviceId, childId, isOn, enabled) {
    const childParam = childId !== null ? `'${childId}'` : 'null'
    const action = isOn ? 'off' : 'on'
    const onClass = isOn ? 'is-on' : ''
    const disabledAttr = enabled ? '' : 'disabled'

    return `
        <button class="toggle-switch ${onClass}"
                onclick="handleToggle('${deviceId}', '${action}', ${childParam})"
                title="${isOn ? 'Turn off' : 'Turn on'}"
                ${disabledAttr}>
        </button>
    `
}

async function loadDevices() {
    try {
        const data = await fetchDevices()
        renderDevices(data.devices)
    } catch (error) {
        console.error('Load devices error:', error)
        showToast('Failed to load devices: ' + error.message)
    }
}

async function handleToggle(deviceId, action, childId) {
    const card = document.querySelector(`[data-id="${deviceId}"]`)
    if (card) card.classList.add('loading')

    try {
        const result = await controlDevice(deviceId, action, childId)
        currentDevices[deviceId] = result
        updateCardFromState(deviceId, result)
        const deviceName = result.name || deviceId
        let msg = `${deviceName}: turned ${action}`
        if (childId && result.children) {
            const child = result.children.find(c => c.id === childId)
            if (child) msg = `${deviceName} / ${child.alias}: turned ${action}`
        }
        showToast(msg, 'success')
    } catch (error) {
        console.error('Toggle error:', error)
        const deviceName = currentDevices[deviceId]?.name || deviceId
        let target = deviceName
        if (childId) {
            const prev = currentDevices[deviceId]
            if (prev?.children) {
                const child = prev.children.find(c => c.id === childId)
                if (child) target = `${deviceName} / ${child.alias}`
            }
        }
        showToast(`${target}: ${error.message}`)
    } finally {
        if (card) card.classList.remove('loading')
    }
}

async function handleRefresh(deviceId) {
    const card = document.querySelector(`[data-id="${deviceId}"]`)
    if (card) card.classList.add('loading')

    try {
        const result = await refreshDevice(deviceId)
        currentDevices[deviceId] = result

        if (result.status === 'online') {
            showToast('Device reconnected', 'success')
        } else {
            showToast('Device still offline', 'warning')
        }

        await loadDevices()
    } catch (error) {
        console.error('Refresh error:', error)
        showToast('Refresh failed: ' + error.message)
    } finally {
        if (card) card.classList.remove('loading')
    }
}

function updateCardFromState(deviceId, device) {
    const card = document.querySelector(`[data-id="${deviceId}"]`)
    if (!card) return

    const online = device.status === 'online'
    const wasOnline = card.classList.contains('state-online')
    if (online !== wasOnline) {
        loadDevices()
        return
    }

    if (!online) return

    if (device.children && device.children.length > 0) {
        for (const child of device.children) {
            const buttons = card.querySelectorAll('.toggle-switch')
            for (const btn of buttons) {
                const onclick = btn.getAttribute('onclick') || ''
                if (onclick.includes(`'${child.id}'`)) {
                    updateToggleButton(btn, deviceId, child.id, child.is_on)
                    const outlet = btn.closest('.child-outlet')
                    if (outlet) {
                        outlet.classList.toggle('is-on', child.is_on)
                    }
                    break
                }
            }
        }
    } else if (device.is_on !== undefined && device.is_on !== null) {
        const btn = card.querySelector('.single-device-control .toggle-switch')
        if (btn) {
            updateToggleButton(btn, deviceId, null, device.is_on)
        }
    }
}

function updateToggleButton(btn, deviceId, childId, isOn) {
    const action = isOn ? 'off' : 'on'
    const childParam = childId !== null ? `'${childId}'` : 'null'
    btn.classList.toggle('is-on', isOn)
    btn.setAttribute('onclick', `handleToggle('${deviceId}', '${action}', ${childParam})`)
    btn.setAttribute('title', isOn ? 'Turn off' : 'Turn on')
}

function setServerOffline(offline) {
    const banner = document.getElementById('server-offline-banner')
    if (banner) banner.classList.toggle('d-none', !offline)
}

async function pollStatus() {
    try {
        const data = await fetchDevices()
        setServerOffline(false)
        for (const device of data.devices) {
            const previous = currentDevices[device.id]

            if (previous && previous.status !== device.status) {
                renderDevices(data.devices)
                return
            }

            currentDevices[device.id] = device
            updateCardFromState(device.id, device)
        }
    } catch (error) {
        console.error('Poll error:', error)
        setServerOffline(true)
    }
}

function startPolling() {
    if (pollTimer) return
    pollTimer = setInterval(pollStatus, POLL_INTERVAL)
}

document.addEventListener('DOMContentLoaded', () => {
    loadDevices()
    startPolling()

    const searchInput = document.getElementById('search-input')
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            searchQuery = searchInput.value.trim()
            const all = getAllDevices()
            renderTabs(all)
            renderDeviceGrid(getFilteredDevices(all))
        })
    }
})
