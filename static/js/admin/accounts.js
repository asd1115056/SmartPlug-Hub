import * as api from './api.js'

let _cache = []

export async function loadAccounts(onUnauth) {
  try {
    _cache = await api.getAccounts()
    renderAccounts()
  } catch (e) {
    if (e.status === 401) onUnauth?.()
  }
}

export function getCache() { return _cache }

export function renderAccounts() {
  const container = document.getElementById('accountsList')
  if (!container) return
  if (!_cache.length) {
    container.innerHTML = '<p class="text-muted mb-0" style="font-size:.85rem">No accounts yet.</p>'
    return
  }
  container.innerHTML = _cache.map(a => `
    <div class="d-flex align-items-center gap-2 py-2 border-bottom border-secondary">
      <span class="protocol-badge type-${esc(a.type)}">${esc(a.type)}</span>
      <span class="flex-fill font-monospace">${esc(a.username)}</span>
      <button class="btn btn-sm btn-outline-danger js-delete-account" data-id="${a.id}">
        <i class="bi bi-trash"></i>
      </button>
    </div>`).join('')
}

function esc(str) {
  const d = document.createElement('div')
  d.textContent = str ?? ''
  return d.innerHTML.replaceAll('"', '&quot;')
}
