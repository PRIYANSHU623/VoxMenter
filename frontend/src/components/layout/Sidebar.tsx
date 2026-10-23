import { NavLink } from 'react-router-dom'
import { navItems } from './navItems'
import ThemeToggle from './ThemeToggle'
import { LogOut } from 'lucide-react'
import { useAuth } from '../../hooks/useAuth'

export default function Sidebar() {
  const { user, signOut } = useAuth()
  return (
    <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-line bg-canvas px-6 py-8 md:flex">
      <div>
        <div className="font-display text-2xl font-semibold tracking-tight">
          VoxMenter<span className="text-accent">.</span>
        </div>
        <p className="eyebrow mt-1">Speaking studio</p>
      </div>

      <nav aria-label="Main" className="mt-12 flex-1">
        <p className="eyebrow mb-3">Workspace</p>
        <ul className="border-t border-line">
          {navItems.map(({ to, label }, index) => (
            <li key={to} className="border-b border-line">
              <NavLink
                to={to}
                className={({ isActive }) =>
                  [
                    'flex items-center gap-4 py-3.5 text-sm transition-colors',
                    isActive
                      ? 'font-semibold text-ink'
                      : 'text-muted hover:text-ink',
                  ].join(' ')
                }
              >
                {({ isActive }) => (
                  <>
                    <span className="font-mono text-xs tabular-nums text-muted">
                      0{index + 1}
                    </span>
                    <span>{label}</span>
                    {isActive && (
                      <span
                        aria-hidden="true"
                        className="ml-auto h-1.5 w-1.5 rounded-full bg-accent"
                      />
                    )}
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="border-t border-line pt-4">
        <p className="truncate text-xs text-muted" title={user?.email}>
          {user?.email}
        </p>
        <div className="mt-2 flex items-center justify-between">
          <button
            type="button"
            onClick={signOut}
            className="inline-flex h-11 items-center gap-2 text-sm text-muted transition-colors hover:text-ink"
          >
            <LogOut size={16} aria-hidden="true" />
            Log out
          </button>
          <ThemeToggle />
        </div>
      </div>
    </aside>
  )
}