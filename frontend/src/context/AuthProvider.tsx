import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { clearToken, getToken, setToken, UNAUTHORIZED_EVENT } from '../api/client'
import { getMe, login, register } from '../api/endpoints'
import { AuthContext } from '../hooks/useAuth'
import type { AuthContextValue, AuthStatus } from '../hooks/useAuth'
import type { User } from '../types/api'

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  // If a token is saved, we must check it with the backend before trusting it.
  const [status, setStatus] = useState<AuthStatus>(
    getToken() ? 'loading' : 'unauthenticated',
  )

  // On first load: validate the saved token.
  useEffect(() => {
    if (!getToken()) return

    let cancelled = false
    getMe()
      .then((me) => {
        if (cancelled) return
        setUser(me)
        setStatus('authenticated')
      })
      .catch(() => {
        if (cancelled) return
        clearToken()
        setStatus('unauthenticated')
      })

    return () => {
      cancelled = true
    }
  }, [])

  // Logged out automatically when any request returns 401.
  useEffect(() => {
    const handleUnauthorized = () => {
      setUser(null)
      setStatus('unauthenticated')
    }
    window.addEventListener(UNAUTHORIZED_EVENT, handleUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, handleUnauthorized)
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    const data = await login(email, password)
    setToken(data.access_token)
    setUser(data.user)
    setStatus('authenticated')
  }, [])

  // The backend's register route returns no token, so we log in right after.
  const signUp = useCallback(
    async (email: string, password: string) => {
      await register(email, password)
      await signIn(email, password)
    },
    [signIn],
  )

  const signOut = useCallback(() => {
    clearToken()
    setUser(null)
    setStatus('unauthenticated')
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({ user, status, signIn, signUp, signOut }),
    [user, status, signIn, signUp, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}