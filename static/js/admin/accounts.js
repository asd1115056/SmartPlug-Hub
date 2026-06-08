import * as api from './api.js'

let cache = []

export async function loadAccounts(onUnauth) {
  try {
    cache = await api.getAccounts()
    renderAccounts()
    populateAccountSelect()
  } catch (e) {
    if (e.status === 401) onUnauth?.()
  }
}

export function getCache() { return cache }

function renderAccounts() {
  const tbody = document.querySelector('#accountsTable tbody')
  if (!cache.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted py-4">No accounts yet.</td></tr>'
    return
  }
  tbody.innerHTML = cache.map(a => `
    <tr>
      <td class="text-center text-muted font-monospace small">${a.id}</td>
      <td class="text-center"><span class="badge bg-secondary">${a.type}</span></td>
      <td class="font-monospace">${esc(a.username)}</td>
      <td class="text-end">
        <button class="btn btn-sm btn-outline-danger js-delete-account" data-id="${a.id}">
          <i class="bi bi-trash"></i>
        </button>
      </td>
    </tr>`).join('')
}

export function populateAccountSelect() {
  const sel = document.getElementById('accountSelect')
  const cur = sel.value
  sel.innerHTML = '<option value="">— none —</option>' +
    cache.map(a => `<option value="${a.id}" data-type="${a.type}">${esc(a.username)} (${a.type})</option>`).join('')
  sel.value = cur
}

function esc(str) {
  const d = document.createElement('div')
  d.textContent = str ?? ''
  return d.innerHTML
}
