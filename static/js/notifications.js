export function showToast(msg, ok = true) {
  const container = document.getElementById('toast-container')
  const el = document.createElement('div')
  el.className = `toast align-items-center text-bg-${ok ? 'success' : 'danger'} border-0`
  el.setAttribute('role', 'alert')
  el.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">${esc(msg)}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
    </div>`
  container.appendChild(el)
  const toast = new bootstrap.Toast(el, { delay: 4000 })
  toast.show()
  el.addEventListener('hidden.bs.toast', () => el.remove())
}

function esc(str) {
  const d = document.createElement('div')
  d.textContent = str ?? ''
  return d.innerHTML
}
