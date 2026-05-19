const SSE_URL = '/api/v1/events'
const RETRY_DELAY = 3000

export function connectSSE(onDevices, onOffline, onOnline) {
  let es = null

  function connect() {
    es = new EventSource(SSE_URL)

    es.onmessage = e => {
      onOnline?.()
      try {
        onDevices(JSON.parse(e.data))
      } catch (_) {}
    }

    es.onerror = () => {
      es.close()
      onOffline?.()
      setTimeout(connect, RETRY_DELAY)
    }
  }

  connect()
}
