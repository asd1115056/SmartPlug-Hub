import { esc, fmtTime } from './common.js'

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

// Shared with the admin page, which has the toast container but no notification bell
const toastContainer = document.getElementById('toast-container')
const notifBadge = document.getElementById('notif-badge')
const notifDropdown = document.getElementById('notif-dropdown')

const history = []
let unreadCount = 0

export function showToast(msg, type = 'danger') {
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
  toastContainer.appendChild(el)
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
  if (!btn || !notifDropdown) return

  btn.addEventListener('click', e => {
    e.stopPropagation()
    if (!notifDropdown.classList.contains('d-none')) {
      notifDropdown.classList.add('d-none')
      return
    }
    unreadCount = 0
    _updateBadge()
    _renderDropdown()
    notifDropdown.classList.remove('d-none')
  })

  document.addEventListener('click', e => {
    if (wrapper && !wrapper.contains(e.target)) notifDropdown.classList.add('d-none')
  })
}

function _updateBadge() {
  if (!notifBadge) return
  if (unreadCount > 0) {
    notifBadge.textContent = unreadCount > 9 ? '9+' : String(unreadCount)
    notifBadge.classList.remove('d-none')
  } else {
    notifBadge.classList.add('d-none')
  }
}

function _renderDropdown() {
  if (!notifDropdown) return
  if (!history.length) {
    notifDropdown.innerHTML = '<p class="notif-empty">No notifications yet</p>'
    return
  }
  notifDropdown.innerHTML = history.map(n => `
    <div class="notif-item">
      <span class="notif-item-icon type-${n.type}"><i class="bi ${n.icon}"></i></span>
      <div class="notif-item-body">
        <div class="notif-item-msg">${esc(n.msg)}</div>
        <div class="notif-item-time">${fmtTime(n.time)}</div>
      </div>
    </div>`).join('')
}
