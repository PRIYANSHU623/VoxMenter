import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { AlertCircle, Loader2 } from 'lucide-react'
import { getErrorMessage } from '../api/client'
import ThemeToggle from '../components/layout/ThemeToggle'
import { useAuth } from '../hooks/useAuth'

type Mode = 'login' | 'register'

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function validate(mode: Mode, email: string, password: string, confirm: string) {
  if (!EMAIL_PATTERN.test(email.trim())) return 'Enter a valid email address.'
  if (password.length < 8) return 'Password must be at least 8 characters.'
  if (mode === 'register' && password !== confirm) return 'Passwords do not match.'
  return null
}

const inputClass =
  'mt-2 h-11 w-full rounded-md border border-line bg-raised px-3 text-base text-ink placeholder:text-muted/70 transition-colors focus:border-accent disabled:opacity-60'

export default function AuthPage({ mode }: { mode: Mode }) {
  const { status, signIn, signUp } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const isLogin = mode === 'login'

  if (status === 'authenticated') return <Navigate to="/dashboard" replace />

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return

    const problem = validate(mode, email, password, confirm)
    if (problem) {
      setError(problem)
      return
    }

    setError(null)
    setSubmitting(true)
    try {
      const cleanEmail = email.trim().toLowerCase()
      if (isLogin) await signIn(cleanEmail, password)
      else await signUp(cleanEmail, password)
      // On success the auth state changes and we are redirected above.
    } catch (err) {
      setError(getErrorMessage(err))
      setSubmitting(false)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <aside className="hidden flex-col justify-between border-r border-line bg-surface p-12 lg:flex">
        <div className="font-display text-2xl font-semibold tracking-tight">
          VoxMenter<span className="text-accent">.</span>
        </div>
        <div>
          <p className="eyebrow">Speaking studio</p>
          <p className="mt-4 max-w-md font-display text-4xl leading-tight">
            Practice the answer. Hear yourself. Get better.
          </p>
          <p className="mt-6 max-w-md text-muted">
            Record your interview answers, get an honest technical and
            communication review, and watch your progress over time.
          </p>
        </div>
        <p className="text-sm text-muted">Interview practice for developers.</p>
      </aside>

      <main className="relative flex items-center justify-center px-6 py-16">
        <div className="absolute right-4 top-4">
          <ThemeToggle />
        </div>

        <div className="w-full max-w-sm">
          <div className="mb-8 font-display text-2xl font-semibold tracking-tight lg:hidden">
            VoxMenter<span className="text-accent">.</span>
          </div>

          <p className="eyebrow">{isLogin ? 'Welcome back' : 'Get started'}</p>
          <h1 className="mt-2 text-3xl font-semibold">
            {isLogin ? 'Log in' : 'Create your account'}
          </h1>

          <form onSubmit={handleSubmit} noValidate className="mt-8 space-y-5">
            <div>
              <label htmlFor="email" className="eyebrow">Email</label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={submitting}
                placeholder="you@example.com"
                className={inputClass}
              />
            </div>

            <div>
              <label htmlFor="password" className="eyebrow">Password</label>
              <input
                id="password"
                type="password"
                autoComplete={isLogin ? 'current-password' : 'new-password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={submitting}
                placeholder="At least 8 characters"
                className={inputClass}
              />
            </div>

            {!isLogin && (
              <div>
                <label htmlFor="confirm" className="eyebrow">Confirm password</label>
                <input
                  id="confirm"
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  disabled={submitting}
                  className={inputClass}
                />
              </div>
            )}

            {error && (
              <div
                role="alert"
                className="flex items-start gap-2 border-l-2 border-danger bg-surface px-3 py-2 text-sm text-danger"
              >
                <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="flex h-11 w-full items-center justify-center gap-2 rounded-md bg-accent font-medium text-accent-fg transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting && <Loader2 size={18} className="animate-spin" aria-hidden="true" />}
              {submitting
                ? isLogin ? 'Logging in…' : 'Creating account…'
                : isLogin ? 'Log in' : 'Create account'}
            </button>
          </form>

          <p className="mt-6 text-sm text-muted">
            {isLogin ? 'New to VoxMenter? ' : 'Already have an account? '}
            <Link
              to={isLogin ? '/register' : '/login'}
              className="font-medium text-ink underline decoration-accent underline-offset-4"
            >
              {isLogin ? 'Create an account' : 'Log in'}
            </Link>
          </p>
        </div>
      </main>
    </div>
  )
}