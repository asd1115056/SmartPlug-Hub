const ICONS = {
  success: 'bi-check-circle-fill',
  warning: 'bi-exclamation-triangle-fill',
  danger:  'bi-x-circle-fill',
  info:    'bi-info-circle-fill',
}

const COLOR = {
  success: 'text-bg-success',
  warning: 'text-bg-warning',
  danger:  'text-bg-danger',
  info:    'text-bg-info',
}

const history = []
let unreadCount = 0

export function showToast(msg, type = 'danger') {
  const container = document.getElementById('toast-container')
  const icon = ICONS[type] ?? ICONS.danger

  const el = document.createElement('div')
  el.className = `toast ${COLOR[type] ?? COLOR.danger} border-0`
  el.setAttribute('role', 'alert')
  el.innerHTML = `
    <div class="d-flex align-items-center">
      <span class="toast-icon"><i class="bi ${icon}"></i></span>
      <div class="toast-body">${esc(msg)}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
    </div>`
  container.appendChild(el)
  const toast = new bootstrap.Toast(el, { delay: 5000 })
  toast.show()
  el.addEventListener('hidden.bs.toast', () => el.remove())

  history.unshift({ msg, type, icon, time: new Date().toISOString() })
  if (history.length > 20) history.pop()
  unreadCount++
  _updateBadge()
}

export function initNotifBell() {
  const btn      = document.getElementById('notif-btn')
  const wrapper  = document.getElementById('notif-wrapper')
  const dropdown = document.getElementById('notif-dropdown')
  if (!btn || !dropdown) return

  btn.addEventListener('click', e => {
    e.stopPropagation()
    if (!dropdown.classList.contains('d-none')) {
      dropdown.classList.add('d-none')
      return
    }
    unreadCount = 0
    _updateBadge()
    _renderDropdown()
    dropdown.classList.remove('d-none')
  })

  document.addEventListener('click', e => {
    if (wrapper && !wrapper.contains(e.target)) dropdown.classList.add('d-none')
  })
}

function _updateBadge() {
  const badge = document.getElementById('notif-badge')
  if (!badge) return
  if (unreadCount > 0) {
    badge.textContent = unreadCount > 9 ? '9+' : String(unreadCount)
    badge.classList.remove('d-none')
  } else {
    badge.classList.add('d-none')
  }
}

function _renderDropdown() {
  const dropdown = document.getElementById('notif-dropdown')
  if (!dropdown) return
  if (!history.length) {
    dropdown.innerHTML = '<p class="notif-empty">No notifications yet</p>'
    return
  }
  dropdown.innerHTML = history.map(n => `
    <div class="notif-item">
      <span class="notif-item-icon type-${n.type}"><i class="bi ${n.icon}"></i></span>
      <div class="notif-item-body">
        <div class="notif-item-msg">${esc(n.msg)}</div>
        <div class="notif-item-time">${_formatTime(n.time)}</div>
      </div>
    </div>`).join('')
}

function _formatTime(iso) {
  try { return new Date(iso).toLocaleTimeString() } catch { return '' }
}

function esc(str) {
  const d = document.createElement('div')
  d.textContent = str ?? ''
  return d.innerHTML
}
