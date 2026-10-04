async function request(path, params = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    query.set(key, String(value))
  })
  const suffix = query.toString() ? `?${query.toString()}` : ''
  const response = await fetch(`/api${path}${suffix}`)
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `HTTP ${response.status}`)
  }
  return response.json()
}

export const api = {
  health: () => request('/health'),
  filters: () => request('/filters'),
  overview: (params) => request('/overview', params),
  documents: (params) => request('/documents', params),
  trace: (params) => request('/trace', params),
  suppliers: (params) => request('/suppliers', params),
  governance: () => request('/governance'),
  exportUrl: (params = {}) => {
    const query = new URLSearchParams(params)
    return `/api/export?${query.toString()}`
  },
}
