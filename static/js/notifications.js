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
  el.className = `toast rounded-pill ${COLOR[type] ?? COLOR.danger} border-0`
  el.setAttribute('role', 'alert')
  el.innerHTML = `
    <div class="d-flex align-items-center gap-2 px-3 py-2">
      <i class="bi ${icon} flex-shrink-0"></i>
      <span class="toast-body p-0">${esc(msg)}</span>
      <button type="button" class="btn-close btn-close-white flex-shrink-0 ms-auto" style="font-size:.7rem" data-bs-dismiss="toast"></button>
    </div>`
  container.appendChild(el)
  const delay = (type === 'success' || type === 'info') ? 2500 : 5000
  const toast = new bootstrap.Toast(el, { delay })
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
  try {
    const date = new Date(iso)
    const offsetMin = -date.getTimezoneOffset()
    const sign = offsetMin >= 0 ? '+' : '-'
    const absMin = Math.abs(offsetMin)
    const h = Math.floor(absMin / 60)
    const m = absMin % 60
    const offset = m ? `${h}:${String(m).padStart(2, '0')}` : `${h}`
    return `${date.toLocaleTimeString(undefined, { hour12: true })} UTC${sign}${offset}`
  } catch { return '' }
}

function esc(str) {
  const d = document.createElement('div')
  d.textContent = str ?? ''
  return d.innerHTML
}
