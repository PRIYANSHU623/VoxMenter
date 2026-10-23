import axios, { isAxiosError } from 'axios'

const TOKEN_KEY = 'voxmenter-token'

export const UNAUTHORIZED_EVENT = 'voxmenter:unauthorized'

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    // Storage blocked: the user will need to log in again after a reload.
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    // ignore
  }
}

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  timeout: 30000,
})

// Attach the JWT to every request.
api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// If a logged-in user gets a 401, the token is expired or invalid.
// A wrong password on the login form also returns 401, so we skip that case.
api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (
      isAxiosError(error) &&
      error.response?.status === 401 &&
      !error.config?.url?.includes('/api/auth/login') &&
      getToken()
    ) {
      clearToken()
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
    }
    return Promise.reject(error)
  },
)

// Turns any error into a readable message for the UI.
export function getErrorMessage(error: unknown): string {
  if (isAxiosError(error)) {
    if (!error.response) {
      return 'Cannot reach the server. Check that the backend is running.'
    }

    const detail = (error.response.data as { detail?: unknown } | undefined)?.detail

    if (typeof detail === 'string') return detail

    // FastAPI validation errors (422) arrive as a list.
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string }
      if (first?.msg) return first.msg
    }

    return `Request failed (${error.response.status}).`
  }

  return error instanceof Error ? error.message : 'Something went wrong.'
}