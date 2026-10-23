import { NavLink } from 'react-router-dom'
import { navItems } from './navItems'
import ThemeToggle from './ThemeToggle'
import { LogOut } from 'lucide-react'
import { useAuth } from '../../hooks/useAuth'

// Shown only below the md breakpoint. The desktop Sidebar covers larger screens.
export function MobileTopBar() {
  const { signOut } = useAuth()
  return (
    <header className="sticky top-0 z-20 flex items-center justify-between border-b border-line bg-canvas/95 px-4 py-2 backdrop-blur md:hidden">
      {/* <div className="flex items-center gap-3">
        <span
          aria-hidden="true"
          className="flex h-8 w-8 items-center justify-center rounded-md bg-accent text-sm font-bold text-accent-fg"
        >
          V
        </span>
        <span className="text-lg font-semibold tracking-tight">VoxMenter</span>
      </div> */}
      <span className="font-display text-xl font-semibold tracking-tight">
        VoxMenter<span className="text-accent">.</span>
      </span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={signOut}
          aria-label="Log out"
          title="Log out"
          className="inline-flex h-11 w-11 items-center justify-center rounded-md border border-line text-muted transition-colors hover:bg-surface hover:text-ink"
        >
          <LogOut size={20} aria-hidden="true" />
        </button>
        <ThemeToggle />
      </div>
    </header>
  )
}

export function MobileTabBar() {
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      <ul className="grid grid-cols-4">
        {navItems.map(({ to, label, icon: Icon }) => (
          <li key={to}>
            <NavLink
              to={to}
              className={({ isActive }) =>
                [
                  'flex min-h-14 flex-col items-center justify-center gap-1 text-xs font-medium transition-colors',
                  isActive ? 'text-accent' : 'text-muted hover:text-ink',
                ].join(' ')
              }
            >
              <Icon size={20} aria-hidden="true" />
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}